import Foundation

/// Fixed vocabulary: provider messages, credentials and arbitrary server strings are never exported.
public enum AIConnectionReason: String, CaseIterable, Sendable {
    case ready = "READY", keychain = "KEYCHAIN_UNAVAILABLE", missingKey = "CREDENTIAL_MISSING"
    case settings = "SETTINGS_MISSING", budget = "BUDGET_MISSING", provider = "PROVIDER_UNSUPPORTED"
    case price = "MODEL_UNPRICED", consent = "PRICE_CONSENT_REQUIRED", validation = "VALIDATION_REQUIRED"
    case auth = "API_AUTH_REJECTED", access = "API_ACCESS_DENIED", model = "MODEL_NOT_AVAILABLE"
    case quota = "API_QUOTA_EXHAUSTED", rate = "API_RATE_LIMIT", tls = "TLS_ERROR", network = "NETWORK_ERROR"
    case timeout = "API_TIMEOUT", unavailable = "API_UNAVAILABLE", request = "API_REQUEST_INVALID"
    case metadata = "METADATA_INVALID", outputLimit = "OUTPUT_LIMIT_REACHED", output = "OUTPUT_INVALID"
    case usage = "USAGE_MISSING", localBudget = "LOCAL_BUDGET_BLOCKED", policy = "POLICY_REFUSAL"
    case changed = "CONFIG_CHANGED", failed = "CHECK_FAILED"

    public var message: String {
        switch self {
        case .ready: return "Conexão validada para esta chave e este modelo. Você já pode tentar uma conversa."
        case .keychain: return "O cofre do Mac não está disponível. Reinicie os serviços, sem apagar seus dados."
        case .missingKey: return "O Atlas não encontrou uma chave registrada no cofre."
        case .settings: return "A chave está registrada. Falta salvar modelo e orçamento."
        case .budget: return "Defina os limites de gasto antes de autorizar chamadas pagas."
        case .provider: return "Esta versão conecta somente à API da OpenAI."
        case .price: return "O modelo selecionado não possui preço cadastrado nesta versão. Escolha outro modelo."
        case .consent: return "A chave está registrada. Revise o aceite de preços como estimativa e salve a configuração."
        case .validation: return "A chave está registrada. Use Salvar e conectar para autorizar a validação."
        case .auth: return "A OpenAI rejeitou a autenticação (401). Confira a validade da chave no projeto da API."
        case .access: return "A API negou acesso (403). Confira as permissões de Models e Responses do projeto/chave."
        case .model: return "A conta não disponibilizou este modelo. Revise o ID e o acesso do projeto."
        case .quota: return "A API informou saldo, cota ou limite de gastos esgotado. Confira o faturamento do projeto; repetir não resolve."
        case .rate: return "A API limitou a frequência das chamadas. Aguarde antes de tentar novamente."
        case .tls: return "O certificado da conexão não pôde ser verificado. Confira rede, data e certificados; não desative a proteção."
        case .network: return "Não foi possível conectar à API. Confira internet, DNS, proxy e firewall."
        case .timeout: return "A API não respondeu no prazo. O resultado pode estar incerto; confira os custos antes de repetir."
        case .unavailable: return "A API está indisponível ou respondeu incorretamente. Tente novamente mais tarde."
        case .request: return "A API rejeitou o formato do pedido. Há uma incompatibilidade do aplicativo; a chave foi preservada."
        case .metadata: return "A consulta do modelo devolveu dados inválidos. Nenhuma geração foi iniciada."
        case .outputLimit: return "O teste atingiu o limite de saída. Isso não indica chave inválida. O resultado não foi aprovado."
        case .output: return "A API respondeu, mas não no formato esperado pelo Atlas. A chave foi preservada."
        case .usage: return "A API não informou consumo real. Uma estimativa não foi usada como prova de validação."
        case .localBudget: return "O orçamento do Atlas não comporta este teste. Revise o teto do teste e o limite mensal disponível."
        case .policy: return "O provedor recusou a solicitação. O Atlas não tentará contornar a recusa."
        case .changed: return "A chave mudou durante a validação. O teste antigo não autoriza a nova credencial."
        case .failed: return "Não foi possível concluir a validação. A chave salva foi preservada. Salve o diagnóstico."
        }
    }
}

#if canImport(Combine)
import Combine

/// One explicitly authorized workflow. Opening or inspecting the panel never makes a model call.
@MainActor public final class AIConnectionSetupModel: ObservableObject {
    @Published public var form = SettingsForm()
    @Published public var newKey = ""
    @Published public private(set) var credentialRegistered: Bool?
    @Published public private(set) var reason: AIConnectionReason = .failed
    @Published public private(set) var connected = false
    @Published public private(set) var busy = false
    @Published public private(set) var loaded = false
    @Published public private(set) var stage = "Verifique o estado da configuração."
    @Published public private(set) var error: String?
    @Published public private(set) var costText: String?
    private let api: AtlasAPI
    private var saved: [String: Any] = [:]

