import Foundation

/// Typed calls the app makes to atlas-core. Every reply is either `result` or a normalized error;
/// errors are surfaced to the owner with their message, never hidden or replaced by a fake success.
public struct AtlasAPIError: Error, CustomStringConvertible {
    public let code: String
    public let message: String
    public var description: String { "\(code): \(message)" }

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }
}

public final class AtlasAPI {
    private let client: IPCClient
    public let employeeId: String

    public init(session: SessionInfo) throws {
        client = try IPCClient(socketPath: session.socketPath)
        try client.hello(token: session.ownerToken)
        employeeId = session.employeeId
    }

    @discardableResult
    public func call(_ method: String, _ params: [String: Any] = [:]) throws -> [String: Any] {
        let reply = try client.call(method, params: params)
        if let error = reply["error"] as? [String: Any] {
            let data = error["data"] as? [String: Any]
            throw AtlasAPIError(code: data?["atlas_code"] as? String ?? "ERROR",
                                message: error["message"] as? String ?? "unknown error")
        }
        return reply["result"] as? [String: Any] ?? [:]
    }

    public func health() throws -> [String: Any] { try call("system.health") }
    public func identity() throws -> [String: Any] { try call("identity.get") }

    public func tasks() throws -> [[String: Any]] {
        try call("tasks.list", ["employee_id": employeeId, "limit": 100])["tasks"] as? [[String: Any]] ?? []
    }

    public func delegate(objective: String) throws -> [String: Any] {
        try call("tasks.create", ["employee_id": employeeId, "objective": objective, "artifact_ids": [String](),
                                  "constraints": ["external_writes": false, "purchases": false]])
    }

    public func send(conversationId: String, text: String) throws -> [String: Any] {
        try call("conversations.send", ["employee_id": employeeId, "conversation_id": conversationId,
                                        "client_message_id": UUID().uuidString.lowercased(), "text": text])
    }

    public func control(_ method: String, taskId: String, version: Int) throws {
        try call(method, ["task_id": taskId, "expected_version": version])
    }

    public func artifacts(taskId: String) throws -> [[String: Any]] {
        try call("artifacts.list", ["task_id": taskId])["artifacts"] as? [[String: Any]] ?? []
    }

    public func approvals() throws -> [[String: Any]] {
        try call("approvals.list")["approvals"] as? [[String: Any]] ?? []
    }

    public func decide(approval: [String: Any], approve: Bool) throws {
        try call("approvals.decide", ["approval_id": approval["approval_id"] ?? "", "decision": approve ? "APPROVE" : "REJECT",
                                      "params_hash": approval["params_hash"] ?? "", "nonce": approval["nonce"] ?? ""])
    }

    public func registerKey(_ key: String) throws {
        try call("credentials.register", ["provider": "openai", "secret_b64": Data(key.utf8).base64EncodedString()])
    }

    /// Saves the reference configuration with the owner's ceilings (minor units, USD).
    public func saveBudget(monthlyCents: Int, perTaskCents: Int, modelId: String, revision: Int) throws {
        let settings: [String: Any] = [
            "schema_version": "1.0",
            "intelligence": [
                "mode": "manual", "default_profile": "general",
                "profiles": ["general": ["provider": "openai", "model_id": modelId]],
                "allow_cross_provider_fallback": false, "max_parallel_research_workers": 2,
                "max_external_effect_workers": 1,
            ],
            "budget": [
                "currency": "USD", "monthly_limit_minor": monthlyCents, "per_task_limit_minor": perTaskCents,
                "require_owner_setup_before_paid_calls": true, "warning_percentages": [70, 90],
            ],
            "security": [
                "host_shell_enabled": false, "unreviewed_code_network_enabled": false,
                "purchases_require_scoped_approval": true, "raw_secrets_in_model_context": false,
            ],
        ]
        try call("settings.update", ["expected_revision": revision, "settings": settings])
    }

    public func testIntelligence(modelId: String, maxCents: Int) throws -> [String: Any] {
        try call("intelligence.check", ["model_id": modelId, "max_cost_minor": maxCents])["report"] as? [String: Any] ?? [:]
    }
}
