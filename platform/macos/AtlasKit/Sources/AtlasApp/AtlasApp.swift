import AppKit
import AtlasKit
import SwiftUI
import UniformTypeIdentifiers

// Atlas development app (Alpha 2). Compiled on the macOS CI runner; interactive behaviour must still be
// validated on a real Mac (D-01). All core I/O goes through AtlasConnection (async, off the main actor).

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Quitting the app stops the services (single database writer). Keeping Atlas working after quit
    /// needs the login item (SMAppService), which must be validated on a real Mac (D-01).
    static var onTerminate: (() -> Void)?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        AppDelegate.onTerminate?()
    }
}

/// Owns the Supervisor and the connection; the view model holds all UI state.
@MainActor
final class AppController: ObservableObject {
    @Published var bootError: String?
    @Published var starting = true
    let supervisor: Supervisor?
    let model: AtlasViewModel
    private var timer: Timer?

    init() {
        var sup: Supervisor?
        do { sup = Supervisor(config: try AppController.bundledConfig()) } catch { sup = nil }
        supervisor = sup
        let connection = AtlasConnection(timeout: 30) {
            guard let sup else { throw SupervisorError.notRunning }
            return try sup.session()
        }
        model = AtlasViewModel(api: AtlasAPI(transport: connection))
        connection.onStateChange = { [weak model] state in
            Task { @MainActor in model?.setConnectionState(state) }
        }
        model.restartServices = { [sup] in
            guard let sup else { throw SupervisorError.notRunning }
            try await Task.detached { try sup.restart() }.value
            connection.reset()
        }
        model.serviceStatus = { [sup] in
            guard let sup else { return "Supervisor indisponível" }
            return "\(sup.isRunning ? "Ativo" : "Parado") · \(sup.lastEvent) · reinícios automáticos: \(sup.restartCount)"
        }
    }

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

    func start() async {
        guard let supervisor else {
            bootError = "Configuração do pacote inválida."
            starting = false
            return
        }
        starting = true
        do {
            if !supervisor.isRunning {
                try await Task.detached(priority: .userInitiated) { try supervisor.start() }.value
            }
            bootError = nil
            await model.start()
            timer?.invalidate()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
                Task { @MainActor in await self?.model.refresh() }
            }
        } catch {
            bootError = "Não foi possível iniciar os serviços: \(AtlasViewModel.friendly(error))"
        }
        starting = false
    }

    func shutdown() {
        timer?.invalidate()
        supervisor?.stop()
    }
}

@main
struct AtlasApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var controller = AppController()

    var body: some Scene {
        WindowGroup("Atlas") {
            RootView().environmentObject(controller).environmentObject(controller.model)
                .frame(minWidth: 900, minHeight: 600)
                .task {
                    AppDelegate.onTerminate = { [weak controller] in controller?.shutdown() }
                    await controller.start()
                }
        }
        .commands {
            CommandMenu("Funcionário") {
                Button("Pare tudo") { Task { await controller.model.stopAll() } }
                    .keyboardShortcut(".", modifiers: [.command])
                Button("Reiniciar serviços") { Task { await controller.model.restart() } }
                Button("Encerrar serviços") { controller.shutdown() }
            }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var controller: AppController
    @EnvironmentObject var model: AtlasViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                Text(model.name).font(.title2).bold()
                Circle().fill(model.connection == .connected ? Color.green : Color.orange).frame(width: 8, height: 8)
                Text(model.connection.text).foregroundStyle(.secondary).font(.callout)
                Spacer()
                Text("Inteligência: \(model.intelligenceText)").font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }.padding()
            if let boot = controller.bootError {
                HStack {
                    Text(boot).foregroundStyle(.red)
                    Button("Tentar de novo") { Task { await controller.start() } }
                }.padding(.horizontal)
            }
            if let err = model.lastError {
                Text(err).foregroundStyle(.red).font(.callout).padding(.horizontal).textSelection(.enabled)
            }
            if let note = model.notice {
                Text(note).foregroundStyle(.secondary).font(.callout).padding(.horizontal)
            }
            TabView {
                ConversationView().tabItem { Text("Conversa") }
                WorkView().tabItem { Text("Trabalho") }
                ApprovalsView().tabItem { Text("Aprovações") }
                SettingsView().tabItem { Text("Configurações") }
                HealthView().tabItem { Text("Saúde") }
            }.padding()
        }
    }
}

