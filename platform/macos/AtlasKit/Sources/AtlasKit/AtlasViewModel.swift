import Combine
import Foundation

public struct ChatMessage: Identifiable, Equatable {
    public let id: String
    public let role: String  // owner | employee | system
    public let kind: String  // chat, ack, question, answer, status, result, control, memory, correction, error
    public let content: String
    public let taskId: String?
    public let artifactId: String?
    public let memoryId: String?
    public let createdAt: String
    /// Stable order assigned by the core (0 when unknown) and global change revision (A3-23).
    public let sequence: Int
    public let revision: Int

    init(_ d: [String: Any]) {
        id = d["message_id"] as? String ?? UUID().uuidString
        role = d["role"] as? String ?? "system"
        kind = d["kind"] as? String ?? "chat"
        content = d["content"] as? String ?? ""
        taskId = d["task_id"] as? String
        artifactId = d["artifact_id"] as? String
        memoryId = d["memory_id"] as? String
        createdAt = d["created_at"] as? String ?? ""
        sequence = d["sequence"] as? Int ?? 0
        revision = d["revision"] as? Int ?? 0
    }

    public var isOwner: Bool { role == "owner" }
}

public struct TaskItem: Identifiable, Equatable {
    public let id: String
    public let objective: String
    public let state: String
    public let version: Int
    public let blockedReason: String?
    /// Exactly what the core accepts in this state (A3-30); the UI never guesses buttons.
    public let availableActions: [String]

    init(_ d: [String: Any]) {
        id = d["task_id"] as? String ?? ""
        objective = d["objective"] as? String ?? ""
        state = d["state"] as? String ?? ""
        version = d["version"] as? Int ?? 0
        blockedReason = d["blocked_reason"] as? String
        availableActions = d["available_actions"] as? [String] ?? []
    }

    public var stateText: String {
        [
            "CREATED": "Na fila", "UNDERSTANDING": "Entendendo", "PLANNING": "Planejando", "READY": "Na fila",
            "RUNNING": "Em execução", "WAITING_USER": "Aguardando você", "WAITING_APPROVAL": "Aguardando aprovação",
            "BLOCKED": "Bloqueada", "PAUSED": "Pausada", "RETRYING": "Nova tentativa agendada",
            "VERIFYING": "Verificando", "COMPLETED": "Concluída", "FAILED": "Falhou", "CANCELLED": "Cancelada",
        ][state] ?? state
    }

    public static let actionLabels: [String: String] = [
        "pause": "Pausar", "resume": "Retomar", "cancel": "Cancelar", "reevaluate": "Reavaliar bloqueio",
        "reconcile": "Conferir ação incerta",
    ]
}

public struct Attachment: Identifiable, Equatable {
    public let id: String  // artifact_id
    public let name: String
    public let sizeBytes: Int
    public let sha256: String
}

public struct MemoryItem: Identifiable, Equatable {
    public let id: String
    public let type: String
    public let status: String
    public let sensitivity: String
    public let version: Int
    public let content: String
    public let validFrom: String?
    public let validUntil: String?
    public let sourceKind: String

    init(_ d: [String: Any]) {
        id = d["memory_id"] as? String ?? ""
        type = d["type"] as? String ?? ""
        status = d["status"] as? String ?? ""
        sensitivity = d["sensitivity"] as? String ?? ""
        version = d["version"] as? Int ?? 1
        content = d["content"] as? String ?? ""
        validFrom = d["valid_from"] as? String
        validUntil = d["valid_until"] as? String
        sourceKind = d["source_kind"] as? String ?? ""
    }

    public var typeText: String {
        ["IDENTITY": "Identidade", "PREFERENCE": "Preferência", "FACT": "Fato", "EPISODE": "Episódio",
         "PROCEDURE": "Procedimento"][type] ?? type
    }

    public var statusText: String {
        ["proposed": "aguardando confirmação", "confirmed": "confirmada", "disputed": "contestada",
         "deleted": "não usada"][status] ?? status
    }
}

public struct FileItem: Identifiable, Equatable {
    public let id: String
    public let name: String
    public let version: Int
    public let sizeBytes: Int
    public let relation: String?
    public let analysisState: String?

