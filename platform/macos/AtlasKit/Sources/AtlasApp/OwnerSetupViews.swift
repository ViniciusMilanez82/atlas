import AppKit
import AtlasKit
import ServiceManagement
import SwiftUI

struct GettingStartedView: View {
    @EnvironmentObject var navigation: AppNavigation
    @EnvironmentObject var model: AtlasViewModel
    @EnvironmentObject var setup: OwnerSetupModel
    @State private var loginNotice = ""

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Seu funcionário digital").font(.largeTitle).bold()
                Text("Dê um nome, escolha como conversar e configure os limites. O Atlas usa arquivos próprios: suas contas e pastas pessoais não são importadas automaticamente.")
                GroupBox("1 · Este computador") {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")
                        Text("Memória: \(ByteCountFormatter.string(fromByteCount: Int64(ProcessInfo.processInfo.physicalMemory), countStyle: .memory))")
                        Text("Esta versão é de desenvolvimento. O computador virtual, os canais remotos e a criptografia do banco ainda precisam ser concluídos; use documentos fictícios nos testes.")
                            .foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("2 · Identidade") { IdentityFields() }
                GroupBox("3 · Inteligência e orçamento") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(model.intelligenceReady ? "A conexão configurada passou pelo teste de inteligência." : "Abra Configurações para guardar sua chave, definir o teto e testar a conexão.")
                        Text("O teste pode ter custo e pede sua ação explícita. A assinatura de um chat não configura automaticamente o acesso deste aplicativo à API.")
                            .font(.callout).foregroundStyle(.secondary)
                        Button("Abrir Configurações") { navigation.tab = "settings" }
                        Text("O teste de conexão não comprova sozinho a qualidade de uma tarefa completa.").font(.caption)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("4 · Privacidade") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Dados sensíveis ficam bloqueados para a nuvem até sua autorização. Em Configurações › Privacidade, escolha separadamente conversa e tarefas.")
                        Text("A voz local permite revisar o que foi entendido antes de enviar. Gravações não são guardadas pelo Atlas.")
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("Disponibilidade") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Fechar a janela mantém o aplicativo ativo. Sair do Atlas encerra seus serviços nesta versão. Mac suspenso ou desligado não trabalha.")
                        HStack {
                            Button("Abrir Atlas ao entrar no Mac") {
                                do { try SMAppService.mainApp.register(); loginNotice = loginStatus }
                                catch { loginNotice = "Não foi possível registrar o início automático: \(error.localizedDescription)" }
                            }
                            Button("Desativar início automático") {
                                do { try SMAppService.mainApp.unregister(); loginNotice = loginStatus }
                                catch { loginNotice = "Não foi possível desativar: \(error.localizedDescription)" }
                            }
                            Button("Ajustes de início") { SMAppService.openSystemSettingsLoginItems() }
                        }
                        Text(loginNotice.isEmpty ? loginStatus : loginNotice).font(.caption)
                        Text("Início ao fazer login não significa continuar trabalhando depois de sair do aplicativo.")
                            .font(.caption).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                if let error = setup.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
                if let notice = setup.notice { Text(notice).foregroundStyle(.secondary) }
                Button("Marcar apresentação como lida") { Task { await setup.saveProfile(step: "done") } }
                    .disabled(setup.busy || !setup.loaded)
                Text("Essa marca guarda apenas seu progresso na apresentação. Não certifica que todas as capacidades estão disponíveis.")
                    .font(.caption).foregroundStyle(.secondary)
            }.padding().frame(maxWidth: 850, alignment: .leading)
        }.task { await setup.load() }
    }

    private var loginStatus: String {
        switch SMAppService.mainApp.status {
        case .enabled: return "Início automático: autorizado."
        case .requiresApproval: return "Início automático: aguardando sua autorização nos Ajustes do Sistema."
        case .notRegistered: return "Início automático: desativado."
        case .notFound: return "Início automático: esta cópia não foi encontrada como aplicativo instalado."
        @unknown default: return "Início automático: estado desconhecido; consulte os Ajustes."
        }
    }
}

