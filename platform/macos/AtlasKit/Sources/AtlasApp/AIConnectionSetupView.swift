import AtlasKit
import SwiftUI

struct AIConnectionSetupView: View {
    @EnvironmentObject var model: AIConnectionSetupModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirm = false
    @State private var maxCents = 5

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Conectar a inteligência do Atlas").font(.title2).bold()
                Spacer()
                Button("Fechar") { dismiss() }.disabled(model.busy).keyboardShortcut(.cancelAction)
            }
            Text(model.stage).textSelection(.enabled)
            if let error = model.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            if let cost = model.costText { Text(cost).font(.callout) }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if model.credentialRegistered == true {
                        Label("Sua chave já está guardada. Não precisa colar novamente.", systemImage: "lock.shield")
                    } else if model.loaded {
                        Text("O aplicativo ainda não confirmou uma chave registrada.")
                    }
                    DisclosureGroup(model.credentialRegistered == true ? "Trocar chave (opcional)" : "Registrar chave") {
                        SecureField("Chave da API da OpenAI", text: $model.newKey)
                        Text("Cole somente neste campo. Não envie a chave no chat ou no GitHub.").font(.caption)
                    }
                    Picker("Modelo para conversar", selection: $model.form.modelId) {
                        Text("Sol — uso geral").tag("gpt-6-sol")
                        Text("Luna — econômico").tag("gpt-6-luna")
                        Text("Astra — tarefas complexas").tag("gpt-6-astra")
                        if !["gpt-6-sol", "gpt-6-luna", "gpt-6-astra"].contains(model.form.modelId) {
                            Text("Atual: \(model.form.modelId)").tag(model.form.modelId)
                        }
                    }
                    Text("O acesso depende do projeto da sua chave. Salvar aqui não contrata um serviço nem escolhe outro modelo escondido.").font(.caption)
                    Stepper("Teto mensal: \(MoneyText.format(minor: model.form.monthlyMinor, currency: model.form.currency))",
                        value: $model.form.monthlyMinor, in: 1...1_000_000, step: 50)
                    Stepper("Teto por tarefa: \(MoneyText.format(minor: model.form.perTaskMinor, currency: model.form.currency))",
                        value: $model.form.perTaskMinor, in: 1...100_000, step: 10)
                    Toggle("Revisei e aceito usar a tabela de preços como estimativa", isOn: $model.form.acceptReferencePrices)
                    Text("Os valores da tabela ainda são estimativas, não garantia de cobrança. A assinatura do ChatGPT não inclui créditos desta API.").font(.caption)
                    Stepper("Teto desta validação: \(MoneyText.format(minor: maxCents, currency: model.form.currency))",
                        value: $maxCents, in: 1...50)
                    Text("Salvar e conectar usa a chave existente, salva os valores acima e testa uma resposta curta. Não acessa seus documentos, não faz compras e não manda mensagens externas.").font(.callout)
                }.padding(.vertical, 6).disabled(model.busy)
            }
            HStack {
                Button("Verificar novamente (sem chamada de IA)") { Task { await model.load() } }.disabled(model.busy)
                Spacer()
                if model.busy { ProgressView().controlSize(.small) }
                Button(model.busy ? "Conectando…" : "Salvar e conectar") { confirm = true }
                    .disabled(model.busy || !model.loaded)
                    .buttonStyle(.borderedProminent)
            }
            Text("Esta conexão não conclui as funções ainda ausentes da Alpha. Use dados fictícios nos testes.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(24).frame(minWidth: 650, idealWidth: 720, minHeight: 540)
        .task { await model.load() }
        .alert("Autorizar teste de conexão?", isPresented: $confirm) {
            Button("Cancelar", role: .cancel) {}
            Button("Salvar e testar") { Task { await model.connect(maxCents: maxCents) } }
        } message: {
            Text("Uma resposta curta poderá ser cobrada, com teto local de \(MoneyText.format(minor: maxCents, currency: model.form.currency)), limitado pelo saldo mensal do Atlas. Preços estimados. A chave já salva será reutilizada, a menos que você tenha preenchido a troca de chave.")
        }
    }
}