    init(_ d: [String: Any]) {
        id = d["id"] as? String ?? ""
        name = d["name"] as? String ?? ""
        version = d["version"] as? Int ?? 1
        sizeBytes = d["size_bytes"] as? Int ?? 0
        relation = d["relation"] as? String
        analysisState = d["analysis_state"] as? String
    }

    public var analysisText: String {
        ["READY_FOR_ANALYSIS": "compreendido", "PARTIAL": "compreendido em parte",
         "UNSUPPORTED": "armazenado, ainda não analisável", "FAILED": "não foi possível ler"][analysisState ?? ""]
            ?? "—"
    }
}

/// Result of one file of an import queue (A3-21): every file ends imported or with an explicit error.
public struct ImportResult: Identifiable, Equatable {
    public let id = UUID()
    public let name: String
    public let artifactId: String?
    public let error: String?
    public var ok: Bool { artifactId != nil }
}

/// The immutable request that is sent and, if needed, resent as-is (A3-22). Changing the text or the
/// attachments in the window creates a NEW envelope with a new id; the old one is never reinterpreted.
public struct SendEnvelope: Equatable {
    public let clientId: String
    public let text: String
    public let delegate: Bool
    public let artifactIds: [String]
    public let replyTo: String?
    public let taskId: String?
}

public struct SettingsForm: Equatable {
    public var monthlyMinor = 500
    public var perTaskMinor = 100
    public var modelId = "gpt-6-sol"  // "general" profile (default)
    public var lightModelId = "gpt-6-luna"
    public var deepModelId = "gpt-6-astra"
    public var mode = "automatic"  // automatic | economic | max_quality | manual
    /// Per profile, what the core says: validated for the current key? priced? (spec 11.4)
    public var profileStatus: [String: Bool] = [:]
    public var currency = "USD"
    public var acceptReferencePrices = false
    public var revision = 0
    public var priceTable = ""
    public var pricesVerified = false

    public init() {}
}

/// UI state and actions of the Atlas window, independent of SwiftUI so it can be tested headless on
/// CI with a fake transport. All work is async; nothing here blocks the main actor on I/O.
@MainActor
public final class AtlasViewModel: ObservableObject {
    @Published public private(set) var connection: ConnectionState = .disconnected
    @Published public private(set) var name = "Atlas"
    @Published public private(set) var intelligenceReady = false
    @Published public private(set) var intelligenceText = "—"
    @Published public private(set) var components: [String: String] = [:]
    @Published public private(set) var messages: [ChatMessage] = []
    @Published public private(set) var hasOlderMessages = false
    @Published public private(set) var tasks: [TaskItem] = []
    @Published public private(set) var approvals: [[String: Any]] = []
    @Published public private(set) var attachments: [Attachment] = []
    @Published public private(set) var importResults: [ImportResult] = []
    @Published public var settings = SettingsForm()
    @Published public private(set) var lastError: String?
    @Published public private(set) var notice: String?
    @Published public private(set) var isSending = false
    @Published public private(set) var isSavingSettings = false
    @Published public private(set) var isChecking = false
    @Published public private(set) var isAttaching = false
    @Published public private(set) var isStopping = false
    @Published public private(set) var eventCursor = 0
    /// The exact envelope kept after a failed send, so "Tentar de novo" resends the SAME request.
    @Published public private(set) var failedDraft: SendEnvelope?
    /// True while the outcome of a send is unknown (reply lost): "confirmando recebimento".
    @Published public private(set) var confirmingReceipt = false
    /// Explicit targets chosen by the owner (A3-14, A3-15): answer THIS question / talk about THIS task.
    @Published public private(set) var memories: [MemoryItem] = []
    @Published public private(set) var files: [FileItem] = []
    @Published public private(set) var replyTarget: ChatMessage?
    @Published public private(set) var taskTarget: TaskItem?

    public let api: AtlasAPI
    public private(set) var conversationId = ""
    public var restartServices: (() async throws -> Void)?
    public var serviceStatus: (() -> String)?
    private var refreshing = false
    private var errorFromRefresh = false
    private var importQueue: [URL] = []
    private var maxSequence = 0
    private var maxRevision = 0