    public init(api: AtlasAPI) { self.api = api }

    private func fetchSettings() async throws {
        let data = try await api.settings()
        saved = data["settings"] as? [String: Any] ?? [:]
        var next = SettingsForm()
        next.revision = data["revision"] as? Int ?? 0
        next.pricesVerified = data["prices_verified"] as? Bool ?? false
        next.priceTable = data["price_table"] as? String ?? ""
        let budget = saved["budget"] as? [String: Any] ?? [:]
        next.monthlyMinor = budget["monthly_limit_minor"] as? Int ?? next.monthlyMinor
        next.perTaskMinor = budget["per_task_limit_minor"] as? Int ?? next.perTaskMinor
        next.currency = budget["currency"] as? String ?? next.currency
        next.acceptReferencePrices = budget["accept_reference_prices"] as? Bool ?? false
        let intel = saved["intelligence"] as? [String: Any] ?? [:]
        let profiles = intel["profiles"] as? [String: [String: Any]] ?? [:]
        let selected = intel["default_profile"] as? String ?? "general"
        next.modelId = profiles[selected]?["model_id"] as? String ?? next.modelId
        next.lightModelId = profiles["light"]?["model_id"] as? String ?? next.lightModelId
        next.deepModelId = profiles["deep"]?["model_id"] as? String ?? next.deepModelId
        next.mode = intel["mode"] as? String ?? next.mode
        form = next
        let status = data["intelligence"] as? [String: Any] ?? [:]
        let raw = status["reason"] as? String ?? ""
        let parsed = AIConnectionReason(rawValue: String(raw.prefix(80).split(separator: ":", maxSplits: 1).first ?? ""))
        reason = parsed ?? .failed
        credentialRegistered = parsed == nil || parsed == .keychain ? nil : parsed != .missingKey
        connected = status["configured"] as? Bool == true && reason == .ready
        loaded = true
    }

    public func load() async {
        guard !busy else { return }
        busy = true
        defer { busy = false }
        error = nil
        do { try await fetchSettings(); stage = reason.message }
        catch { connected = false; loaded = false; error = "Não foi possível ler a configuração. Use Verificar novamente." }
    }

    /// Called only after a visible confirmation stating the owner's chosen maximum cost.
    public func connect(maxCents: Int) async {
        guard !busy, loaded else { return }
        guard maxCents > 0 && maxCents <= 50 else { error = "Defina um teto de teste entre 1 e 50 centavos."; return }
        guard form.pricesVerified || form.acceptReferencePrices else {
            reason = .consent; error = reason.message; return
        }
        let pasted = newKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pasted.isEmpty || credentialRegistered == true else {
            error = "Nenhuma chave salva foi confirmada. Registre a chave pelo campo seguro."; return
        }
        busy = true; error = nil; costText = nil; connected = false
        defer { busy = false }
        let edited = form
        do {
            if !pasted.isEmpty {
                stage = "Guardando a chave no cofre do Mac…"
                try await api.registerKey(pasted)
                newKey = ""; credentialRegistered = true
            }
            stage = "Salvando modelo e limites…"
            let doc = AtlasAPI.settingsDocument(monthlyMinor: edited.monthlyMinor, perTaskMinor: edited.perTaskMinor,
                modelId: edited.modelId, currency: edited.currency, acceptReferencePrices: edited.acceptReferencePrices,
                mode: edited.mode, lightModelId: edited.lightModelId, deepModelId: edited.deepModelId)
            let merged = ConfigurationMerge.intelligence(original: saved, edited: doc)
            let revision = try await api.saveSettings(merged, expectedRevision: edited.revision)
            saved = merged; form.revision = revision
            stage = "Validando a API com uma resposta curta. Não feche esta janela…"
            let report = try await api.testIntelligence(modelId: edited.modelId, maxCents: maxCents)
            reason = AIConnectionReason(rawValue: report["reason_code"] as? String ?? "") ?? .failed
            if report["passed"] as? Bool == true {
                // Re-read authoritative state: a new key/configuration may have replaced this check.
                try await fetchSettings()
                if connected {
                    costText = "Custo estimado registrado: " + MoneyText.format(minor: report["cost_minor"] as? Int ?? 0,
                        currency: report["currency"] as? String ?? edited.currency)
                    stage = reason.message
                } else { error = "A configuração mudou. A conexão ativa ainda não foi validada." }
            } else {
                error = reason.message; stage = "Validação não concluída. Sua chave foi preservada."
            }
        } catch {
            let failure = error as? AtlasAPIError
            if failure?.code == "VERSION_CONFLICT" {
                self.error = "A configuração mudou em outra janela. Recarregue, revise os valores e tente novamente."
            } else {
                self.error = "Não foi possível confirmar esta operação. Não repetimos a chamada automaticamente; verifique o estado antes de tentar de novo."
            }
            stage = "Use Verificar novamente para conferir o que foi salvo."
        }
    }
}
#endif
