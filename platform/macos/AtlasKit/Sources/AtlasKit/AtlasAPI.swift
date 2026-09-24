import Foundation

/// Typed async calls the app makes to atlas-core. Every reply is either a result or an
/// `AtlasAPIError`; retry safety is declared per method, next to the call.
public final class AtlasAPI {
    public let transport: AtlasTransport
    /// Priority control lane (A3-04, spec 6.2): its own connection and serial queue, so "stop" is never
    /// queued behind a send, an upload, a reconnect or a slow model call on `transport`.
    public let control: AtlasTransport
    /// Upload chunk: 512 KiB -> ~699 KB of base64, under the core's 700 000 character limit.
    public static let uploadChunk = 512 * 1024
    public static let readChunk = 512 * 1024
    public static let maxAttachmentBytes = 50 * 1024 * 1024

    public init(transport: AtlasTransport, control: AtlasTransport? = nil) {
        self.transport = transport
        self.control = control ?? transport
    }

    private var employeeId: String { transport.employeeId ?? "" }

    @discardableResult
    func read(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
        try await transport.call(method, params, retrySafe: true)
    }

    @discardableResult
    func write(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
        try await transport.call(method, params, retrySafe: false)
    }

    // MARK: status

    public func health() async throws -> [String: Any] { try await read("system.health") }
    public func identity() async throws -> [String: Any] { try await read("identity.get") }

    public func tasks() async throws -> [[String: Any]] {
        try await read("tasks.list", ["employee_id": employeeId, "limit": 100])["tasks"] as? [[String: Any]] ?? []
    }

    public func events(after cursor: Int) async throws -> (events: [[String: Any]], cursor: Int) {
        let r = try await read("events.subscribe", ["employee_id": employeeId, "after_sequence_id": cursor])
        return (r["events"] as? [[String: Any]] ?? [], r["last_sequence_id"] as? Int ?? cursor)
    }

    // MARK: conversation

    public func currentConversation() async throws -> String {
        try await read("conversations.current")["conversation_id"] as? String ?? ""
    }

    public func history(conversationId: String, before: String? = nil, afterSequence: Int? = nil,
                        changedSinceRevision: Int? = nil, limit: Int = 50) async throws
        -> (messages: [[String: Any]], hasMore: Bool)
    {
        var p: [String: Any] = ["conversation_id": conversationId, "limit": limit]
        if let before { p["before_message_id"] = before }
        if let afterSequence { p["after_sequence"] = afterSequence }  // A3-23: gap-free catch-up
        if let changedSinceRevision { p["changed_since_revision"] = changedSinceRevision }  // A3-23: upserts
        let r = try await read("conversations.history", p)
        return (r["messages"] as? [[String: Any]] ?? [], r["has_more"] as? Bool ?? false)
    }

    /// Retry-safe: the core deduplicates by `clientMessageId`, so a resend after a reconnect returns
    /// what already happened instead of doing it twice.
    public func send(conversationId: String, text: String, clientMessageId: String, delegate: Bool = false,
                     artifactIds: [String] = [], replyTo: String? = nil, taskId: String? = nil) async throws
        -> [String: Any]
    {
        var p: [String: Any] = [
            "employee_id": employeeId, "conversation_id": conversationId, "client_message_id": clientMessageId,
            "text": text, "intent": delegate ? "delegate" : "auto",
        ]
        if !artifactIds.isEmpty { p["artifact_ids"] = artifactIds }
        if let replyTo { p["reply_to_message_id"] = replyTo }
        if let taskId { p["task_id"] = taskId }
        return try await transport.call("conversations.send", p, retrySafe: true)
    }

    /// "Pare tudo" through the control lane. Repeating it is harmless (nothing more to pause).
    public func stopAll() async throws -> [String: Any] {
        try await control.call("control.stop", ["employee_id": control.employeeId ?? employeeId], retrySafe: true)
    }

    // MARK: memory and files screens (N06/N12)

    public func memories(statuses: [String] = ["proposed", "confirmed", "disputed"]) async throws -> [[String: Any]] {
        try await read("memories.list", ["statuses": statuses, "limit": 300])["memories"] as? [[String: Any]] ?? []
    }

    public func forgetPreview(_ memoryId: String) async throws -> [String: Any] {
        try await read("memories.forget_preview", ["memory_id": memoryId])
    }

    public func forget(_ memoryId: String, scope: String) async throws -> [String: Any] {
        try await write("memories.delete", ["memory_id": memoryId, "scope": scope])
    }

    public func correctMemory(_ memoryId: String, version: Int, content: String) async throws {
        try await write("memories.correct", ["memory_id": memoryId, "expected_version": version, "content": content])
    }

    public func exportMemories() async throws -> [String: Any] { try await read("memories.export") }

    public func files() async throws -> [[String: Any]] {
        try await read("artifacts.all", ["limit": 300])["artifacts"] as? [[String: Any]] ?? []
    }

    public func confirmMemory(_ memoryId: String) async throws {
        try await write("memories.confirm", ["memory_id": memoryId])
    }

    // MARK: work

    @discardableResult
    public func control(_ method: String, taskId: String, version: Int) async throws -> [String: Any] {
        try await write(method, ["task_id": taskId, "expected_version": version])
    }

    public func artifacts(taskId: String) async throws -> [[String: Any]] {
        try await read("artifacts.list", ["task_id": taskId])["artifacts"] as? [[String: Any]] ?? []
    }

    public func approvals() async throws -> [[String: Any]] {
        try await read("approvals.list")["approvals"] as? [[String: Any]] ?? []
    }