    public init(api: AtlasAPI) {
        self.api = api
    }

    public nonisolated static func friendly(_ error: Error) -> String {
        if let e = error as? AtlasAPIError {
            switch e.code {
            case "VERSION_CONFLICT": return "Isso mudou em outro lugar. Recarreguei os dados; revise e tente de novo."
            case AtlasAPIError.unknownOutcomeCode, AtlasAPIError.unavailableCode: return e.message
            case "UNAUTHORIZED": return "Não autorizado: \(e.message)"
            case "INVALID_INPUT": return "Dados inválidos: \(e.message)"
            case "MODEL_UNSUPPORTED": return "Inteligência indisponível: \(e.message)"
            default: return "\(e.code): \(e.message)"
            }
        }
        return AtlasConnection.describe(error)
    }

    public func setConnectionState(_ state: ConnectionState) { connection = state }

    /// Runs an owner action; its error stays visible until the next owner action succeeds.
    private func attempt(_ body: () async throws -> Void) async {
        do {
            try await body()
            lastError = nil
            errorFromRefresh = false
        } catch is CancellationError {
            return
        } catch {
            lastError = Self.friendly(error)
            errorFromRefresh = false
        }
    }

    // MARK: lifecycle

    public func start() async {
        await attempt {
            name = try await api.identity()["name"] as? String ?? name
            connection = .connected
            try await loadSettings()
            conversationId = try await api.currentConversation()
            let page = try await api.history(conversationId: conversationId)
            messages = []
            upsert(page.messages.map(ChatMessage.init))
            hasOlderMessages = page.hasMore
        }
        await refresh()
    }

