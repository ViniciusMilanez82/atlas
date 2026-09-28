import SwiftUI
import AtlasKit

struct SkillsView: View {
    @EnvironmentObject var skills: SkillLibraryModel
    @State private var proposedDecision: String?
    @State private var confirmDecision = false
    @State private var reviewedVersion: TableSkillSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Habilidades do funcionário").font(.title2).bold()
                Spacer()
                Button("Atualizar") { Task { await skills.load() } }.disabled(skills.busy)
            }
            Text("Nesta edição: procedimentos reutilizáveis para transformar tabelas e calcular valores. Peça pela conversa; o Atlas prepara exemplos para você revisar aqui.")
                .font(.callout).foregroundStyle(.secondary)
            if let error = skills.error { Text(error).foregroundStyle(.red).textSelection(.enabled) }
            if let notice = skills.notice { Text(notice).foregroundStyle(.secondary).textSelection(.enabled) }
            if skills.skills.isEmpty {
                ContentUnavailableView("Nenhuma habilidade proposta", systemImage: "checklist",
                    description: Text("Exemplo de pedido: “Crie uma habilidade que multiplique quantidade por preço unitário. Teste antes de me pedir para aprovar.” É necessário configurar a inteligência para delegar esse pedido."))
            } else {
                HSplitView {
                    List(skills.skills) { version in
                        Button { Task { await skills.select(version) } } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("\(version.key) · v\(version.version)").bold()
                                Text(version.description).font(.caption)
                                Text(version.stateText).font(.caption).foregroundStyle(.secondary)
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 4)
                        }.buttonStyle(.plain).disabled(skills.busy)
                    }.frame(minWidth: 220, idealWidth: 260, maxWidth: 340)
                    ScrollView {
                        if let version = skills.selected {
                            VStack(alignment: .leading, spacing: 14) {
                                Text("\(version.key) — versão \(version.version)").font(.headline)
                                Text(version.description).textSelection(.enabled)
                                Text(version.stateText).bold()
                                Text("Permissões: apenas transformar dados entregues à tarefa e devolver o resultado à tarefa. Não executa código novo, não acessa contas e não envia dados à internet.")
                                    .font(.callout)
                                Text("Privacidade: \(version.classification)").font(.caption)
                                ForEach(Array(skills.columns.enumerated()), id: \.offset) { _, column in
                                    Text(columnDescription(column)).font(.callout).textSelection(.enabled)
                                }
                                if skills.examples.isEmpty { Text("Ainda não há resultado de teste nesta versão.") }
                                ForEach(Array(skills.examples.enumerated()), id: \.offset) { index, example in
                                    GroupBox("Exemplo \(index + 1): \(example["label"] as? String ?? "")") {
                                        VStack(alignment: .leading, spacing: 8) {
                                            Text(example["passed"] as? Bool == true ? "Aprovado no teste" : "Falhou no teste").bold()
                                            dataRows("Dados de entrada", example["rows"])
                                            dataRows("Resultado esperado", example["expected"])
                                            dataRows("Resultado obtido", example["actual"])
                                            if let code = example["actual_error"] as? String { Text("Erro obtido: \(code)") }
                                            if let code = example["expected_error"] as? String { Text("Erro esperado: \(code)") }
                                        }.frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                }
                                Text("Os testes conferem esses exemplos; não garantem que o procedimento sirva para qualquer situação. Confira os campos e os valores antes de ativar.").font(.callout)
                                HStack {
                                    if ["DRAFT", "TESTED"].contains(version.state) {
                                        Button("Executar testes") { Task { await skills.testSelected() } }
                                    }
                                    if version.canActivate { Button("Ativar esta versão") { ask("activate") } }
                                    if version.canRollback { Button("Restaurar esta versão") { ask("rollback") } }
                                    if version.state == "ACTIVE" { Button("Bloquear para revisão") { ask("quarantine") } }
                                    if version.state != "REVOKED" { Button("Revogar", role: .destructive) { ask("revoke") } }
                                }.disabled(skills.busy)
                                DisclosureGroup("Identificação e integridade") {
                                    Text("Versão: \(version.id)\nHash: \(version.contentHash)\nTeste: \(version.testId ?? "não executado")")
                                        .font(.caption.monospaced()).textSelection(.enabled)
                                }
                            }.padding()
                        } else { Text("Selecione uma versão para conferir os exemplos.").padding() }
                    }.frame(minWidth: 440)
                }
            }
            if skills.busy { ProgressView("Registrando e verificando…") }
        }
        .task { await skills.load() }
        .confirmationDialog("Confirmar decisão sobre a versão exibida?", isPresented: $confirmDecision) {
            Button("Confirmar") {
                if let operation = proposedDecision, let version = reviewedVersion {
                    Task { await skills.decide(operation, reviewed: version) }
                }
                proposedDecision = nil
            }
            Button("Cancelar", role: .cancel) { proposedDecision = nil }
        } message: {
            Text("Versão \(reviewedVersion?.key ?? "") v\(reviewedVersion?.version ?? 0). A decisão vale apenas para esta versão e seus testes. Restaurar ou ativar substitui a versão ativa anterior, sem apagar o histórico. Revogar impede novos usos, mas preserva resultados já produzidos.")
        }
    }
    private func ask(_ decision: String) { reviewedVersion = skills.selected; proposedDecision = decision; confirmDecision = true }
    private func columnDescription(_ column: [String: Any]) -> String {
        let op = column["op"] as? String ?? ""
        let labels = ["copy": "copiar", "upper": "maiúsculas", "lower": "minúsculas", "strip": "remover espaços externos",
                      "literal": "valor fixo", "add": "somar", "subtract": "subtrair", "multiply": "multiplicar", "divide": "dividir"]
        let fields = column["fields"] as? [String] ?? [column["field"] as? String ?? String(describing: column["value"] ?? "")]
        let scale = (column["scale"] as? Int).map { " · \($0) casas decimais, arredondamento de metade para cima" } ?? ""
        return "\(column["name"] as? String ?? ""): \(labels[op] ?? op) — \(fields.joined(separator: ", "))\(scale)"
    }
    @ViewBuilder private func dataRows(_ title: String, _ value: Any?) -> some View {
        if let rows = value as? [[String: Any]] {
            Text(title).font(.caption).bold()
            ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                Text("\(index + 1). " + row.keys.sorted().map { "\($0): \(String(describing: row[$0]!))" }.joined(separator: " | "))
                    .font(.caption).textSelection(.enabled)
            }
        }
    }
}
