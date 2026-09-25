import AppKit
import AtlasKit
import SwiftUI
import UniformTypeIdentifiers

// Atlas development app (Alpha 2). Compiled on the macOS CI runner; interactive behaviour must still be
// validated on a real Mac (D-01). All core I/O goes through AtlasConnection (async, off the main actor).

final class AppDelegate: NSObject, NSApplicationDelegate {
    /// Quitting the app stops the services (single database writer). Keeping Atlas working after quit
    /// needs the login item (SMAppService), which must be validated on a real Mac (D-01).
    static var onTerminateAsync: (() async -> Void)?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// A3-31: the services stop OFF the main actor with a deadline; the window stays responsive and the
    /// app quits when the bounded stop returns (graceful or forced, never an unbounded wait).
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let stop = AppDelegate.onTerminateAsync else { return .terminateNow }
        Task { @MainActor in
            await stop()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

/// Owns the Supervisor and the connection; the view model holds all UI state.
@MainActor
final class AppController: ObservableObject {
    @Published var bootError: String?
    @Published var starting = true
    let supervisor: Supervisor?
    let model: AtlasViewModel
    let setup: ProductSetupModel
    let voice: VoiceController
    private var timer: Timer?

    init() {
        var sup: Supervisor?
        do { sup = Supervisor(config: try AppController.bundledConfig()) } catch { sup = nil }
        supervisor = sup
        let connection = AtlasConnection(timeout: 30) {
            guard let sup else { throw SupervisorError.notRunning }
            return try sup.session()
        }
        // A3-04: "Pare tudo" has its own socket and queue; it never waits behind the conversation.
        let controlLane = AtlasConnection(timeout: 10) {
            guard let sup else { throw SupervisorError.notRunning }
            return try sup.session()
        }
        let api = AtlasAPI(transport: connection, control: controlLane)
        model = AtlasViewModel(api: api)
        setup = ProductSetupModel(api: api)
        voice = VoiceController(capture: NativeVoiceCapture(), output: NativeVoiceOutput())
        connection.onStateChange = { [weak model] state in
            Task { @MainActor in model?.setConnectionState(state) }
        }
        model.restartServices = { [sup] in
            guard let sup else { throw SupervisorError.notRunning }
            try await Task.detached { try sup.restart() }.value
            connection.reset()
            controlLane.reset()
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
                do {
                    try await Task.detached(priority: .userInitiated) { try supervisor.start() }.value
                } catch SupervisorError.alreadyRunning {
                    // A3-28: another Atlas window owns the services; connect to it, never take over.
                    model.noteExternalServices()
                }
            }
            bootError = nil
            await model.start()
            await setup.load()
            timer?.invalidate()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
                Task { @MainActor in await self?.model.refresh() }
            }
        } catch {
            bootError = "Não foi possível iniciar os serviços: \(AtlasViewModel.friendly(error))"
        }
        starting = false
    }

    /// Bounded and off the main actor (A3-31). Says what had to be forced, if anything.
    func shutdown() async {
        timer?.invalidate()
        voice.cancelRecording()
        voice.stopSpeaking()
        guard let supervisor else { return }
        let report = await Task.detached(priority: .userInitiated) { supervisor.stop(grace: 8) }.value
        model.noteShutdown(forced: report.forced)
    }
}

@main
struct AtlasApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var controller = AppController()

    var body: some Scene {
        WindowGroup("Atlas") {
            RootView().environmentObject(controller).environmentObject(controller.model)
                .environmentObject(controller.setup).environmentObject(controller.voice)
                .frame(minWidth: 900, minHeight: 600)
                .task {
                    AppDelegate.onTerminateAsync = { [weak controller] in await controller?.shutdown() }
                    await controller.start()
                }
        }
        .commands {
            CommandMenu("Funcionário") {
                Button("Pare tudo") { Task { await controller.model.stopAll() } }
                    .keyboardShortcut(".", modifiers: [.command])
                Button("Reiniciar serviços") { Task { await controller.model.restart() } }
                Button("Encerrar serviços") { Task { await controller.shutdown() } }
            }
        }
    }
}