    /// Periodic refresh. Guarded so overlapping timers never stack requests.
    public func refresh() async {
        guard !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            let h = try await api.health()
            let comps = h["components"] as? [String: Any] ?? [:]
            components = comps.compactMapValues { $0 as? String }
            intelligenceReady = comps["intelligence"] as? String == "ready"
            intelligenceText = intelligenceReady ? "Pronta" : "Não configurada: \(h["intelligence_reason"] as? String ?? "")"
            connection = .connected
            tasks = try await api.tasks().map(TaskItem.init)
            approvals = try await api.approvals()
            let ev = try await api.events(after: eventCursor)  // cursor survives reconnects
            eventCursor = ev.cursor
            if !conversationId.isEmpty { try await reconcileHistory() }
            if errorFromRefresh {  // a background refresh only clears the error it caused itself
                lastError = nil
                errorFromRefresh = false
            }
        } catch is CancellationError {
            return
        } catch {
            if lastError == nil || errorFromRefresh {
                lastError = Self.friendly(error)
                errorFromRefresh = true
            }
        }
    }

    /// A3-23: fetch EVERYTHING after the last confirmed sequence (no gap after 50+ messages), then every
    /// message changed since the last seen revision, and upsert both. Cursors move only after applying.
    private func reconcileHistory() async throws {
        var after = maxSequence
        while true {
            let page = try await api.history(conversationId: conversationId, afterSequence: after, limit: 200)
            let batch = page.messages.map(ChatMessage.init)
            upsert(batch)
            guard page.hasMore, let last = batch.last, last.sequence > after else { break }
            after = last.sequence
        }
        if maxRevision > 0 {
            var since = maxRevision
            while true {
                let page = try await api.history(conversationId: conversationId, changedSinceRevision: since, limit: 200)
                let batch = page.messages.map(ChatMessage.init)
                upsert(batch)
                let top = batch.map(\.revision).max() ?? since
                guard page.hasMore, top > since else { break }
                since = top
            }
        }
    }

    /// Insert or replace by id; keep the core's order by sequence (messages without one keep arrival order).
    func upsert(_ newer: [ChatMessage]) {
        for m in newer {
            if let i = messages.firstIndex(where: { $0.id == m.id }) {
                if m.revision >= messages[i].revision { messages[i] = m }
            } else if m.sequence > 0, let j = messages.firstIndex(where: { $0.sequence > m.sequence }) {
                messages.insert(m, at: j)
            } else {
                messages.append(m)
            }
            maxSequence = max(maxSequence, m.sequence)
            maxRevision = max(maxRevision, m.revision)
        }
    }

    public func loadOlder() async {
        guard hasOlderMessages, let first = messages.first else { return }
        await attempt {
            let page = try await api.history(conversationId: conversationId, before: first.id)
            let older = page.messages.map(ChatMessage.init).filter { m in !messages.contains { $0.id == m.id } }
            messages = older + messages
            hasOlderMessages = page.hasMore
        }
    }

    // MARK: conversation

    /// Explicit target for the next message (the owner's "Responder" on a question).
    public func reply(to question: ChatMessage) {
        replyTarget = question
        taskTarget = nil
    }

    /// Explicit task for the next message ("Responder nesta tarefa"): corrections/attachments go there.
    public func talk(about task: TaskItem) {
        taskTarget = task
        replyTarget = nil
    }

    public func clearTargets() {
        replyTarget = nil
        taskTarget = nil
    }

    public func send(_ text: String, delegate: Bool = false) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        // A3-15: attachments travel with the message but never decide the intent; A3-22: one immutable
        // envelope, built once, with everything that defines the request.
        let envelope = SendEnvelope(clientId: UUID().uuidString.lowercased(), text: trimmed, delegate: delegate,
                                    artifactIds: attachments.map(\.id), replyTo: replyTarget?.id,
                                    taskId: taskTarget?.id)
        await deliver(envelope)
    }

    public func retryFailedSend() async {
        guard let draft = failedDraft, !isSending else { return }
        await deliver(draft)  // the SAME envelope, even if the window's attachments changed meanwhile
    }

    private func deliver(_ e: SendEnvelope) async {
        isSending = true
        defer { isSending = false }
        do {
            let out = try await api.send(conversationId: conversationId, text: e.text, clientMessageId: e.clientId,
                                         delegate: e.delegate, artifactIds: e.artifactIds, replyTo: e.replyTo,
                                         taskId: e.taskId)
            failedDraft = nil
            confirmingReceipt = out["intent"] as? String == "processing"
            attachments.removeAll { e.artifactIds.contains($0.id) }
            if replyTarget?.id == e.replyTo { replyTarget = nil }
            if taskTarget?.id == e.taskId { taskTarget = nil }
            lastError = nil
            var fresh: [ChatMessage] = []
            if let m = out["message"] as? [String: Any] { fresh.append(ChatMessage(m)) }
            if let r = out["reply"] as? [String: Any] { fresh.append(ChatMessage(r)) }
            upsert(fresh)
        } catch {
            failedDraft = e
            confirmingReceipt = (error as? AtlasAPIError)?.code == AtlasAPIError.unknownOutcomeCode
            lastError = Self.friendly(error)
        }
    }

    /// "Delegar como tarefa" on an earlier owner message (no new owner message is created).
    public func delegate(message: ChatMessage) async {
        guard message.isOwner, !isSending else { return }
        isSending = true
        defer { isSending = false }
        await attempt {
            let out = try await api.send(conversationId: conversationId, text: message.content,
                                         clientMessageId: UUID().uuidString.lowercased(), delegate: true,
                                         replyTo: message.id)
            if let r = out["reply"] as? [String: Any] { upsert([ChatMessage(r)]) }
        }
    }

    /// A3-04: never gated by `isSending`/`isAttaching` and never routed through the conversation. The
    /// order goes through the control lane; the reply says what stopped and what was already sent.
    public func stopAll() async {
        isStopping = true
        defer { isStopping = false }
        do {
            let r = try await api.stopAll()
            notice = Self.stopText(r)
            lastError = nil
        } catch {
            lastError = "A parada NÃO foi confirmada: \(Self.friendly(error)). Tente de novo."
        }
        Task { await self.refresh() }  // the main lane may still be busy; do not wait for it here
    }

    public nonisolated static func stopText(_ r: [String: Any]) -> String {
        let paused = (r["paused_tasks"] as? [Any])?.count ?? 0
        let inFlight = (r["in_flight_actions"] as? [Any])?.count ?? 0
        let unknown = (r["unknown_actions"] as? [Any])?.count ?? 0
        var parts = ["Parei: \(paused) tarefa(s) pausada(s); nenhum passo novo será iniciado."]
        if inFlight > 0 {
            parts.append("\(inFlight) ação(ões) já tinham sido enviadas; pedi a interrupção, mas o que foi enviado não é desfeito.")
        }
        if unknown > 0 { parts.append("\(unknown) ação(ões) com resultado incerto serão conferidas antes de qualquer repetição.") }
        return parts.joined(separator: " ")
    }

    // MARK: Memory and Files screens (N06/N12)

    public func loadMemories() async {
        await attempt { memories = try await api.memories().map(MemoryItem.init) }
    }

    public func confirmMemory(id: String) async {
        await attempt {
            try await api.confirmMemory(id)
            notice = "Memória confirmada."
        }
        await loadMemories()
    }

    /// Plain-language scope of a deletion, shown BEFORE the owner confirms it (spec 8.4).
    public func forgetPreviewText(_ item: MemoryItem) async -> String {
        do {
            let r = try await api.forgetPreview(item.id)
            return "Serão apagados: esta memória (\(r["memory_versions"] as? Int ?? 0) versão(ões)), "
                + "\(r["messages"] as? Int ?? 0) mensagem(ns) da conversa e "
                + "\(r["observations"] as? Int ?? 0) registro(s) de trabalho que a contêm. "
                + (r["outside_atlas"] as? String ?? "")
        } catch {
            return Self.friendly(error)
        }
    }

    /// scope: "stop_using" (keep history visible, never use again) or "erase" (remove the content).
    public func forget(_ item: MemoryItem, scope: String) async {
        await attempt {
            _ = try await api.forget(item.id, scope: scope)
            notice = scope == "erase" ? "Conteúdo apagado do Atlas." : "O Atlas não vai mais usar esta memória."
        }
        await loadMemories()
    }

    public func correctMemory(_ item: MemoryItem, newContent: String) async {
        let text = newContent.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        await attempt {
            try await api.correctMemory(item.id, version: item.version, content: text)
            notice = "Memória corrigida (nova versão; a anterior fica no histórico)."
        }
        await loadMemories()
    }

    /// Writes the export (manifest + memories) to the file the owner chose.
    @discardableResult
    public func exportMemories(to destination: URL) async -> Bool {
        do {
            let doc = try await api.exportMemories()
            let data = try JSONSerialization.data(withJSONObject: doc, options: [.prettyPrinted, .sortedKeys])
            try await Task.detached(priority: .userInitiated) { try data.write(to: destination, options: .atomic) }.value
            notice = "Memórias exportadas para \(destination.lastPathComponent)."
            return true
        } catch {
            lastError = Self.friendly(error)
            return false
        }
    }

    public func loadFiles() async {
        await attempt { files = try await api.files().map(FileItem.init) }
    }

    public func confirmMemory(_ message: ChatMessage) async {
        guard let id = message.memoryId else { return }
        await attempt {
            try await api.confirmMemory(id)
            notice = "Memória confirmada."
        }
    }

    // MARK: attachments

    /// A3-21: a queue, one file at a time, with a result per file. A drop of ten files while another
    /// import runs never discards any: they wait their turn and each one ends imported or failed.
    public func attach(fileURLs urls: [URL]) async {
        importQueue.append(contentsOf: urls)
        guard !isAttaching else { return }  // the running loop below picks them up
        isAttaching = true
        defer { isAttaching = false }
        while !importQueue.isEmpty {
            let url = importQueue.removeFirst()
            importResults.append(await importOne(url))
        }
        let failed = importResults.filter { !$0.ok }
        if !failed.isEmpty {
            lastError = "\(failed.count) arquivo(s) não foram anexados: "
                + failed.map { "\($0.name) (\($0.error ?? "erro"))" }.joined(separator: "; ")
        }
    }

    public func attach(fileURL: URL) async { await attach(fileURLs: [fileURL]) }

    public func clearImportResults() { importResults = [] }

    private func importOne(_ url: URL) async -> ImportResult {
        let name = url.lastPathComponent
        do {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true else {
                throw AtlasAPIError(code: "INVALID_INPUT", message: "escolha um arquivo comum (não pasta nem atalho)")
            }
            guard (values.fileSize ?? 0) <= AtlasAPI.maxAttachmentBytes else {
                throw AtlasAPIError(code: "INVALID_INPUT", message: "o arquivo passa de 50 MB")
            }
            let data = try await Task.detached(priority: .userInitiated) { try Data(contentsOf: url) }.value
            let r = try await api.importFile(data: data, name: name)
            let a = Attachment(id: r["artifact_id"] as? String ?? "", name: r["name"] as? String ?? name,
                               sizeBytes: r["size_bytes"] as? Int ?? data.count, sha256: r["sha256"] as? String ?? "")
            attachments.append(a)
            return ImportResult(name: name, artifactId: a.id, error: nil)
        } catch {
            return ImportResult(name: name, artifactId: nil, error: Self.friendly(error))
        }
    }

    public func removeAttachment(_ a: Attachment) { attachments.removeAll { $0.id == a.id } }

    public func preview(artifactId: String) async -> String {
        do {
            let r = try await api.readArtifact(artifactId, maxBytes: Preview.maxBytes + 1)
            return Preview.text(mime: r.mime, data: r.data) ?? "Pré-visualização indisponível para \(r.mime). Use «Salvar como…»."
        } catch {
            return Self.friendly(error)
        }
    }

    /// A3-32: the save panel starts with the artifact's real name and extension.
    public func suggestedFileName(artifactId: String) async -> String {
        (try? await api.artifactName(artifactId)).flatMap { $0.isEmpty ? nil : $0 } ?? "entrega"
    }

    /// Save-as: the owner picked `destination` in a save panel (which already asked before replacing
    /// an existing file). The content is written only after the full SHA-256 matches the core's hash.
    @discardableResult
    public func export(artifactId: String, to destination: URL) async -> String? {
        do {
            let r = try await api.readArtifact(artifactId)
            let actual = Hashing.sha256Hex(r.data)
            guard actual == r.sha256 else {
                throw AtlasAPIError(code: "INTEGRITY", message: "o conteúdo recebido não confere com o hash guardado")
            }
            try await Task.detached(priority: .userInitiated) { try r.data.write(to: destination, options: .atomic) }.value
            notice = "Salvo em \(destination.lastPathComponent). SHA-256 \(actual.prefix(16))…"
            lastError = nil
            return actual
        } catch {
            lastError = Self.friendly(error)
            return nil
        }
    }

    // MARK: work and approvals

    public func artifacts(of task: TaskItem) async -> [[String: Any]] {
        (try? await api.artifacts(taskId: task.id)) ?? []
    }

    /// A3-30: only actions the core listed for this task are executed.
    public func perform(_ action: String, on task: TaskItem) async {
        guard task.availableActions.contains(action) else {
            lastError = "Essa ação não está disponível para a tarefa no estado atual."
            return
        }
        let method = ["pause": "tasks.pause", "resume": "tasks.resume", "cancel": "tasks.cancel",
                      "reevaluate": "tasks.reevaluate", "reconcile": "tasks.reevaluate"][action] ?? ""
        await attempt {
            let out = try await api.control(method, taskId: task.id, version: task.version)
            if let why = out["explanation"] as? String { notice = why }
        }
        await refresh()
    }

    public func control(_ method: String, _ task: TaskItem) async {
        let action = ["tasks.pause": "pause", "tasks.resume": "resume", "tasks.cancel": "cancel"][method] ?? method
        await perform(action, on: task)
    }

    public func decide(_ approval: [String: Any], approve: Bool) async {
        await attempt { try await api.decide(approval: approval, approve: approve) }
        await refresh()
    }

    // MARK: settings and intelligence

    public func loadSettings() async throws {
        let r = try await api.settings()
        var form = SettingsForm()
        form.revision = r["revision"] as? Int ?? 0
        form.priceTable = r["price_table"] as? String ?? ""
        form.pricesVerified = r["prices_verified"] as? Bool ?? false
        if let s = r["settings"] as? [String: Any] {
            let budget = s["budget"] as? [String: Any] ?? [:]
            form.monthlyMinor = budget["monthly_limit_minor"] as? Int ?? form.monthlyMinor
            form.perTaskMinor = budget["per_task_limit_minor"] as? Int ?? form.perTaskMinor
            form.currency = budget["currency"] as? String ?? form.currency
            form.acceptReferencePrices = budget["accept_reference_prices"] as? Bool ?? false
            let intel = s["intelligence"] as? [String: Any] ?? [:]
            let profiles = intel["profiles"] as? [String: Any] ?? [:]
            let profile = profiles[intel["default_profile"] as? String ?? ""] as? [String: Any]
            form.modelId = profile?["model_id"] as? String ?? form.modelId
            form.lightModelId = (profiles["light"] as? [String: Any])?["model_id"] as? String ?? form.lightModelId
            form.deepModelId = (profiles["deep"] as? [String: Any])?["model_id"] as? String ?? form.deepModelId
            form.mode = intel["mode"] as? String ?? form.mode
        }
        if let intel = r["intelligence"] as? [String: Any], let profiles = intel["profiles"] as? [[String: Any]] {
            for p in profiles {
                if let name = p["profile"] as? String { form.profileStatus[name] = p["validated"] as? Bool ?? false }
            }
        }
        settings = form
    }

    public func registerKey(_ key: String) async {
        await attempt {
            try await api.registerKey(key)
            notice = "Chave guardada no Keychain."
        }
    }

    /// Always saves against the revision the form was loaded from; a conflict reloads the saved values.
    public func saveSettings() async {
        guard !isSavingSettings else { return }
        isSavingSettings = true
        defer { isSavingSettings = false }
        let form = settings
        let doc = AtlasAPI.settingsDocument(monthlyMinor: form.monthlyMinor, perTaskMinor: form.perTaskMinor,
                                            modelId: form.modelId, currency: form.currency,
                                            acceptReferencePrices: form.acceptReferencePrices, mode: form.mode,
                                            lightModelId: form.lightModelId, deepModelId: form.deepModelId)
        do {
            let revision = try await api.saveSettings(doc, expectedRevision: form.revision)
            settings.revision = revision
            notice = "Configurações salvas (revisão \(revision))."
            lastError = nil
        } catch {
            lastError = Self.friendly(error)
            if (error as? AtlasAPIError)?.code == "VERSION_CONFLICT" { try? await loadSettings() }
        }
        await refresh()
    }

    public func testIntelligence(maxCents: Int, modelId: String? = nil) async {
        guard !isChecking else { return }  // repeated clicks never start a second paid check
        isChecking = true
        defer { isChecking = false }
        await attempt {
            let report = try await api.testIntelligence(modelId: modelId ?? settings.modelId, maxCents: maxCents)
            if report["passed"] as? Bool != true {
                throw AtlasAPIError(code: "CHECK_FAILED", message: "\(report["errors"] ?? "sem detalhes")")
            }
            let cost = report["cost_minor"] as? Int ?? 0
            notice = "Inteligência validada. Custo do teste: \(MoneyText.format(minor: cost, currency: report["currency"] as? String ?? settings.currency))."
        }
        try? await loadSettings()  // refresh which profiles are validated
        await refresh()
    }

    /// Another Atlas window already runs the services (A3-28): this window only connects to them.
    public func noteExternalServices() {
        notice = "Outra janela do Atlas já gerencia os serviços; esta janela está conectada a ela."
    }

    /// A3-31: say how the services ended, including what had to be forced after the deadline.
    public func noteShutdown(forced: [String]) {
        notice = forced.isEmpty
            ? "Serviços encerrados."
            : "Serviços encerrados; \(forced.joined(separator: ", ")) não respondeu a tempo e foi finalizado. "
                + "Ações em andamento serão conferidas ao reiniciar."
    }

    public func restart() async {
        guard let restartServices else { return }
        await attempt {
            connection = .reconnecting(attempt: 1)
            try await restartServices()
        }
        await refresh()
    }
}