// MARK: - Conversation

struct ConversationView: View {
    @EnvironmentObject var model: AtlasViewModel
    @State private var text = ""
    @State private var asTask = false
    @State private var dropTargeted = false
    @State private var previewText: String?

    var body: some View {
        VStack(spacing: 8) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if model.hasOlderMessages {
                            Button("Carregar mensagens anteriores") { Task { await model.loadOlder() } }
                                .buttonStyle(.link)
                        }
                        ForEach(model.messages) { m in
                            Bubble(message: m, preview: { id in
                                Task { previewText = await model.preview(artifactId: id) }
                            }).id(m.id)
                        }
                    }.padding(.vertical, 4)
                }
                .onChange(of: model.messages.count) { _ in
                    if let last = model.messages.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            if !model.attachments.isEmpty {
                ScrollView(.horizontal) {
                    HStack {
                        ForEach(model.attachments) { a in
                            HStack(spacing: 4) {
                                Image(systemName: "paperclip")
                                Text("\(a.name) · \(ByteCountFormatter.string(fromByteCount: Int64(a.sizeBytes), countStyle: .file))")
                                Button { model.removeAttachment(a) } label: { Image(systemName: "xmark.circle.fill") }
                                    .buttonStyle(.borderless)
                            }
                            .padding(6).background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                        }
                    }
                }
            }
            if let draft = model.failedDraft {
                HStack {
                    Text("Não enviado: «\(draft.text.prefix(60))»").foregroundStyle(.orange)
                    Button("Tentar de novo") { Task { await model.retryFailedSend() } }.disabled(model.isSending)
                }
            }
            HStack(alignment: .bottom) {
                Button {
                    pickFiles()
                } label: { Image(systemName: "paperclip") }
                    .help("Anexar arquivo (uma cópia é importada; o original não é alterado)")
                    .disabled(model.isAttaching)
                TextField("Converse com o Atlas… (\"pare\" interrompe o trabalho)", text: $text, axis: .vertical)
                    .textFieldStyle(.roundedBorder).lineLimit(1...5)
                    .onSubmit(send)
                Toggle("Como tarefa", isOn: $asTask).toggleStyle(.checkbox)
                    .help("Envia direto como tarefa, sem interpretação")
                Button(model.isSending ? "Enviando…" : "Enviar", action: send)
                    .keyboardShortcut(.return, modifiers: [.command])
                    .disabled(model.isSending || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if model.isAttaching { ProgressView("Importando anexo…").controlSize(.small) }
        }
        .overlay(dropTargeted ? RoundedRectangle(cornerRadius: 8).stroke(Color.accentColor, lineWidth: 2) : nil)
        .onDrop(of: [UTType.fileURL], isTargeted: $dropTargeted) { providers in
            for provider in providers {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    guard let url else { return }
                    Task { @MainActor in await model.attach(fileURL: url) }
                }
            }
            return true
        }
        .sheet(isPresented: Binding(get: { previewText != nil }, set: { if !$0 { previewText = nil } })) {
            VStack(alignment: .leading) {
                Text("Pré-visualização (somente texto; nada é executado ou carregado da internet)")
                    .font(.caption).foregroundStyle(.secondary)
                ScrollView {
                    Text(previewText ?? "").font(.system(.body, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                HStack { Spacer(); Button("Fechar") { previewText = nil }.keyboardShortcut(.cancelAction) }
            }.padding().frame(minWidth: 640, minHeight: 480)
        }
    }

    private func send() {
        let t = text
        text = ""
        Task { await model.send(t, delegate: asTask) }
    }

    private func pickFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.resolvesAliases = false
        panel.allowedContentTypes = [.plainText, .pdf, .png, .jpeg, .json, .commaSeparatedText, .html, .zip,
                                     UTType(filenameExtension: "md") ?? .plainText,
                                     UTType(filenameExtension: "docx") ?? .data,
                                     UTType(filenameExtension: "xlsx") ?? .data,
                                     UTType(filenameExtension: "pptx") ?? .data]
        guard panel.runModal() == .OK else { return }
        let urls = panel.urls
        Task { for url in urls { await model.attach(fileURL: url) } }
    }
}

struct Bubble: View {
    @EnvironmentObject var model: AtlasViewModel
    let message: ChatMessage
    let preview: (String) -> Void

    private var tint: Color {
        switch message.kind {
        case "question": return .orange.opacity(0.18)
        case "error": return .red.opacity(0.12)
        case "result": return .green.opacity(0.15)
        case "memory": return .purple.opacity(0.12)
        default: return message.isOwner ? .accentColor.opacity(0.18) : Color.gray.opacity(0.12)
        }
    }

    private var label: String? {
        ["question": "Pergunta", "result": "Resultado", "status": "Status", "memory": "Memória",
         "control": "Controle", "error": "Aviso", "ack": "Tarefa", "correction": "Correção", "answer": "Resposta"][message.kind]
    }

    var body: some View {
        HStack {
            if message.isOwner { Spacer(minLength: 80) }
            VStack(alignment: .leading, spacing: 6) {
                if let label { Text(label).font(.caption2).bold().foregroundStyle(.secondary) }
                Text(message.content).textSelection(.enabled)
                HStack {
                    if message.kind == "memory", message.memoryId != nil {
                        Button("Confirmar memória") { Task { await model.confirmMemory(message) } }
                    }
                    if let artifact = message.artifactId {
                        Button("Visualizar") { preview(artifact) }
                        Button("Salvar como…") { saveAs(artifact) }
                    }
                    if message.isOwner, message.taskId == nil, message.kind == "chat" {
                        Button("Delegar como tarefa") { Task { await model.delegate(message: message) } }
                            .disabled(model.isSending)
                    }
                }.buttonStyle(.link).font(.caption)
            }
            .padding(10).background(tint, in: RoundedRectangle(cornerRadius: 10))
            if !message.isOwner { Spacer(minLength: 80) }
        }
    }

    private func saveAs(_ artifactId: String) {
        let panel = NSSavePanel()  // the panel itself asks before replacing an existing file
        panel.canCreateDirectories = true
        panel.nameFieldStringValue = "entrega"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.export(artifactId: artifactId, to: url) }
    }
}

