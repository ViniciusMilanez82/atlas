import Combine
import Foundation

/// User-facing settings, backed by typed owner-only core operations, not UserDefaults authority.
@MainActor
public final class OwnerSetupModel: ObservableObject {
    @Published public var employeeName = "Atlas"
    @Published public var ownerName = ""
    @Published public var locale = "pt-BR"
    @Published public var timezone = "America/Sao_Paulo"
    @Published public private(set) var step = "welcome"
    @Published public private(set) var profileRevision = 1
    @Published public private(set) var settingsRevision = 0
    @Published public private(set) var loaded = false
    @Published public private(set) var busy = false
    @Published public private(set) var error: String?
    @Published public private(set) var notice: String?
    @Published public var sensitiveConversation = false
    @Published public var sensitiveTasks = false
    @Published public var webEnabled = false
    @Published public var allowedDomains = ""
    @Published public var blockedDomains = ""
    private var otherConsents: [[String: Any]] = []
    private let api: AtlasAPI

    public init(api: AtlasAPI) { self.api = api }

    private func applyProfile(_ p: [String: Any]) {
        employeeName = p["name"] as? String ?? employeeName
        ownerName = p["owner_name"] as? String ?? ownerName
        locale = p["locale"] as? String ?? locale
        timezone = p["timezone"] as? String ?? timezone
        step = p["step"] as? String ?? step
        profileRevision = p["revision"] as? Int ?? profileRevision
    }

    private func applyPrivacy(_ p: [String: Any]) {
        settingsRevision = p["revision"] as? Int ?? 0
        let privacy = p["privacy"] as? [String: Any] ?? [:]
        let consents = privacy["sensitive_consents"] as? [[String: Any]] ?? []
        otherConsents = consents.filter { $0["provider"] as? String != "openai" }
        let purposes = consents.filter { $0["provider"] as? String == "openai" }
            .flatMap { $0["purposes"] as? [String] ?? [] }
        sensitiveConversation = purposes.contains("conversation")
        sensitiveTasks = purposes.contains("task")
        let research = p["research"] as? [String: Any] ?? [:]
        webEnabled = research["web_enabled"] as? Bool ?? false
        allowedDomains = (research["allowed_domains"] as? [String] ?? []).joined(separator: "\n")
        blockedDomains = (research["blocked_domains"] as? [String] ?? []).joined(separator: "\n")
    }

    public func load() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        do {
            applyProfile(try await api.ownerProfile())
            applyPrivacy(try await api.ownerPrivacy())
            loaded = true
            error = nil
        } catch { self.error = AtlasViewModel.friendly(error) }
    }

    @discardableResult
    public func saveProfile(step next: String? = nil) async -> Bool {
        guard !busy, loaded else { return false }
        busy = true
        defer { busy = false }
        do {
            let r = try await api.updateOwnerProfile(name: employeeName, owner: ownerName, locale: locale,
                timezone: timezone, step: next ?? step, expectedRevision: profileRevision)
            applyProfile(r)
            notice = "Identidade e progresso salvos neste computador."
            error = nil
            return true
        } catch {
            self.error = AtlasViewModel.friendly(error)
            if (error as? AtlasAPIError)?.code == "VERSION_CONFLICT", let r = try? await api.ownerProfile() {
                applyProfile(r)
            }
            return false
        }
    }

    @discardableResult
    public func savePrivacy() async -> Bool {
        guard !busy, loaded else { return false }
        busy = true
        defer { busy = false }
        var purposes: [String] = []
        if sensitiveConversation { purposes.append("conversation") }
        if sensitiveTasks { purposes.append("task") }
        var consents = otherConsents
        if !purposes.isEmpty { consents.append(["provider": "openai", "purposes": purposes]) }
        func domains(_ text: String) -> [String] {
            Array(Set(text.components(separatedBy: CharacterSet(charactersIn: ",;\n "))
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }.filter { !$0.isEmpty })).sorted()
        }
        do {
            let r = try await api.updateOwnerPrivacy(
                privacy: ["sensitive_consents": consents],
                research: ["web_enabled": webEnabled, "allowed_domains": domains(allowedDomains),
                           "blocked_domains": domains(blockedDomains)], expectedRevision: settingsRevision)
            applyPrivacy(r)
            notice = "Privacidade salva. Os novos pedidos usam esta decisão; um envio já realizado não pode ser desfeito."
            error = nil
            return true
        } catch {
            self.error = AtlasViewModel.friendly(error)
            if (error as? AtlasAPIError)?.code == "VERSION_CONFLICT", let r = try? await api.ownerPrivacy() {
                applyPrivacy(r)
            }
            return false
        }
    }
}

extension AtlasAPI {
    public func ownerProfile() async throws -> [String: Any] { try await read("setup.get") }
    public func ownerPrivacy() async throws -> [String: Any] { try await read("privacy.get") }

    public func updateOwnerProfile(name: String, owner: String, locale: String, timezone: String,
                                   step: String, expectedRevision: Int) async throws -> [String: Any] {
        let p: [String: Any] = ["request_id": UUID().uuidString.lowercased(), "expected_revision": expectedRevision,
            "name": name, "owner_name": owner, "locale": locale, "timezone": timezone, "step": step]
        return try await transport.call("setup.update", p, retrySafe: true)
    }

    public func updateOwnerPrivacy(privacy: [String: Any], research: [String: Any],
                                   expectedRevision: Int) async throws -> [String: Any] {
        let p: [String: Any] = ["request_id": UUID().uuidString.lowercased(), "expected_revision": expectedRevision,
                              "privacy": privacy, "research": research]
        return try await transport.call("privacy.update", p, retrySafe: true)
    }
}