struct IdentityFields: View {
    @EnvironmentObject var model: AtlasViewModel
    @EnvironmentObject var setup: OwnerSetupModel
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Nome do funcionário", text: $setup.employeeName)
            TextField("Como chamar você", text: $setup.ownerName)
            Picker("Idioma de conversa", selection: $setup.locale) {
                Text("Português brasileiro").tag("pt-BR")
                Text("English").tag("en-US")
                Text("Español").tag("es-ES")
            }
            TextField("Fuso IANA (ex.: America/Sao_Paulo)", text: $setup.timezone)
            Button("Salvar identidade") {
                Task { if await setup.saveProfile(step: setup.step == "welcome" ? "identity" : nil) { await model.reloadIdentity() } }
            }.disabled(setup.busy || !setup.loaded)
        }.textFieldStyle(.roundedBorder).padding(5)
    }
}

struct PrivacySettingsView: View {
    @EnvironmentObject var model: AtlasViewModel
    @EnvironmentObject var setup: OwnerSetupModel
    @State private var confirming = false
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Compartilhar dados sensíveis com OpenAI").font(.headline)
            Text("Autorizar guardar uma informação não autoriza enviá-la à nuvem. Estas opções permitem apenas o conteúdo necessário para a finalidade selecionada; segredos continuam proibidos.")
            Toggle("Permitir dados sensíveis na conversa", isOn: $setup.sensitiveConversation)
            Toggle("Permitir dados sensíveis nas tarefas", isOn: $setup.sensitiveTasks)
            Divider()
            Toggle("Permitir consulta de páginas públicas pela ferramenta web.fetch", isOn: $setup.webEnabled)
            Text("Não é o navegador virtual: é uma consulta mediada de páginas. Sites autenticados e controles de acesso não são contornados.")
                .font(.caption).foregroundStyle(.secondary)
            TextField("Domínios permitidos (vazio: qualquer destino público aceito pela política)", text: $setup.allowedDomains, axis: .vertical)
            TextField("Domínios bloqueados, separados por vírgula", text: $setup.blockedDomains, axis: .vertical)
            Button("Revisar e salvar privacidade") { confirming = true }.disabled(setup.busy || !setup.loaded)
            if let error = setup.error { Text(error).foregroundStyle(.red) }
            if let notice = setup.notice { Text(notice).font(.caption) }
        }
        .task { await setup.load() }
        .alert("Confirmar sua decisão", isPresented: $confirming) {
            Button("Cancelar", role: .cancel) {}
            Button("Salvar estes limites") {
                Task { if await setup.savePrivacy() { try? await model.loadSettings() } }
            }
        } message: {
            Text("Conversa sensível: \(setup.sensitiveConversation ? "permitida" : "bloqueada"). Tarefas sensíveis: \(setup.sensitiveTasks ? "permitidas" : "bloqueadas"). Consulta web: \(setup.webEnabled ? "ativa" : "desativada"). A revogação bloqueia novos envios; não desfaz dados já enviados.")
        }
    }
}

struct VoicePanel: View {
    @EnvironmentObject var voice: VoiceController
    @EnvironmentObject var setup: OwnerSetupModel
    @Binding var draft: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if voice.state == .listening {
                    Label("Microfone ativo · reconhecimento local", systemImage: "mic.fill")
                    Button("Terminar gravação") { voice.finishCapture() }
                    Button("Descartar", role: .cancel) { voice.cancelCapture() }
                } else if voice.state == .authorizing {
                    Text("Aguardando permissão do microfone…")
                    Button("Cancelar") { voice.cancelCapture() }
                } else {
                    Button { Task { await voice.start(locale: setup.locale) } } label: { Label("Falar", systemImage: "mic") }
                        .help("Transcrever no Mac, revisar e só então enviar.")
                }
                if voice.isSpeaking {
                    Text("Voz sintetizada pelo computador").font(.caption)
                    Button("Pare de falar") { voice.stopSpeaking() }
                }
            }
            if voice.state == .review {
                Text("Revise especialmente nomes, datas e valores. Este texto ainda NÃO foi enviado.").font(.caption)
                TextField("Transcrição para revisão", text: $voice.transcript, axis: .vertical).lineLimit(1...5)
                HStack {
                    Button("Usar no rascunho") {
                        if let text = voice.takeReviewedText() { draft += (draft.isEmpty ? "" : "\n") + text }
                    }
                    Button("Descartar") { voice.cancelCapture() }
                }
            } else if voice.state == .listening {
                Text(voice.transcript.isEmpty ? "Estou ouvindo…" : voice.transcript).font(.callout)
            } else if case let .failed(why) = voice.state {
                Text(why).foregroundStyle(.orange).font(.caption)
                if !voice.transcript.isEmpty { Text("Trecho não enviado: \(voice.transcript)").textSelection(.enabled) }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
}