// MARK: - Work and approvals

struct WorkView: View {
    @EnvironmentObject var model: AtlasViewModel

    var body: some View {
        List(model.tasks) { task in
            TaskRow(task: task)
        }
    }
}

struct TaskRow: View {
    @EnvironmentObject var model: AtlasViewModel
    let task: TaskItem
    @State private var artifacts: [[String: Any]] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(task.objective).font(.headline)
            Text(task.stateText + (task.blockedReason.map { " · \($0)" } ?? "")).font(.caption)
            HStack {
                Button("Pausar") { Task { await model.control("tasks.pause", task) } }
                Button("Retomar") { Task { await model.control("tasks.resume", task) } }
                Button("Cancelar", role: .destructive) { Task { await model.control("tasks.cancel", task) } }
            }.buttonStyle(.borderless)
            ForEach(Array(artifacts.enumerated()), id: \.offset) { _, a in
                Text("\(a["relation"] as? String == "output" ? "Entrega" : "Anexo"): \(a["name"] as? String ?? "") v\(a["version"] as? Int ?? 0)")
                    .font(.caption)
            }
        }
        .task(id: task.state) { artifacts = await model.artifacts(of: task) }
    }
}

struct ApprovalsView: View {
    @EnvironmentObject var model: AtlasViewModel