struct RootView: View {
    @EnvironmentObject var setup: ProductSetupModel
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
            if setup.loaded && !setup.completed {
                OnboardingView()
            } else {
            TabView {
                ConversationView().tabItem { Text("Conversa") }
                WorkView().tabItem { Text("Trabalho") }
                MemoryView().tabItem { Text("Memória") }
                FilesView().tabItem { Text("Arquivos") }
                ApprovalsView().tabItem { Text("Aprovações") }
                SettingsView().tabItem { Text("Configurações") }
                IdentityEditor().tabItem { Text("Identidade") }.task { await setup.load() }
                PrivacyView().tabItem { Text("Privacidade") }.task { await setup.load() }
                HealthView().tabItem { Text("Saúde") }
            }.padding()
            }
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
            VoiceComposer(text: $text)
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
                    Text(model.confirmingReceipt
                         ? "Confirmando recebimento de «\(draft.text.prefix(60))»…"
                         : "Não confirmado: «\(draft.text.prefix(60))»")
                        .foregroundStyle(.orange)
                    Button("Tentar de novo (mesmo pedido)") { Task { await model.retryFailedSend() } }
                        .disabled(model.isSending)
                }
            }
            if !model.importResults.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(model.importResults) { r in
                        Text(r.ok ? "✓ \(r.name)" : "✗ \(r.name): \(r.error ?? "erro")")
                            .font(.caption).foregroundStyle(r.ok ? Color.secondary : Color.red)
                    }
                    Button("Limpar") { model.clearImportResults() }.buttonStyle(.link).font(.caption)
                }
            }
            if let q = model.replyTarget {
                HStack {
                    Text("Respondendo à pergunta: «\(q.content.prefix(80))»").font(.caption)
                    Button { model.clearTargets() } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.borderless).accessibilityLabel("Cancelar resposta")
                }
            } else if let t = model.taskTarget {
                HStack {
                    Text("Sobre a tarefa: «\(t.objective.prefix(80))»").font(.caption)
                    Button { model.clearTargets() } label: { Image(systemName: "xmark.circle.fill") }
                        .buttonStyle(.borderless).accessibilityLabel("Cancelar vínculo com a tarefa")
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
                Button(role: .destructive) { Task { await model.stopAll() } } label: {
                    Label(model.isStopping ? "Parando…" : "Parar tudo", systemImage: "stop.circle")
                }
                .help("Interrompe o trabalho agora (⌘.). Funciona mesmo durante um envio.")
                .accessibilityLabel("Parar todo o trabalho")
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
            // A3-21: collect EVERY dropped URL, then hand them to the import queue in one go.
            let group = DispatchGroup()
            let lock = NSLock()
            var urls: [URL] = []
            for provider in providers {
                group.enter()
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url {
                        lock.lock()
                        urls.append(url)
                        lock.unlock()
                    }
                    group.leave()
                }
            }
            group.notify(queue: .main) {
                Task { @MainActor in await model.attach(fileURLs: urls) }
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
        guard panel.runModal() == .OK, let url = panel.urls.first else { return }
        let urls = panel.urls
        _ = url
        Task { await model.attach(fileURLs: urls) }
    }
}

