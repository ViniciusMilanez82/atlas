import AppKit
import AtlasKit
import SwiftUI

// Atlas development app (Alpha). Compiled on the macOS CI runner; interactive behaviour must still be
// validated on a real Mac (D-01). Closing the window keeps the services; "Encerrar serviços" stops them.

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Quitting the app stops the services (single database writer). Keeping Atlas working after quit
    /// needs the login item (SMAppService), which must be validated on a real Mac (D-01).
    static var onTerminate: (() -> Void)?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        AppDelegate.onTerminate?()
    }
}

@main
struct AtlasApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Atlas") {
            ContentView().environmentObject(model).frame(minWidth: 880, minHeight: 560)
                .onAppear {
                    AppDelegate.onTerminate = { [weak model] in model?.shutdownServices() }
                    model.startIfNeeded()
                }
        }
        .commands {
            CommandMenu("Funcionário") {
                Button("Pare tudo") { model.stopAll() }.keyboardShortcut(".", modifiers: [.command])
                Button("Encerrar serviços") { model.shutdownServices() }
            }
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var status = "Iniciando…"
    @Published var name = "Atlas"
    @Published var intelligence = "—"
    @Published var tasks: [[String: Any]] = []
    @Published var approvals: [[String: Any]] = []
    @Published var healthText = ""
    @Published var lastError: String?
    @Published var servicesRunning = false
    private var supervisor: Supervisor?
    private var api: AtlasAPI?
    private let conversationId = UUID().uuidString.lowercased()
    private var timer: Timer?

    func startIfNeeded() {
        guard supervisor == nil else { return }
        do {
            let sup = Supervisor(config: try Self.bundledConfig())
            try sup.start()
            supervisor = sup
            api = try AtlasAPI(session: try sup.session())
            servicesRunning = true
            status = "Serviços ativos"
            refresh()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.refresh() }
            }
        } catch {
            status = "Não foi possível iniciar: \(error)"
        }
    }

    /// Layout of the development bundle built by packaging/macos/build_app.sh.
    static func bundledConfig() throws -> SupervisorConfig {
        let res = Bundle.main.resourceURL ?? URL(fileURLWithPath: ".")
        let dirs = SupervisorConfig.defaultDirectories()
        return SupervisorConfig(
            python: res.appendingPathComponent("python/bin/python3"),
            coreRoot: res.appendingPathComponent("core-src"),
            extraPythonPath: [res.appendingPathComponent("site-packages")],
            keychainAgent: Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/atlas-keychain-agent"),
            dataDir: dirs.data, ipcDir: dirs.ipc)
    }

    func run(_ action: () throws -> Void) {
        do {
            try action()
            lastError = nil
        } catch {
            lastError = "\(error)"
        }
        refresh()
    }

    func refresh() {
        guard let api else { return }
        do {
            let h = try api.health()
            let comps = h["components"] as? [String: Any] ?? [:]
            intelligence = (comps["intelligence"] as? String == "ready") ? "Pronta"
                : "Não configurada: \(h["intelligence_reason"] as? String ?? "")"
            healthText = (try? String(data: JSONSerialization.data(withJSONObject: h, options: [.prettyPrinted, .sortedKeys]),
                                      encoding: .utf8)) ?? ""
            name = (try api.identity()["name"] as? String) ?? name
            tasks = try api.tasks()
            approvals = try api.approvals()
        } catch {
            lastError = "\(error)"
        }
    }

    func delegate(_ text: String) {
        run {
            guard let api else { return }
            let reply = try api.send(conversationId: conversationId, text: text)
            if reply["control"] as? String == "stopped" { return }  // "pare" already changed state
            _ = try api.delegate(objective: text)
        }
    }

    func stopAll() { run { _ = try api?.send(conversationId: conversationId, text: "pare tudo") } }

    func control(_ method: String, _ task: [String: Any]) {
        run { try api?.control(method, taskId: task["task_id"] as? String ?? "", version: task["version"] as? Int ?? 0) }
    }

    func decide(_ approval: [String: Any], approve: Bool) { run { try api?.decide(approval: approval, approve: approve) } }
    func registerKey(_ key: String) { run { try api?.registerKey(key) } }

    func saveBudget(monthly: Int, perTask: Int, model: String) {
        run { try api?.saveBudget(monthlyCents: monthly, perTaskCents: perTask, modelId: model, revision: try currentRevision()) }
    }

    private func currentRevision() throws -> Int {
        // The core owns the revision; settings.update rejects stale revisions explicitly.
        (try api?.identity()["settings_revision"] as? Int) ?? 0
    }

    func testIntelligence(model: String, maxCents: Int) {
        run {
            let report = try api?.testIntelligence(modelId: model, maxCents: maxCents) ?? [:]
            if report["passed"] as? Bool != true {
                throw AtlasAPIError(code: "CHECK_FAILED", message: "\(report["errors"] ?? "sem detalhes")")
            }
        }
    }

    func artifacts(_ task: [String: Any]) -> [[String: Any]] {
        (try? api?.artifacts(taskId: task["task_id"] as? String ?? "")) ?? []
    }

    func shutdownServices() {
        timer?.invalidate()
        supervisor?.stop()
        supervisor = nil
        api = nil
        servicesRunning = false
        status = "Serviços encerrados"
    }
}

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(model.name).font(.title2).bold()
                Text(model.status).foregroundStyle(.secondary)
                Spacer()
                Text("Inteligência: \(model.intelligence)").font(.caption).foregroundStyle(.secondary)
            }.padding()
            if let err = model.lastError {
                Text(err).foregroundStyle(.red).font(.caption).padding(.horizontal)
            }
            TabView {
                ConversationView().tabItem { Text("Conversa") }
                WorkView().tabItem { Text("Trabalho") }
                ApprovalsView().tabItem { Text("Aprovações") }
                SettingsView().tabItem { Text("Configurações") }
                ScrollView { Text(model.healthText).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
                    .tabItem { Text("Diagnóstico") }
            }.padding()
        }
    }
}