    var body: some View {
        List(Array(model.approvals.enumerated()), id: \.offset) { _, ap in
            VStack(alignment: .leading, spacing: 4) {
                Text("\(ap["action_type"] as? String ?? "") → \(ap["destination"] as? String ?? "")").font(.headline)
                Text("Risco \(ap["risk_class"] as? String ?? "") · expira \(ap["expires_at"] as? String ?? "")").font(.caption)
                if let cost = ap["max_cost"] as? [String: Any] {
                    Text("Custo máximo: \(MoneyText.format(minor: cost["amount_minor"] as? Int ?? 0, currency: cost["currency"] as? String ?? "USD"))")
                        .font(.caption)
                }
                HStack {
                    Button("Aprovar") { Task { await model.decide(ap, approve: true) } }
                    Button("Rejeitar", role: .destructive) { Task { await model.decide(ap, approve: false) } }
                }
            }
        }
    }
}

// MARK: - Settings and health

struct SettingsView: View {
    @EnvironmentObject var model: AtlasViewModel
    @State private var key = ""
    @State private var checkCents = 5

    var body: some View {
        Form {
            Section("Chave da API (guardada no Keychain)") {
                SecureField("sk-…", text: $key)
                Button("Guardar no Keychain") {
                    let k = key
                    key = ""
                    Task { await model.registerKey(k) }
                }.disabled(key.isEmpty)
                Text("O uso da API é cobrado separadamente da assinatura do ChatGPT.").font(.caption)
            }
            Section("Orçamento") {
                Stepper("Teto mensal: \(MoneyText.format(minor: model.settings.monthlyMinor, currency: model.settings.currency))",
                        value: $model.settings.monthlyMinor, in: 1...1_000_000, step: 50)
                Stepper("Teto por tarefa: \(MoneyText.format(minor: model.settings.perTaskMinor, currency: model.settings.currency))",
                        value: $model.settings.perTaskMinor, in: 1...100_000, step: 10)
                TextField("Modelo (ID exato da API)", text: $model.settings.modelId)
                Toggle("Aceito usar a tabela de preços de referência \(model.settings.priceTable) como ESTIMATIVA",
                       isOn: $model.settings.acceptReferencePrices)
                Text(model.settings.pricesVerified
                     ? "Tabela de preços verificada."
                     : "Os preços não foram verificados com o provedor. Sem o aceite acima, nenhuma chamada paga é feita; com o aceite, o teto é uma estimativa, não uma garantia.")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Button(model.isSavingSettings ? "Salvando…" : "Salvar configuração") { Task { await model.saveSettings() } }
                        .disabled(model.isSavingSettings)
                    Text("Revisão \(model.settings.revision)").font(.caption).foregroundStyle(.secondary)
                }
            }
            Section("Testar inteligência (uma chamada paga pequena)") {
                Stepper("Teto do teste: \(MoneyText.format(minor: checkCents, currency: model.settings.currency))",
                        value: $checkCents, in: 1...50)
                Button(model.isChecking ? "Testando…" : "Testar agora") { Task { await model.testIntelligence(maxCents: checkCents) } }
                    .disabled(model.isChecking)
            }
        }
    }
}

struct HealthView: View {
    @EnvironmentObject var model: AtlasViewModel

    var body: some View {
        Form {
            Section("Conexão") {
                Text(model.connection.text)
                Text(model.serviceStatus?() ?? "—").font(.caption)
                Text("Cursor de eventos: \(model.eventCursor)").font(.caption).foregroundStyle(.secondary)
                Button("Reiniciar serviços") { Task { await model.restart() } }
            }
            Section("Componentes") {
                ForEach(model.components.sorted(by: { $0.key < $1.key }), id: \.key) { k, v in
                    HStack { Text(k); Spacer(); Text(v).foregroundStyle(v == "ok" || v == "ready" ? .green : .secondary) }
                }
                Text("Inteligência: \(model.intelligenceText)").font(.caption)
            }
        }
    }
}
