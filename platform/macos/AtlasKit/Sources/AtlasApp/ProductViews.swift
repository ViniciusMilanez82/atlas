import AtlasKit
import SwiftUI

struct SetupNotice: View {
    @EnvironmentObject var setup: ProductSetupModel
    var body: some View {
        VStack(alignment: .leading) {
            if let error = setup.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            if let notice = setup.notice { Text(notice).font(.caption).foregroundStyle(.secondary) }
        }
    }
}

struct IdentityEditor: View {
    @EnvironmentObject var setup: ProductSetupModel
    @EnvironmentObject var model: AtlasViewModel
    var body: some View {
        Form {
            Section("Apresente-se ao seu funcionário") {
                TextField("Seu nome", text: $setup.identity.ownerName)
                TextField("Nome do funcionário", text: $setup.identity.name)
                Picker("Idioma das respostas", selection: $setup.identity.locale) {
                    Text("Português (Brasil)").tag("pt-BR")
                    Text("English (US)").tag("en-US")
                    Text("Español").tag("es-ES")
                }
                TextField("Fuso horário IANA", text: $setup.identity.timezone)
                Text("Exemplo: America/Sao_Paulo. Alterar o nome não cria outro funcionário nem apaga memórias.")
                    .font(.caption).foregroundStyle(.secondary)
                Button("Salvar identidade") {
                    Task { await setup.saveIdentity(); await model.refreshIdentity() }
                }.disabled(setup.busy)
            }
            Section("Ambiente próprio") {
                Text("Suas contas, pastas e sessões pessoais não são importadas automaticamente. Arquivos entram somente quando você escolhe compartilhá-los.")
                Text("Esta versão é Alpha. Navegador virtual, contas operacionais e acesso pelo celular ainda não estão disponíveis.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            SetupNotice()
        }.padding()
    }
}

struct PrivacyView: View {
    @EnvironmentObject var setup: ProductSetupModel
    @EnvironmentObject var model: AtlasViewModel
    var body: some View {
        Form {
            Section("Informações sensíveis — provedor OpenAI") {
                Text("Guardar informações no Atlas é diferente de autorizar seu envio a um serviço de IA. Por padrão, conteúdo sensível não é enviado.")
                Toggle("Permitir conteúdo sensível nas conversas", isOn: $setup.sensitiveConversation)
                Toggle("Permitir conteúdo sensível nas tarefas", isOn: $setup.sensitiveTasks)
                Text("Estas permissões valem para novas chamadas à OpenAI, nas finalidades marcadas, até você revogar. Não são autorizações para compras, divulgação a terceiros ou outros provedores. Senhas e tokens continuam bloqueados no contexto do modelo.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Consulta a páginas públicas") {
                Toggle("Permitir a ferramenta de leitura de páginas públicas", isOn: $setup.webEnabled)
                Text("A ferramenta web.fetch consulta endereços fornecidos ao agente. Não é um navegador virtual nem libera login em suas contas. Restrições de destino existentes são preservadas.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Aplicar decisão") {
                Button("Salvar privacidade e pesquisa") {
                    Task { await setup.savePrivacy(); try? await model.loadSettings() }
                }.disabled(setup.busy || !setup.settingsSaved)
                Text("Desmarcar e salvar impede novos envios naquele escopo. Não apaga dados já recebidos pelo provedor. A cifra do banco em uso ainda não está implementada nesta Alpha; não use dados reais sensíveis para testar.")
                    .font(.caption).foregroundStyle(.secondary)
                SetupNotice()
            }
        }.padding()
    }
}

struct OnboardingView: View {
    @EnvironmentObject var setup: ProductSetupModel
    @EnvironmentObject var model: AtlasViewModel
    @State private var step = 0
    private let titles = ["Identidade", "Inteligência e orçamento", "Privacidade", "Concluir"]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Bem-vindo ao Atlas").font(.largeTitle).bold()
            Text("Configure seu funcionário. Nenhuma conta pessoal, assinatura ou chamada paga será criada automaticamente.")
                .foregroundStyle(.secondary)
            Picker("Etapa", selection: $step) {
                ForEach(0..<titles.count, id: \.self) { Text("\($0 + 1). \(titles[$0])").tag($0) }
            }.pickerStyle(.segmented)
            Group {
                switch step {
                case 0: IdentityEditor()
                case 1: ScrollView { SettingsView().padding() }
                case 2: PrivacyView()
                default:
                    Form {
                        Section("Revisar a configuração") {
                            Text("Funcionário: \(setup.identity.name)")
                            Text("Identidade: \(setup.identity.revision > 1 ? "salva" : "ainda não salva")")
                            Text("Orçamento: \(setup.settingsSaved ? "salvo" : "ainda não salvo")")
                            Text("Inteligência: \(setup.intelligenceReady ? "conexão validada" : "não validada")")
                            Text("O teste pequeno valida a conexão, não a qualidade de todas as tarefas. A versão continua Alpha.")
                                .font(.caption).foregroundStyle(.secondary)
                            Button("Concluir com inteligência configurada") { Task { await setup.finish(limited: false) } }
                                .disabled(setup.busy || !setup.intelligenceReady)
                            Button("Continuar em modo limitado, sem inteligência") { Task { await setup.finish(limited: true) } }
                                .disabled(setup.busy || setup.identity.revision <= 1 || !setup.settingsSaved)
                            Text("No modo limitado você pode organizar arquivos e configurações. Conversa livre e execução inteligente exigem uma chave e validação autorizada; não serão simuladas.")
                                .font(.caption).foregroundStyle(.secondary)
                            SetupNotice()
                        }
                    }.padding()
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            HStack {
                Button("Voltar") { step -= 1 }.disabled(step == 0)
                Spacer()
                Text("\(step + 1) de 4").font(.caption).foregroundStyle(.secondary)
                Button("Próxima etapa") { step += 1 }.disabled(step == 3)
            }
        }.padding(20)
            .onChange(of: step) { _ in Task { await setup.load() } }
    }
}

struct VoiceComposer: View {
    @EnvironmentObject var voice: VoiceController
    @EnvironmentObject var setup: ProductSetupModel
    @Binding var text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if voice.recording {
                    ProgressView().controlSize(.small)
                    Text(voice.phase == .preparing ? "Solicitando acesso ao microfone…" : "Microfone ativo — ditado local")
                    Button("Terminar ditado") { voice.finishRecording() }
                    Button("Descartar") { voice.cancelRecording() }
                } else {
                    Button { Task { await voice.start(locale: setup.identity.locale) } } label: {
                        Label("Ditar mensagem", systemImage: "mic")
                    }.disabled(voice.phase == .review)
                }
                if voice.reading { Button("Parar fala") { voice.stopSpeaking() } }
                Spacer()
                Text("Voz de IA · revise antes de enviar").font(.caption).foregroundStyle(.secondary)
            }
            if voice.phase == .review {
                TextEditor(text: $voice.transcript).frame(height: 80).border(.quaternary)
                HStack {
                    Text("Confira nomes, datas, valores e destinatários. O áudio não autoriza ações.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Usar no campo de mensagem") {
                        if let draft = voice.takeDraft() { text += (text.isEmpty ? "" : "\n") + draft }
                    }
                    Button("Descartar") { voice.cancelRecording() }
                }
            } else if voice.recording, !voice.transcript.isEmpty {
                Text(voice.transcript).font(.callout).foregroundStyle(.secondary).lineLimit(3)
            }
            if let error = voice.error { Text(error).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
        }.onDisappear { voice.cancelRecording(); voice.stopSpeaking() }
    }
}