struct ConversationView: View {
    @EnvironmentObject var model: AppModel
    @State private var text = ""

    var body: some View {
        VStack(alignment: .leading) {
            Text("Delegue um objetivo. \"Pare\" interrompe o trabalho em andamento.").foregroundStyle(.secondary)
            HStack {
                TextField("O que o Atlas deve fazer?", text: $text).textFieldStyle(.roundedBorder)
                    .onSubmit(send)
                Button("Enviar", action: send).disabled(text.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            Spacer()
        }
    }

    private func send() {
        model.delegate(text)
        text = ""
    }
}

struct WorkView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        List(Array(model.tasks.enumerated()), id: \.offset) { _, task in
            VStack(alignment: .leading, spacing: 4) {
                Text(task["objective"] as? String ?? "").font(.headline)
                Text("Estado: \(task["state"] as? String ?? "")").font(.caption)
                HStack {
                    Button("Pausar") { model.control("tasks.pause", task) }
                    Button("Retomar") { model.control("tasks.resume", task) }
                    Button("Cancelar", role: .destructive) { model.control("tasks.cancel", task) }
                }.buttonStyle(.borderless)
                ForEach(Array(model.artifacts(task).enumerated()), id: \.offset) { _, a in
                    Text("\(a["relation"] as? String ?? ""): \(a["name"] as? String ?? "") v\(a["version"] as? Int ?? 0)")
                        .font(.caption)
                }
            }
        }
    }
}

struct ApprovalsView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        List(Array(model.approvals.enumerated()), id: \.offset) { _, ap in
            VStack(alignment: .leading, spacing: 4) {
                Text("\(ap["action_type"] as? String ?? "") → \(ap["destination"] as? String ?? "")").font(.headline)
                Text("Risco \(ap["risk_class"] as? String ?? "") · expira \(ap["expires_at"] as? String ?? "")").font(.caption)
                if let cost = ap["max_cost"] as? [String: Any] {
                    Text("Custo máximo: \(cost["amount_minor"] ?? "") \(cost["currency"] ?? "")").font(.caption)
                }
                HStack {
                    Button("Aprovar") { model.decide(ap, approve: true) }
                    Button("Rejeitar", role: .destructive) { model.decide(ap, approve: false) }
                }
            }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var key = ""
    @State private var monthly = 500
    @State private var perTask = 100
    @State private var modelId = "gpt-6-sol"
    @State private var checkCents = 5

    var body: some View {
        Form {
            Section("Chave da API (guardada no Keychain)") {
                SecureField("sk-…", text: $key)
                Button("Guardar no Keychain") {
                    model.registerKey(key)
                    key = ""
                }.disabled(key.isEmpty)
                Text("O uso da API é cobrado separadamente da assinatura do ChatGPT.").font(.caption)
            }
            Section("Orçamento (centavos de USD)") {
                Stepper("Teto mensal: \(monthly)", value: $monthly, in: 1...100_000, step: 50)
                Stepper("Teto por tarefa: \(perTask)", value: $perTask, in: 1...10_000, step: 10)
                TextField("Modelo (ID exato da API)", text: $modelId)
                Button("Salvar configuração") { model.saveBudget(monthly: monthly, perTask: perTask, model: modelId) }
            }
            Section("Testar inteligência (uma chamada paga pequena)") {
                Stepper("Teto do teste: \(checkCents) centavos", value: $checkCents, in: 1...50)
                Button("Testar agora") { model.testIntelligence(model: modelId, maxCents: checkCents) }
            }
            Section("Serviços") {
                Text(model.servicesRunning ? "Ativos (fechar a janela não os encerra)" : "Encerrados")
                Button("Encerrar serviços", role: .destructive) { model.shutdownServices() }
            }
        }
    }
}
