# Habilidades de tabela — incremento para revisão

## O que foi implementado

O Atlas pode propor um procedimento declarativo reutilizável, testar exemplos, solicitar revisão na
aba Habilidades e aplicar somente a versão aprovada a dados fornecidos em outra tarefa. Exemplos:
multiplicar quantidade por preço, limpar espaços, copiar ou renomear colunas. A pessoa confere dados
de entrada, resultado esperado e resultado obtido antes de ativar, restaurar, bloquear ou revogar.

A ferramenta skills.transform_rows recebe no máximo 50 linhas/8.000 bytes e devolve no máximo
12.000 bytes. Ela não abre nem grava arquivos; não aceita caminho ou artifact_id. A leitura de fontes,
quando necessária, pertence às ferramentas existentes com suas autorizações. Não é uma integração
com ERP nem a conclusão do ciclo de habilidades executáveis. ADR-020 detalha os limites.

## Evidências locais antes do CI

39 testes Python direcionados passaram na variante final limitada, usando interpretador, SQLite,
Broker, TaskEngine, controle de privacidade e IPC reais. O provedor de modelo é controlado localmente,
sem rede ou cobrança. Conferência: nenhum artefato é criado pela ferramenta de cálculo.
Cinco testes Swift de revisão foram escritos; a verificação sintática local não substitui compilação,
link, execução no macOS ou interação humana. Resultados do CI devem ser conferidos no PR, não supostos.

Cobertura dirigida: números grandes, arredondamento independente, formatos inválidos, ausência de
operações de script/rede/arquivo, limites, exemplos distintos, teste reprovado, versões imutáveis,
autorização exclusivamente local, integridade, restauração, invalidação após alteração do motor,
recibos idempotentes, reutilização real pelo Broker, três falhas/quarentena, revogação durante cálculo,
pausa/correção durante cálculo, proteção da descrição sensível e rollback de aprovação com falha de gravação.

O ambiente local usa Python 3.13.5 e dependências diferentes do lock do CI. Em verificações amplas
anteriores, a auditoria SBOM apontou essa divergência e um teste existente de início de subprocesso
atingiu timeout. As verificações não foram removidas. Ruff/mypy não estavam instalados e a instalação
falhou por DNS; a validação de tipos/lint fica a cargo do CI com as dependências fixadas.

## Bloqueios preservados e distribuição

Uma alteração no gerenciador de arquivos foi recusada pela plataforma e ficou de fora. O módulo
original foi preservado; esta variante não recria o efeito bloqueado. O PR é independente do PR10,
cujo navegador Linux ainda não passou no teste real; a ponte nativa Mac/VM continua não entregue.

O instalador antigo não contém este incremento. Só um novo artefato compilado e instalado com sucesso
pode ser fornecido como edição atualizada; ele continuará Alpha, sem Developer ID/notarização.
Nenhum teste de habilidade significa conclusão de VM, navegador, contas, voz contínua ou companion.

## Uso e privacidade

Abra Habilidades, selecione a proposta e confira operações e exemplos. Ative apenas uma versão que
represente seu pedido. Revogação bloqueia novos usos, não apaga exemplos ou resultados anteriores.
Testes aprovados não garantem a lógica de qualquer pedido; o LLM real ainda precisa ser avaliado.
A proteção completa em repouso, o restante da governança de exclusão e a jornada integral por uma
pessoa no Mac continuam pendentes. Usar somente informações fictícias nesta versão experimental.