    public func decide(approval: [String: Any], approve: Bool) async throws {
        try await write("approvals.decide", [
            "approval_id": approval["approval_id"] ?? "", "decision": approve ? "APPROVE" : "REJECT",
            "params_hash": approval["params_hash"] ?? "", "nonce": approval["nonce"] ?? "",
        ])
    }

    // MARK: attachments

    /// Copies ONE file the owner chose into Atlas (explicit import; the original is never modified).
    public func importFile(data: Data, name: String) async throws -> [String: Any] {
        guard data.count <= AtlasAPI.maxAttachmentBytes else {
            throw AtlasAPIError(code: "INVALID_INPUT", message: "o arquivo passa de 50 MB")
        }
        let ref = UUID().uuidString.lowercased()
        var offset = 0
        repeat {
            let end = min(offset + AtlasAPI.uploadChunk, data.count)
            let chunk = data.subdata(in: offset..<end)
            // Retry-safe: the core accepts an identical resend of the same offset.
            _ = try await transport.call("artifacts.upload", [
                "upload_ref": ref, "offset": offset, "data_b64": chunk.base64EncodedString(),
            ], retrySafe: true)
            offset = end
        } while offset < data.count
        // A3-22: the import is a receipt per upload_ref, so a lost reply is recovered by asking again with
        // the same ref (the core returns the artifact it already created; never a duplicate).
        return try await transport.call("artifacts.import", [
            "employee_id": employeeId, "upload_ref": ref, "declared_name": name,
            "expected_sha256": Hashing.sha256Hex(data),
        ], retrySafe: true)
    }

    /// Name (with extension) of a stored artifact, for the save panel (A3-32).
    public func artifactName(_ artifactId: String) async throws -> String {
        let r = try await read("artifacts.read", ["artifact_id": artifactId, "offset": 0, "length": 1])
        return r["name"] as? String ?? ""
    }

    /// Reads a whole artifact in chunks and verifies each chunk and the final SHA-256.
    public func readArtifact(_ artifactId: String, maxBytes: Int = Int.max) async throws
        -> (data: Data, name: String, mime: String, sha256: String)
    {
        var data = Data()
        var name = "", mime = "", sha = ""
        var offset = 0
        while true {
            let length = min(AtlasAPI.readChunk, max(1, maxBytes - offset))
            let r = try await read("artifacts.read", ["artifact_id": artifactId, "offset": offset, "length": length])
            let piece = Data(base64Encoded: r["data_b64"] as? String ?? "") ?? Data()
            guard Hashing.sha256Hex(piece) == r["chunk_sha256"] as? String else {
                throw AtlasAPIError(code: "INTEGRITY", message: "trecho recebido não confere com o hash")
            }
            data.append(piece)
            name = r["name"] as? String ?? name
            mime = r["mime_type"] as? String ?? mime
            sha = r["sha256"] as? String ?? sha
            offset += piece.count
            if r["eof"] as? Bool == true || piece.isEmpty || offset >= maxBytes { break }
        }
        return (data, name, mime, sha)
    }

    // MARK: settings and intelligence

    public func settings() async throws -> [String: Any] { try await read("settings.get") }

    public func registerKey(_ key: String) async throws {
        try await write("credentials.register", ["provider": "openai", "secret_b64": Data(key.utf8).base64EncodedString()])
    }

    /// Guarded by `expected_revision`: a stale form is rejected with VERSION_CONFLICT, never merged.
    public func saveSettings(_ settings: [String: Any], expectedRevision: Int) async throws -> Int {
        try await write("settings.update", ["expected_revision": expectedRevision, "settings": settings])["revision"]
            as? Int ?? expectedRevision
    }

    public func testIntelligence(modelId: String, maxCents: Int) async throws -> [String: Any] {
        try await write("intelligence.check", ["model_id": modelId, "max_cost_minor": maxCents])["report"]
            as? [String: Any] ?? [:]
    }

    /// Reference configuration with the owner's ceilings (minor units).
    public static func settingsDocument(monthlyMinor: Int, perTaskMinor: Int, modelId: String, currency: String = "USD",
                                        acceptReferencePrices: Bool, mode: String = "automatic",
                                        lightModelId: String? = nil, deepModelId: String? = nil) -> [String: Any]
    {
        // N13: the mode chosen in plain words (Automático/Econômico/Máxima qualidade) is a real setting;
        // model ids stay in "Avançado". Unvalidated profiles are never used by the core.
        var profiles: [String: Any] = ["general": ["provider": "openai", "model_id": modelId]]
        if let lightModelId, !lightModelId.isEmpty { profiles["light"] = ["provider": "openai", "model_id": lightModelId] }
        if let deepModelId, !deepModelId.isEmpty { profiles["deep"] = ["provider": "openai", "model_id": deepModelId] }
        return [
            "schema_version": "1.0",
            "intelligence": [
                "mode": mode, "default_profile": "general",
                "profiles": profiles,
                "allow_cross_provider_fallback": false, "max_parallel_research_workers": 2,
                "max_external_effect_workers": 1,
            ] as [String: Any],
            "budget": [
                "currency": currency, "monthly_limit_minor": monthlyMinor, "per_task_limit_minor": perTaskMinor,
                "require_owner_setup_before_paid_calls": true, "warning_percentages": [70, 90],
                "accept_reference_prices": acceptReferencePrices,
            ] as [String: Any],
            "security": [
                "host_shell_enabled": false, "unreviewed_code_network_enabled": false,
                "purchases_require_scoped_approval": true, "raw_secrets_in_model_context": false,
            ],
        ]
    }
}
