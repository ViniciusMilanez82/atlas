# ADR-020 — Habilidades declarativas e limitadas de transformação de dados

## Decisão e escopo

Entregar uma parte utilizável de N19 sem executar código gerado nem depender do workspace/VM ainda
não integrado. Uma habilidade é um documento JSON validado por esquema fechado, interpretado por
operações fixas e confiáveis. Não é Python, JavaScript, shell, SQL, macro ou expressão arbitrária.
A ferramenta recebe dados em memória e devolve dados. Não recebe caminhos ou IDs de arquivos e não
abre nem grava arquivos. Nenhuma permissão de rede, credenciais ou execução nova é concedida.

A proposta inicial de integração para gravação de artefatos exigia uma alteração que a plataforma
bloqueou em runtime/artifacts/manager.py. Essa alteração foi abandonada e não foi publicada.
Este incremento mantém o gerenciador original intacto. Não reproduzir a alteração bloqueada por
outro módulo, ferramenta, codificação ou workflow. A variante entregue é estritamente mais limitada:
skills.transform_rows faz apenas cálculos sobre linhas fornecidas e devolve resultados pequenos.
Também permanece respeitada a restrição anterior sobre publicação da ponte nativa Mac/VM.

## Representação e limites

Formato atlas.table.v1. Entre 1 e 30 colunas de saída, nomes únicos e chaves literais. Operações:
copy, upper, lower, strip, literal, add, subtract, multiply, divide. As quatro aritméticas usam dois
campos e escala de 0 a 8 casas. Números decimais chegam como strings com ponto; inteiros são aceitos.
Booleanos não viram valores monetários, notação ambígua, NaN, infinito e expoentes são rejeitados.
Contexto Decimal privado de 80 dígitos, arredondamento half-up, resultado limitado a 24 dígitos inteiros.

Ferramenta pública: até 50 linhas, 8.000 bytes de entrada canônica, 12.000 bytes de resultado canônico.
Esses limites são intencionais para evitar truncamento no contexto. O interpretador possui limites
defensivos adicionais, mas eles não ampliam os limites públicos. Não há extração de documento nesta
ferramenta: calcular corretamente não comprova que os valores fornecidos correspondem à fonte.

Cada proposta contém entre 2 e 12 exemplos. Exigir pelo menos dois conjuntos positivos distintos e
não vazios; comparar resultados realmente calculados e erros observados com os resultados esperados.
Os testes só demonstram aqueles exemplos, não a correção universal da lógica pretendida.

## Ciclo de vida

DRAFT -> TESTED -> ACTIVE. Uma nova versão ativa torna a anterior SUPERSEDED; nenhuma definição ou
resultado de teste é reescrito. QUARANTINED bloqueia novas execuções. REVOKED impede reutilização.
Após três tentativas com erro, colocar a versão em quarentena. Uma execução válida zera o contador.
Restaurar exige versão anterior já aprovada, testes atuais e decisão explícita do dono.

A ativação é vinculada ao employee/owner da sessão local autenticada, ID da versão, revisão, hash
do conteúdo, ID de teste e fingerprint do interpretador mais esquema. Mudança no interpretador ou
esquema invalida a aprovação antiga; uma nova versão precisa ser testada e revisada. Apenas a
interface local do proprietário decide; conteúdo da conversa, modelo, runtime e dispositivo remoto
não conseguem promover uma habilidade. Aprovar a habilidade não autoriza transações externas.

Recibos idempotentes ficam na mesma transação das decisões. Reenvio lê o estado atual e não reativa
uma versão revogada. Conflito de revisão não confirma silenciosamente uma versão nova.

## Execução e integração

skills.propose_table cria versão e executa exemplos via Broker. skills.catalog lista somente versões
ativas compatíveis, com paginação. skills.transform_rows usa ID/hash exatos. Metadados de tarefa e
observações determinam a classificação conservadora dos resultados e descrições. Segredos são recusados;
conteúdo sensível continua passando pelo Egress Guard existente antes de chegar a um provedor.

Ações usam o lease e a revisão atuais. Antes de registrar/devolver o resultado, revalidar cancelamento,
estado da tarefa, fencing token, revisão da instrução e aprovação da versão numa transação. Uma
revogação, pausa ou correção durante o cálculo impede liberar um resultado obsoleto. Registro de uso
contém IDs de tarefa/ação/versão e hashes de entrada/saída, não cria um artefato. O AgentRunner trata
lease revogado por controle do dono como interrupção normal, sem afrouxar a verificação de lease.

IPC: skills.list/get/test/decide; autorização por proprietário local em todos os endpoints. A aba
Habilidades mostra operações, entradas, expectativas e saídas reais; confirmação captura a versão
exibida, mesmo que outra seleção apareça durante uma resposta atrasada.

## Limitações que permanecem

Não é o ciclo completo de skills executáveis do contrato. Sem plugins arbitrários, navegação, ambiente
virtual, self-modification ou novas permissões. Sem avaliação com LLM real ou jornada humana do Mac
nesta preparação. Revogar não apaga exemplos/histórico; exclusão e retenção completas ainda precisam
ser integradas. Usar dados fictícios nesta Alpha; cifra completa em repouso continua pendente.
