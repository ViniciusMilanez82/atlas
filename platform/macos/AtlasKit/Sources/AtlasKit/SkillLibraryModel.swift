import Foundation
import Combine

public struct TableSkillSummary: Identifiable {
    public let id: String
    public let key: String
    public let version: Int
    public let description: String
    public let state: String
    public let revision: Int
    public let contentHash: String
    public let testId: String?
    public let canActivate: Bool
    public let canRollback: Bool
    public let testsPassed: Bool
    public let testsCurrent: Bool
    public let classification: String

    public init?(_ value: [String: Any]) {
        guard let id = value["id"] as? String, let key = value["skill_key"] as? String,
              let version = value["version"] as? Int, let revision = value["revision"] as? Int,
              let hash = value["content_hash"] as? String, let state = value["state"] as? String else { return nil }
        self.id = id; self.key = key; self.version = version; self.revision = revision; self.contentHash = hash
        self.state = state; self.description = value["description"] as? String ?? ""
        self.testId = value["test_id"] as? String
        self.canActivate = value["can_activate"] as? Bool ?? false
        self.canRollback = value["can_rollback"] as? Bool ?? false
        self.testsPassed = value["tests_passed"] as? Bool ?? false
        self.testsCurrent = value["tests_current"] as? Bool ?? false
        self.classification = value["classification"] as? String ?? "SENSITIVE"
    }
    public var stateText: String {
        switch state {
        case "DRAFT": return "Rascunho — ainda não aprovado nos testes"
        case "TESTED": return "Testado — aguardando sua revisão"
        case "ACTIVE": return testsCurrent ? "Ativo" : "Precisa testar novamente após atualização"
        case "SUPERSEDED": return "Versão anterior preservada"
        case "QUARANTINED": return "Bloqueado para revisão"
        case "REVOKED": return "Revogado"
        default: return "Estado desconhecido — uso bloqueado"
        }
    }
}

@MainActor public final class SkillLibraryModel: ObservableObject {
    @Published public private(set) var skills: [TableSkillSummary] = []
    @Published public private(set) var selected: TableSkillSummary?
    @Published public private(set) var detail: [String: Any] = [:]
    @Published public private(set) var busy = false
    @Published public private(set) var error: String?
    @Published public private(set) var notice: String?
    private let api: AtlasAPI
    private var selectionEpoch = 0

    public init(api: AtlasAPI) { self.api = api }

    public func load() async {
        do {
            let result = try await api.read("skills.list")
            let values = result["skills"] as? [[String: Any]] ?? []
            let decoded = values.compactMap(TableSkillSummary.init)
            guard decoded.count == values.count else {
                throw AtlasAPIError(code: "INVALID_REPLY", message: "Lista de habilidades inválida.")
            }
            skills = decoded
        } catch { self.error = error.localizedDescription }
    }

    public func select(_ version: TableSkillSummary) async {
        guard !busy else { return }
        selectionEpoch += 1
        let epoch = selectionEpoch
        selected = nil; detail = [:]; error = nil; notice = nil
        do {
            let response = try await api.read("skills.get", ["version_id": version.id])
            guard epoch == selectionEpoch else { return }
            guard let decoded = TableSkillSummary(response) else {
                throw AtlasAPIError(code: "INVALID_REPLY", message: "Detalhes da habilidade inválidos.")
            }
            selected = decoded; detail = response
        } catch { if epoch == selectionEpoch { self.error = error.localizedDescription } }
    }

    public func testSelected() async { await perform("test") }
    public func decide(_ decision: String, reviewed: TableSkillSummary? = nil) async { await perform(decision, reviewed: reviewed) }

    private func perform(_ operation: String, reviewed: TableSkillSummary? = nil) async {
        guard !busy, let version = reviewed ?? selected else { return }
        guard (operation == "test" && ["DRAFT", "TESTED"].contains(version.state))
                || (operation == "activate" && version.canActivate)
                || (operation == "rollback" && version.canRollback)
                || (["quarantine", "revoke"].contains(operation) && version.state != "REVOKED") else {
            error = "Essa ação não está disponível para a versão exibida."; return
        }
        busy = true; error = nil; notice = nil; selectionEpoch += 1
        defer { busy = false }
        var params: [String: Any] = ["version_id": version.id, "expected_revision": version.revision,
                                    "request_id": UUID().uuidString.lowercased()]
        let method = operation == "test" ? "skills.test" : "skills.decide"
        if operation != "test" {
            params["decision"] = operation
            params["content_hash"] = version.contentHash
            params["test_id"] = version.testId.map { $0 as Any } ?? NSNull()
        }
        do {
            // The exact request UUID, revision/hash/test ID are retained across transport retries.
            // Replaying a decision reads the current state; it cannot reactivate a revoked version.
            let response = try await api.transport.call(method, params, retrySafe: true)
            guard let decoded = TableSkillSummary(response) else {
                throw AtlasAPIError(code: "INVALID_REPLY", message: "Resposta da habilidade inválida.")
            }
            selected = decoded; detail = response
            notice = operation == "test" ? (decoded.testsPassed ? "Exemplos aprovados. Confira se representam o que você quer antes de ativar." : "Alguns exemplos falharam. Peça ao Atlas uma versão corrigida.") : "Decisão registrada. Nenhum acesso a internet, senhas ou arquivos pessoais foi concedido."
        } catch {
            self.error = error.localizedDescription
            // A stale confirmation is discarded, never automatically applied to a newer version.
            selected = nil; detail = [:]
        }
        await load()
    }

    public var examples: [[String: Any]] {
        (detail["test_report"] as? [String: Any])?["cases"] as? [[String: Any]] ?? []
    }
    public var columns: [[String: Any]] {
        (detail["definition"] as? [String: Any])?["columns"] as? [[String: Any]] ?? []
    }
}
