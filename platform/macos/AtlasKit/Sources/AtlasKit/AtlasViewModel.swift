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

    init(_ d: [String: Any]) {
        id = d["message_id"] as? String ?? UUID().uuidString
        role = d["role"] as? String ?? "system"
        kind = d["kind"] as? String ?? "chat"
        content = d["content"] as? String ?? ""
        taskId = d["task_id"] as? String
        artifactId = d["artifact_id"] as? String
        memoryId = d["memory_id"] as? String
        createdAt = d["created_at"] as? String ?? ""
    }

    public var isOwner: Bool { role == "owner" }
}

public struct TaskItem: Identifiable, Equatable {
    public let id: String
    public let objective: String
    public let state: String
    public let version: Int
    public let blockedReason: String?

    init(_ d: [String: Any]) {
        id = d["task_id"] as? String ?? ""
        objective = d["objective"] as? String ?? ""
        state = d["state"] as? String ?? ""
        version = d["version"] as? Int ?? 0
        blockedReason = d["blocked_reason"] as? String
    }

    public var stateText: String {
        [
            "CREATED": "Na fila", "UNDERSTANDING": "Entendendo", "PLANNING": "Planejando", "READY": "Na fila",
            "RUNNING": "Em execução", "WAITING_USER": "Aguardando você", "WAITING_APPROVAL": "Aguardando aprovação",
            "BLOCKED": "Bloqueada", "PAUSED": "Pausada", "RETRYING": "Nova tentativa agendada",
            "VERIFYING": "Verificando", "COMPLETED": "Concluída", "FAILED": "Falhou", "CANCELLED": "Cancelada",
        ][state] ?? state
    }
}

public struct Attachment: Identifiable, Equatable {
    public let id: String  // artifact_id
    public let name: String
    public let sizeBytes: Int
    public let sha256: String
}

public struct SettingsForm: Equatable {
    public var monthlyMinor = 500
    public var perTaskMinor = 100
    public var modelId = "gpt-6-sol"
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
    @Published public var settings = SettingsForm()
    @Published public private(set) var lastError: String?
    @Published public private(set) var notice: String?
    @Published public private(set) var isSending = false
    @Published public private(set) var isSavingSettings = false
    @Published public private(set) var isChecking = false
    @Published public private(set) var isAttaching = false
    @Published public private(set) var eventCursor = 0
    /// Text + client id kept after a failed send, so "Tentar de novo" reuses the SAME id (no duplicate).
    @Published public private(set) var failedDraft: (text: String, clientId: String, delegate: Bool)?

    public let api: AtlasAPI
    public private(set) var conversationId = ""
    public var restartServices: (() async throws -> Void)?
    public var serviceStatus: (() -> String)?
    private var refreshing = false
    private var errorFromRefresh = false

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
            messages = page.messages.map(ChatMessage.init)
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
            if !conversationId.isEmpty {
                merge(try await api.history(conversationId: conversationId).messages.map(ChatMessage.init))
            }
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

    private func merge(_ newer: [ChatMessage]) {
        var known = Set(messages.map(\.id))
        for m in newer where !known.contains(m.id) {
            messages.append(m)
            known.insert(m.id)
        }
    }

    public func loadOlder() async {
        guard hasOlderMessages, let first = messages.first else { return }
        await attempt {
            let page = try await api.history(conversationId: conversationId, before: first.id)
            messages = page.messages.map(ChatMessage.init) + messages
            hasOlderMessages = page.hasMore
        }
    }

    // MARK: conversation

    public func send(_ text: String, delegate: Bool = false) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isSending else { return }
        await deliver(trimmed, clientId: UUID().uuidString.lowercased(), delegate: delegate)
    }

    public func retryFailedSend() async {
        guard let draft = failedDraft, !isSending else { return }
        await deliver(draft.text, clientId: draft.clientId, delegate: draft.delegate)
    }

    private func deliver(_ text: String, clientId: String, delegate: Bool) async {
        isSending = true
        defer { isSending = false }
        let ids = attachments.map(\.id)
        do {
            let out = try await api.send(conversationId: conversationId, text: text, clientMessageId: clientId,
                                         delegate: delegate || !ids.isEmpty, artifactIds: ids)
            failedDraft = nil
            attachments = []
            lastError = nil
            var fresh: [ChatMessage] = []
            if let m = out["message"] as? [String: Any] { fresh.append(ChatMessage(m)) }
            if let r = out["reply"] as? [String: Any] { fresh.append(ChatMessage(r)) }
            merge(fresh)
        } catch {
            failedDraft = (text, clientId, delegate)
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
            if let r = out["reply"] as? [String: Any] { merge([ChatMessage(r)]) }
        }
    }

    public func stopAll() async { await send("pare tudo") }

    public func confirmMemory(_ message: ChatMessage) async {
        guard let id = message.memoryId else { return }
        await attempt {
            try await api.confirmMemory(id)
            notice = "Memória confirmada."
        }
    }

    // MARK: attachments

    public func attach(fileURL: URL) async {
        guard !isAttaching else { return }
        isAttaching = true
        defer { isAttaching = false }
        await attempt {
            let values = try fileURL.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true else {
                throw AtlasAPIError(code: "INVALID_INPUT", message: "escolha um arquivo comum (não pasta nem atalho)")
            }
            guard (values.fileSize ?? 0) <= AtlasAPI.maxAttachmentBytes else {
                throw AtlasAPIError(code: "INVALID_INPUT", message: "o arquivo passa de 50 MB")
            }
            let data = try await Task.detached(priority: .userInitiated) { try Data(contentsOf: fileURL) }.value
            let r = try await api.importFile(data: data, name: fileURL.lastPathComponent)
            attachments.append(Attachment(id: r["artifact_id"] as? String ?? "", name: r["name"] as? String ?? "",
                                          sizeBytes: r["size_bytes"] as? Int ?? data.count,
                                          sha256: r["sha256"] as? String ?? ""))
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

    public func control(_ method: String, _ task: TaskItem) async {
        await attempt { try await api.control(method, taskId: task.id, version: task.version) }
        await refresh()
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
                                            acceptReferencePrices: form.acceptReferencePrices)
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

    public func testIntelligence(maxCents: Int) async {
        guard !isChecking else { return }  // repeated clicks never start a second paid check
        isChecking = true
        defer { isChecking = false }
        await attempt {
            let report = try await api.testIntelligence(modelId: settings.modelId, maxCents: maxCents)
            if report["passed"] as? Bool != true {
                throw AtlasAPIError(code: "CHECK_FAILED", message: "\(report["errors"] ?? "sem detalhes")")
            }
            let cost = report["cost_minor"] as? Int ?? 0
            notice = "Inteligência validada. Custo do teste: \(MoneyText.format(minor: cost, currency: report["currency"] as? String ?? settings.currency))."
        }
        await refresh()
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
