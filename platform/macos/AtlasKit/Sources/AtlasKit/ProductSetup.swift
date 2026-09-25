import Combine
import Foundation

public struct IdentityForm: Equatable {
    public var name = "Atlas"
    public var ownerName = ""
    public var locale = "pt-BR"
    public var timezone = "America/Sao_Paulo"
    public var revision = 1
    public init() {}
}

/// An edit only replaces the fields actually shown in the intelligence form. Privacy, research,
/// security, additional profiles and future supported settings survive unrelated budget edits.
public enum ConfigurationMerge {
    public static func intelligence(original: [String: Any], edited: [String: Any]) -> [String: Any] {
        guard !original.isEmpty else { return edited }
        var out = original
        var budget = out["budget"] as? [String: Any] ?? [:]
        let changedBudget = edited["budget"] as? [String: Any] ?? [:]
        for key in ["currency", "monthly_limit_minor", "per_task_limit_minor", "accept_reference_prices"] {
            if let value = changedBudget[key] { budget[key] = value }
        }
        out["budget"] = budget
        var intelligence = out["intelligence"] as? [String: Any] ?? [:]
        let changed = edited["intelligence"] as? [String: Any] ?? [:]
        intelligence["mode"] = changed["mode"]
        var profiles = intelligence["profiles"] as? [String: Any] ?? [:]
        let defaultProfile = intelligence["default_profile"] as? String ?? "general"
        for (key, value) in changed["profiles"] as? [String: Any] ?? [:] {
            let target = key == "general" ? defaultProfile : key
            var prior = profiles[target] as? [String: Any] ?? ["provider": "openai"]
            if let id = (value as? [String: Any])?["model_id"] { prior["model_id"] = id }
            profiles[target] = prior
        }
        intelligence["profiles"] = profiles
        out["intelligence"] = intelligence
        return out
    }

    public static func privacy(original: [String: Any], conversation: Bool, tasks: Bool,
                               webEnabled: Bool) -> [String: Any] {
        var out = original
        var privacy = out["privacy"] as? [String: Any] ?? [:]
        var consents = (privacy["sensitive_consents"] as? [[String: Any]] ?? [])
            .filter { $0["provider"] as? String != "openai" }
        let purposes = (conversation ? ["conversation"] : []) + (tasks ? ["task"] : [])
        if !purposes.isEmpty { consents.append(["provider": "openai", "purposes": purposes]) }
        privacy["sensitive_consents"] = consents
        out["privacy"] = privacy
        var research = out["research"] as? [String: Any] ?? [:]
        research["web_enabled"] = webEnabled
        out["research"] = research
        return out
    }
}

public extension AtlasAPI {
    func setupStatus() async throws -> [String: Any] { try await read("setup.status") }
    func updateIdentity(_ form: IdentityForm) async throws -> [String: Any] {
        try await write("identity.update", ["expected_profile_version": form.revision,
            "name": form.name, "owner_name": form.ownerName, "locale": form.locale, "timezone": form.timezone])
    }
    func completeSetup(profile: Int, settings: Int, limited: Bool) async throws -> [String: Any] {
        try await write("setup.complete", ["expected_profile_version": profile,
            "expected_settings_revision": settings, "allow_limited_mode": limited])
    }
}

/// The wizard never invents a successful model test and does not perform billable calls.
@MainActor
public final class ProductSetupModel: ObservableObject {
    @Published public var identity = IdentityForm()
    @Published public var sensitiveConversation = false
    @Published public var sensitiveTasks = false
    @Published public var webEnabled = false
    @Published public private(set) var loaded = false
    @Published public private(set) var completed = false
    @Published public private(set) var intelligenceReady = false
    @Published public private(set) var settingsSaved = false
    @Published public private(set) var busy = false
    @Published public private(set) var error: String?
    @Published public private(set) var notice: String?
    private let api: AtlasAPI
    private var document: [String: Any] = [:]
    private var settingsRevision = 0

    public init(api: AtlasAPI) { self.api = api }

    public func load() async {
        do {
            let status = try await api.setupStatus()
            let data = status["identity"] as? [String: Any] ?? [:]
            var form = IdentityForm()
            form.name = data["name"] as? String ?? form.name
            form.ownerName = data["owner_name"] as? String ?? ""
            form.locale = data["locale"] as? String ?? form.locale
            form.timezone = data["timezone"] as? String ?? form.timezone
            form.revision = data["profile_version"] as? Int ?? 1
            identity = form
            completed = status["completed"] as? Bool ?? false
            intelligenceReady = status["intelligence_ready"] as? Bool ?? false
            settingsSaved = status["settings_saved"] as? Bool ?? false
            let settings = try await api.settings()
            settingsRevision = settings["revision"] as? Int ?? 0
            document = settings["settings"] as? [String: Any] ?? [:]
            let consents = (document["privacy"] as? [String: Any])?["sensitive_consents"] as? [[String: Any]] ?? []
            let purposes = consents.filter { $0["provider"] as? String == "openai" }
                .flatMap { $0["purposes"] as? [String] ?? [] }
            sensitiveConversation = purposes.contains("conversation")
            sensitiveTasks = purposes.contains("task")
            webEnabled = (document["research"] as? [String: Any])?["web_enabled"] as? Bool ?? false
            loaded = true
            error = nil
        } catch { self.error = AtlasViewModel.friendly(error) }
    }

    public func saveIdentity() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let result = try await api.updateIdentity(identity)
            identity.revision = result["profile_version"] as? Int ?? identity.revision
            notice = "Identidade salva. Memórias e tarefas continuam pertencendo ao mesmo funcionário."
            error = nil
        } catch {
            self.error = AtlasViewModel.friendly(error)
            if (error as? AtlasAPIError)?.code == "VERSION_CONFLICT" {
                let message = self.error
                await load()
                self.error = message
            }
        }
    }

    public func savePrivacy() async {
        guard !busy else { return }
        guard !document.isEmpty else {
            error = "Salve primeiro a configuração de inteligência e orçamento. Nenhum consentimento foi alterado."
            return
        }
        busy = true
        defer { busy = false }
        let edited = ConfigurationMerge.privacy(original: document, conversation: sensitiveConversation,
                                                tasks: sensitiveTasks, webEnabled: webEnabled)
        do {
            settingsRevision = try await api.saveSettings(edited, expectedRevision: settingsRevision)
            document = edited
            notice = "Preferências salvas. Revogações valem para novos envios; dados já enviados não são recuperados."
            error = nil
        } catch {
            self.error = AtlasViewModel.friendly(error)
            if (error as? AtlasAPIError)?.code == "VERSION_CONFLICT" {
                let message = self.error
                await load()
                self.error = message
            }
        }
    }

    public func finish(limited: Bool) async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            // Re-read revisions. The finish operation grants no new privacy, spending or account access.
            let state = try await api.setupStatus()
            let data = state["identity"] as? [String: Any] ?? [:]
            let result = try await api.completeSetup(profile: data["profile_version"] as? Int ?? 1,
                                                     settings: data["settings_revision"] as? Int ?? 0, limited: limited)
            completed = result["completed"] as? Bool ?? false
            intelligenceReady = result["intelligence_ready"] as? Bool ?? false
            error = nil
        } catch { self.error = AtlasViewModel.friendly(error) }
    }
}
