import Foundation

/// N22/N24: read-only prerequisites for a manual Alpha test. This is NOT a V1 acceptance report.
/// Only fixed status codes and our own bundle's metadata can enter the exported JSON.
public enum MacTestCheckState: String, Codable, Sendable {
    case passed, blocked, notChecked, limitation
}

public struct MacTestCheck: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let state: MacTestCheckState
    public let detail: String
}

public struct MacTestEnvironment: Codable, Equatable, Sendable {
    public enum Architecture: String, Codable, Sendable { case arm64, intel, unsupported }
    public enum InstallLocation: String, Codable, Sendable { case applications, translocated, other }
    public let osMajor: Int
    public let osMinor: Int
    public let osPatch: Int
    public let architecture: Architecture
    public let location: InstallLocation
    public let build: String
    public let pythonPresent: Bool
    public let corePresent: Bool
    public let keychainHelperPresent: Bool

    public init(osMajor: Int, osMinor: Int = 0, osPatch: Int = 0, architecture: Architecture,
                location: InstallLocation, build: String, pythonPresent: Bool,
                corePresent: Bool, keychainHelperPresent: Bool) {
        self.osMajor = max(0, min(999, osMajor))
        self.osMinor = max(0, min(999, osMinor))
        self.osPatch = max(0, min(999, osPatch))
        self.architecture = architecture
        self.location = location
        // The development build is a git hash or git-describe output. Never echo an arbitrary plist
        // value (which may contain paths or user data) into diagnostics. Do not use a deny-list.
        let pattern = #"^(?:[0-9a-f]{7,40}|v?[0-9]+\.[0-9]+\.[0-9]+(?:[-.][a-z0-9]+){0,8})(?:-dirty)?$"#
        self.build = build.utf8.count <= 80 && build.range(of: pattern, options: .regularExpression) != nil
            ? build : "unavailable"
        self.pythonPresent = pythonPresent
        self.corePresent = corePresent
        self.keychainHelperPresent = keychainHelperPresent
    }

    public static func inspect(bundle: Bundle = .main) -> MacTestEnvironment {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        #if arch(arm64)
        let architecture = Architecture.arm64
        #elseif arch(x86_64)
        let architecture = Architecture.intel
        #else
        let architecture = Architecture.unsupported
        #endif
        let app = bundle.bundleURL.standardizedFileURL
        let path = app.path
        let location: InstallLocation = path.contains("/AppTranslocation/") ? .translocated
            : (path == "/Applications/Atlas.app" ? .applications : .other)
        let manager = FileManager.default
        func present(_ relative: String, executable: Bool) -> Bool {
            let item = app.appendingPathComponent(relative).resolvingSymlinksInPath()
            let base = app.resolvingSymlinksInPath().path + "/"
            guard item.path.hasPrefix(base) else { return false }
            var directory: ObjCBool = false
            guard manager.fileExists(atPath: item.path, isDirectory: &directory), !directory.boolValue else {
                return false
            }
            return !executable || manager.isExecutableFile(atPath: item.path)
        }
        return MacTestEnvironment(
            osMajor: version.majorVersion, osMinor: version.minorVersion, osPatch: version.patchVersion,
            architecture: architecture, location: location,
            build: bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "",
            pythonPresent: present("Contents/Resources/python/bin/python3", executable: true),
            corePresent: present("Contents/Resources/core-src/core/__main__.py", executable: false),
            keychainHelperPresent: present("Contents/MacOS/atlas-keychain-agent", executable: true))
    }
}

public struct MacTestReport: Codable, Sendable {
    public let schemaVersion = 1
    public let scope = "alpha-manual-test-prerequisites"
    public let completeProduct = false
    public let realModelTestedByThisCheck = false
    public let containsConversationContent = false
    public let checkedAt: Date
    public let environment: MacTestEnvironment
    public let checks: [MacTestCheck]

    public var localPrerequisitesPass: Bool {
        ["system", "architecture", "bundle", "ipc", "database", "worker"].allSatisfy { id in
            checks.first { $0.id == id }?.state == .passed
        }
    }
    public var mayAttemptConversation: Bool {
        localPrerequisitesPass && checks.first { $0.id == "intelligence" }?.state == .passed
    }
    public var summary: String {
        if mayAttemptConversation { return "Pré-requisitos atendidos. Falta testar uma conversa real." }
        if localPrerequisitesPass { return "Parte local funcionando. Falta configurar e validar a inteligência." }
        return "Há verificações pendentes ou problemas locais. Confira os itens abaixo."
    }