struct Bubble: View {
    @EnvironmentObject var voice: VoiceController
    @EnvironmentObject var setup: ProductSetupModel
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
                if !message.isOwner {
                    Button("Ouvir resposta") { voice.speak(message.content, locale: setup.identity.locale) }
                        .buttonStyle(.link).font(.caption).disabled(voice.recording)
                }
                HStack {
                    if message.kind == "memory", message.memoryId != nil {
                        Button("Confirmar memória") { Task { await model.confirmMemory(message) } }
                    }
                    if message.kind == "question" {
                        Button("Responder") { model.reply(to: message) }
                            .accessibilityLabel("Responder a esta pergunta")
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
        Task { @MainActor in
            // A3-32: start from the artifact's real name and extension; renaming stays possible.
            let name = await model.suggestedFileName(artifactId: artifactId)
            let panel = NSSavePanel()  // the panel itself asks before replacing an existing file
            panel.canCreateDirectories = true
            panel.nameFieldStringValue = name
            let ext = (name as NSString).pathExtension
            if !ext.isEmpty, let type = UTType(filenameExtension: ext) {
                panel.allowedContentTypes = [type]
                panel.allowsOtherFileTypes = false
            }
            guard panel.runModal() == .OK, let url = panel.url else { return }
            await model.export(artifactId: artifactId, to: url)
        }
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
                // A3-30: exactly the actions the core accepts in this state.
                ForEach(task.availableActions, id: \.self) { action in
                    Button(TaskItem.actionLabels[action] ?? action, role: action == "cancel" ? .destructive : nil) {
                        Task { await model.perform(action, on: task) }
                    }
                }
                if !["COMPLETED", "FAILED", "CANCELLED"].contains(task.state) {
                    Button("Falar sobre esta tarefa") { model.talk(about: task) }
                }
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
        VStack(alignment: .leading) {
            if !model.capabilityRequests.isEmpty {
                Text("Pedidos de recurso").font(.headline)
                ForEach(Array(model.capabilityRequests.enumerated()), id: \.offset) { _, r in
                    CapabilityRequestRow(item: r)
                }
                Divider()
            }
            approvalsList
        }
        .task { await model.loadCapabilityRequests() }
    }

    private var approvalsList: some View {
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

struct CapabilityRequestRow: View {
    @EnvironmentObject var model: AtlasViewModel
    let item: [String: Any]

    var body: some View {
        let req = item["request"] as? [String: Any] ?? [:]
        let price = req["price"] as? [String: Any] ?? [:]
        let renew = ["once": "pagamento único", "monthly": "mensal", "yearly": "anual"][price["recurrence"] as? String ?? ""] ?? ""
        VStack(alignment: .leading, spacing: 4) {
            Text("\(req["provider"] as? String ?? "") — \(req["missing_capability"] as? String ?? "")").bold()
            Text(req["problem"] as? String ?? "").font(.caption)
            Text("Preço observado: \(price["amount"] as? String ?? "") \(price["currency"] as? String ?? "") (\(renew))")
                .font(.caption)
            Text("Dados enviados: \((req["data_shared"] as? [String] ?? []).joined(separator: ", "))").font(.caption)
            Text("Alternativas: \((req["alternatives"] as? [String] ?? []).joined(separator: "; "))").font(.caption)
            Text("Aprovar não faz compra nem libera dados sensíveis.").font(.caption2).foregroundStyle(.secondary)
            HStack {
                Button("Aprovar") { Task { await model.decideCapability(item["request_id"] as? String ?? "", approve: true) } }
                Button("Recusar", role: .destructive) {
                    Task { await model.decideCapability(item["request_id"] as? String ?? "", approve: false) }
                }
            }
        }.padding(.vertical, 4)
    }
}

// MARK: - Memory and files (N06/N12)

struct MemoryView: View {
    @EnvironmentObject var model: AtlasViewModel
    @State private var editing: MemoryItem?
    @State private var draft = ""
    @State private var forgetting: MemoryItem?
    @State private var forgetText = ""

    var body: some View {
        VStack(alignment: .leading) {
            HStack {
                Text("O que o \(model.name) sabe").font(.headline)
                Spacer()
                Button("Exportar…") { exportAll() }
            }
            List(model.memories) { m in
                VStack(alignment: .leading, spacing: 4) {
                    Text(m.content).textSelection(.enabled)
                    Text("\(m.typeText) · \(m.statusText) · fonte: \(m.sourceKind == "owner_message" ? "você" : m.sourceKind)"
                         + (m.sensitivity == "SENSITIVE" ? " · sensível" : "")
                         + (m.validFrom != nil || m.validUntil != nil
                            ? " · vale de \(m.validFrom ?? "…") até \(m.validUntil ?? "…")" : ""))
                        .font(.caption).foregroundStyle(.secondary)
                    HStack {
                        if m.status == "proposed" {
                            Button("Confirmar") { Task { await model.confirmMemory(id: m.id) } }
                        }
                        Button("Corrigir") { editing = m; draft = m.content }
                        Button("Esquecer…", role: .destructive) {
                            forgetting = m
                            Task { forgetText = await model.forgetPreviewText(m) }
                        }
                    }.buttonStyle(.link).font(.caption)
                }
            }
        }
        .padding(.vertical, 4)
        .task { await model.loadMemories() }
        .sheet(item: $editing) { m in
            VStack(alignment: .leading) {
                Text("Corrigir memória (a versão anterior fica no histórico; a validade não muda)").font(.caption)
                TextField("Conteúdo", text: $draft, axis: .vertical).lineLimit(2...6)
                HStack {
                    Spacer()
                    Button("Cancelar") { editing = nil }
                    Button("Salvar") { Task { await model.correctMemory(m, newContent: draft); editing = nil } }
                        .keyboardShortcut(.defaultAction)
                }
            }.padding().frame(minWidth: 480)
        }
        .sheet(item: $forgetting) { m in
            VStack(alignment: .leading, spacing: 8) {
                Text("Esquecer: «\(m.content.prefix(120))»").font(.headline)
                Text(forgetText.isEmpty ? "Calculando o alcance…" : forgetText).font(.callout)
                HStack {
                    Spacer()
                    Button("Cancelar") { forgetting = nil }
                    Button("Não usar mais") { Task { await model.forget(m, scope: "stop_using"); forgetting = nil } }
                    Button("Apagar o conteúdo", role: .destructive) {
                        Task { await model.forget(m, scope: "erase"); forgetting = nil }
                    }
                }
            }.padding().frame(minWidth: 520)
        }
    }

    private func exportAll() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "memorias-atlas.json"
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        Task { await model.exportMemories(to: url) }
    }
}

struct FilesView: View {
    @EnvironmentObject var model: AtlasViewModel

    var body: some View {
        List(model.files) { f in
            HStack {
                VStack(alignment: .leading) {
                    Text("\(f.name) v\(f.version)")
                    Text("\(f.relation == "output" ? "Entrega" : "Entrada") · \(f.analysisText) · "
                         + ByteCountFormatter.string(fromByteCount: Int64(f.sizeBytes), countStyle: .file))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .task { await model.loadFiles() }
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
                Picker("Modo de inteligência", selection: $model.settings.mode) {
                    Text("Automático").tag("automatic")
                    Text("Econômico").tag("economic")
                    Text("Máxima qualidade").tag("max_quality")
                }
                .help("Automático escolhe pelo tipo de trabalho; Econômico usa o perfil validado mais barato; "
                      + "Máxima qualidade usa o mais forte validado. Nenhum modo aumenta o orçamento.")
                DisclosureGroup("Avançado: modelos por perfil") {
                    TextField("Geral (ID exato da API)", text: $model.settings.modelId)
                    TextField("Leve (ID exato da API)", text: $model.settings.lightModelId)
                    TextField("Profundo (ID exato da API)", text: $model.settings.deepModelId)
                    ForEach(["light", "general", "deep"], id: \.self) { p in
                        Text("\(["light": "Leve", "general": "Geral", "deep": "Profundo"][p] ?? p): "
                             + ((model.settings.profileStatus[p] ?? false) ? "validado" : "falta validar"))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
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
                HStack {
                    Button(model.isChecking ? "Testando…" : "Testar geral") {
                        Task { await model.testIntelligence(maxCents: checkCents) }
                    }
                    Button("Testar leve") {
                        Task { await model.testIntelligence(maxCents: checkCents, modelId: model.settings.lightModelId) }
                    }
                    Button("Testar profundo") {
                        Task { await model.testIntelligence(maxCents: checkCents, modelId: model.settings.deepModelId) }
                    }
                }.disabled(model.isChecking)
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
