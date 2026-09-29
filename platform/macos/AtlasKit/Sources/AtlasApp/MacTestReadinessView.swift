import AppKit
import AtlasKit
import SwiftUI
import UniformTypeIdentifiers

/// Available before onboarding completes and when core startup fails. Requires no Terminal.
struct MacTestReadinessView: View {
    @EnvironmentObject var readiness: MacTestReadinessModel
    @Environment(\.dismiss) private var dismiss
    @State private var saveMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Preparar meu teste no Mac").font(.title2).bold()
                    Text("Verificação local sem chamada paga e sem envio de arquivos.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                Spacer()
                Button("Fechar") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(readiness.report.summary).bold().accessibilityIdentifier("atlas.test.summary")
                    Text("Verde aqui não significa Atlas completo. Este painel verifica a instalação e o estado dos serviços; você ainda precisa testar o comportamento com dados fictícios.")
                        .font(.callout)
                    ForEach(readiness.report.checks) { check in
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: symbol(check.state)).foregroundStyle(color(check.state))
                                .accessibilityLabel(label(check.state))
                            VStack(alignment: .leading, spacing: 3) {
                                Text(check.title).bold()
                                Text(check.detail).font(.callout).foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                        }.accessibilityElement(children: .combine)
                    }
                    Divider()
                    Text("Depois da verificação").font(.headline)
                    Text("1. Termine Identidade e Privacidade. Em Configurações, registre sua chave e salve modelo e orçamento. O botão de teste da inteligência exige autorização e pode ter custo. Não envie sua chave por chat.")
                    Text("2. Na Conversa, use o pedido fictício abaixo. Confira o resultado, em vez de aceitar apenas a mensagem de conclusão.")
                    Text("Teste com dados fictícios: são 12 unidades a R$ 125,50 cada, mais R$ 180,00 de frete. Calcule pelo recurso de cálculo e apresente subtotal, frete e total. Não pesquise na internet, não envie mensagens e não faça compras.")
                        .textSelection(.enabled).padding(10).background(.quaternary).cornerRadius(6)
                    Text("Resultado esperado: subtotal R$ 1.506,00; frete R$ 180,00; total R$ 1.686,00. Esse acerto isolado não valida memória, autonomia ou todas as ferramentas.")
                        .font(.callout).foregroundStyle(.secondary)
                    Text("3. Teste a memória com uma preferência fictícia, confirmando-a na aba Memória. Feche e reabra o aplicativo e pergunte novamente. Se houver falha, salve o diagnóstico abaixo; não envie logs completos nem documentos pessoais.")
                    Divider()
                    Text("O diagnóstico salvo contém somente versão do sistema/aplicativo e estados fixos de verificação. Não inclui nome do usuário, caminhos pessoais, chaves, conversas, memórias ou documentos. Nada é enviado automaticamente.")
                        .font(.caption).foregroundStyle(.secondary)
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4)
            }
            HStack {
                Button(readiness.checking ? "Verificando…" : "Verificar este Mac") {
                    Task { await readiness.run() }
                }.disabled(readiness.checking).accessibilityIdentifier("atlas.test.run")
                Button("Salvar diagnóstico…") { saveReport() }.disabled(readiness.checking)
                if readiness.checking { ProgressView().controlSize(.small) }
                Spacer()
            }
            if let saveMessage { Text(saveMessage).font(.caption).textSelection(.enabled) }
        }.padding(22).frame(minWidth: 660, idealWidth: 760, minHeight: 520, idealHeight: 660)
    }

    private func saveReport() {
        // No automatic write or upload; the owner selects the destination using a native save panel.
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "Atlas-Diagnostico-Teste.json"
        panel.message = "Somente estados técnicos; nenhum conteúdo das suas conversas será incluído."
        panel.begin { response in
            guard response == .OK, let url = panel.url else { return }
            do {
                try readiness.report.json().write(to: url, options: .atomic)
                saveMessage = "Diagnóstico salvo no local que você escolheu. Nenhum envio foi feito."
            } catch {
                saveMessage = "Não foi possível salvar. Escolha outro destino; os dados do Atlas não foram alterados."
            }
        }
    }

    private func symbol(_ state: MacTestCheckState) -> String {
        switch state {
        case .passed: return "checkmark.circle.fill"
        case .blocked: return "exclamationmark.triangle.fill"
        case .notChecked: return "circle.dashed"
        case .limitation: return "info.circle"
        }
    }
    private func color(_ state: MacTestCheckState) -> Color {
        switch state {
        case .passed: return .green
        case .blocked: return .orange
        case .notChecked, .limitation: return .secondary
        }
    }
    private func label(_ state: MacTestCheckState) -> String {
        switch state {
        case .passed: return "Verificado"
        case .blocked: return "Atenção necessária"
        case .notChecked: return "Não verificado"
        case .limitation: return "Limitação"
        }
    }
}