    public func json() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return try encoder.encode(self)
    }

    /// `health` is an authenticated system.health response. Never retain that dictionary: it may
    /// contain free-form failure messages, identifiers, paths or data belonging to the owner.
    public static func evaluate(environment e: MacTestEnvironment, health: [String: Any]?,
                                attempted: Bool, checkedAt: Date = Date()) -> MacTestReport {
        var checks: [MacTestCheck] = []
        func append(_ id: String, _ title: String, _ state: MacTestCheckState, _ detail: String) {
            checks.append(MacTestCheck(id: id, title: title, state: state, detail: detail))
        }
        append("system", "Versão do macOS", e.osMajor >= 15 ? .passed : .blocked,
               e.osMajor >= 15 ? "macOS compatível com esta Alpha." : "Esta edição exige macOS 15 ou posterior.")
        append("architecture", "Tipo de Mac", e.architecture == .arm64 ? .passed : .blocked,
               e.architecture == .arm64 ? "Aplicativo executado na arquitetura Apple Silicon."
               : "Esta edição exige Apple Silicon; não force a instalação em Mac Intel.")
        let allPresent = e.pythonPresent && e.corePresent && e.keychainHelperPresent
        append("bundle", "Componentes incluídos", allPresent ? .passed : .blocked,
               allPresent ? "Python, núcleo e auxiliar do cofre estão presentes. Isso não verifica assinatura."
               : "Há componentes ausentes. Não instale Python como atalho; confira o pacote do Atlas.")
        let properLocation = e.location == .applications
        append("location", "Local da instalação", properLocation ? .passed : .limitation,
               properLocation ? "Aplicativo aberto pela pasta Aplicativos."
               : "Abra a cópia instalada em Aplicativos para testar o instalador; não use a prévia do download.")
        let ipcState: MacTestCheckState = health != nil ? .passed : (attempted ? .blocked : .notChecked)
        append("ipc", "Conexão com o núcleo", ipcState,
               health != nil ? "O núcleo respondeu à consulta autenticada de saúde."
               : (attempted ? "O núcleo não respondeu. Use Tentar de novo ou confira Saúde; não apague os dados."
                  : "Clique em Verificar este Mac. Nenhuma consulta ao modelo será feita."))
        let components = health?["components"] as? [String: Any] ?? [:]
        for (id, title) in [("database", "Banco local"), ("worker", "Executor de tarefas")] {
            let state: MacTestCheckState = health == nil ? (attempted ? .blocked : .notChecked)
                : (components[id] as? String == "ok" ? .passed : .blocked)
            let detail = state == .passed ? "Componente respondeu com estado saudável."
                : "Estado saudável ainda não comprovado. Não considere tarefas prontas nesta condição."
            append(id, title, state, detail)
        }
        let intelligenceReady = components["intelligence"] as? String == "ready"
        let rawReason = health?["intelligence_reason"] as? String ?? ""
        let code = String(rawReason.prefix(80).split(separator: ":", maxSplits: 1).first ?? "")
        let blockingDetail = (AIConnectionReason(rawValue: code) ?? .failed).message
        append("intelligence", "Configuração da inteligência",
               health == nil ? .notChecked : (intelligenceReady ? .passed : .blocked),
               intelligenceReady ? "O núcleo registra uma configuração validada. Esta verificação não chamou a IA."
               : blockingDetail)
        append("distribution", "Limite desta distribuição", .limitation,
               "Alpha de desenvolvimento, sem notarização. Este diagnóstico não avalia Gatekeeper nem certifica segurança.")
        append("scope", "Funções ainda fora desta entrega", .limitation,
               "Computador virtual integrado, navegador completo, contas próprias e acesso pelo celular não estão entregues aqui.")
        return MacTestReport(checkedAt: checkedAt, environment: e, checks: checks)
    }
}

#if canImport(Combine)
import Combine

/// A dedicated short-deadline transport is injected by AppController. No mutation or paid request.
@MainActor public final class MacTestReadinessModel: ObservableObject {
    @Published public private(set) var report: MacTestReport
    @Published public private(set) var checking = false
    private let api: AtlasAPI
    private let inspect: () -> MacTestEnvironment

    public init(api: AtlasAPI, inspect: @escaping () -> MacTestEnvironment = { .inspect() }) {
        self.api = api
        self.inspect = inspect
        self.report = .evaluate(environment: inspect(), health: nil, attempted: false)
    }

    public func run() async {
        guard !checking else { return }
        checking = true
        // Invalidate the old green result BEFORE waiting for I/O.
        report = .evaluate(environment: inspect(), health: nil, attempted: false)
        defer { checking = false }
        do {
            let health = try await api.health()
            report = .evaluate(environment: inspect(), health: health, attempted: true)
        } catch {
            // Never expose an exception description in an export. It could include a secret or path.
            report = .evaluate(environment: inspect(), health: nil, attempted: true)
        }
    }
}
#endif
