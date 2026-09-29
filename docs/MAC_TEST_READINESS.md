# N22/N24 — preparação de teste manual no Mac

Incremento sobre o instalador do PR9 (`3c0aa38`). Não integra os componentes bloqueados dos PR10/11 e não significa a V1 completa.

## Implementado

Botão **Preparar meu teste** no cabeçalho, disponível antes de completar onboarding e quando a inicialização falha. Verifica versão/arquitetura e somente os componentes do próprio bundle, sem ler documentos pessoais. Consulta `system.health` autenticado por uma conexão própria de diagnóstico: timeout por operação de 3 segundos, sem reconexões automáticas. Não usa a fila da conversa nem a fila prioritária de parada. Não faz chamada de modelo, não cadastra credencial, não muda configurações e não cria tarefas.

Banco, executor e inteligência são estados distintos. Executar Python ou ter um processo vivo não significa que a IA funciona. Resposta ausente, incompleta ou com estados desconhecidos nunca aprova pré-requisitos. Novo diagnóstico invalida o resultado antigo antes de esperar I/O; cliques simultâneos não acumulam chamadas.

Exportação iniciada pelo dono por NSSavePanel. JSON com schema fixo: versão do Mac/build, localização normalizada (Aplicativos/translocado/outro), estados e textos constantes. Não inclui caminhos pessoais, variáveis de ambiente, identidade, token, conteúdo do banco, conversa ou exceção livre. Campos desconhecidos do servidor não são exportados. Nenhum envio automático. O diagnóstico não verifica a assinatura/notarização, não testa a IA real e não certifica segurança/produção.

O painel fornece um exercício fictício de cálculo (12 x 125,50 + 180 = 1.686,00) e um percurso manual de memória. Não envia esses pedidos por conta própria. O teste de inteligência existente continua dependente de consentimento, credencial e limite de custo.

## Testes e evidência

- 18 testes Swift de avaliação/exportação executados localmente no Linux, pacote isolado somente com a unidade nova: aprovados. Não é execução da interface macOS.
- 3 testes adicionais do modelo assíncrono escritos para macOS: somente leitura, falha após resultado verde, cliques simultâneos.
- Probe `atlas-bundle-check` estendido para avaliar o bundle real e a resposta IPC real; exige pré-requisitos locais saudáveis e inteligência NÃO configurada no ambiente sintético.
- CI geral e instalador devem compilar/testar/instalar/reinstalar esta revisão antes de fornecer pacote novo. Não presumir aprovação antecipada. Os resultados efetivos são registrados no PR.

## Escopo preservado

Nenhuma modificação em core, memória, cofre, aprovações, tools, skills, artifact manager ou integração VM. Nenhuma reaplicação de conteúdo previamente bloqueado. Main preservada; nenhuma credencial ou pagamento utilizado. Alpha ainda sem cifra completa em repouso, navegador integrado, contas operacionais, companion e homologação V1. Somente dados fictícios nos testes.

## Referências

- Apple Foundation ProcessInfo: https://developer.apple.com/documentation/foundation/processinfo
- Apple NSSavePanel: https://developer.apple.com/documentation/appkit/nssavepanel
- Apple segurança de apps: https://support.apple.com/pt-br/102445
