# ATLAS — Revisão independente do PR #5
## Correções restantes, evidências locais e continuidade até o contrato v2

**Preparado para:** Vinícius Milanez  
**Data:** 25 de setembro de 2026  
**Repositório:** ViniciusMilanez82/atlas  
**Natureza:** revisão somente de leitura, sem alteração de código, issue, PR, permissões ou publicação.

## 1. Parecer executivo

O PR #5 representa avanço aproveitável, mas não comprova a resolução integral das 32 classes de achados anteriores e não entrega a V1 do funcionário digital. Ele já foi integrado. A revisão recomenda continuar sobre a base existente e corrigir nove achados abaixo, sem reverter o PR inteiro nem recomeçar o produto.

Esta revisão executou 14 cenários locais, independentes da suíte do projeto: 12 produziram comportamentos defeituosos, agrupados em nove achados; dois cenários completos de controle passaram. Há ainda uma verificação positiva de equação dentro do cenário de total incorreto. Esses números não representam taxa de falha do produto: os casos foram escolhidos para investigar riscos, não amostrados aleatoriamente.

**Decisão recomendada:** não homologar como Alpha local confiável para dados sensíveis e entregas autônomas nos caminhos afetados; não chamar Beta ou V1. Preservar as melhorias e executar uma rodada direcionada de correções com regressões negativas e positivas. Nenhuma alegação de vazamento real, compra indevida ou descoberta de todos os bugs é feita aqui.

## 2. Versão, origem e fidelidade do material

- PR: https://github.com/ViniciusMilanez82/atlas/pull/5
- Base: `d81cece2713ccb5b12e58902e55b05a614467951`.
- Head revisado: `80f357b44663b190a4cacc8038accf27d0c11c13`.
- Merge definitivo informado pelo GitHub: `5a997e3ba7e77c8aa8f58ebb688521e6b31011c0`.
- Merge do PR: 25/09/2026 às 11:25:51 UTC (08:25:51 em America/Sao_Paulo).
- Dimensão informada: 32 commits, 130 arquivos modificados, 17.088 adições e 594 remoções. Não foi feita inspeção exaustiva linha a linha de todas as adições.
- CI: execução `36128752671`, job macOS `108050875369`.
- O log do CI faz checkout do merge temporário `0bbc90fc813eb19be5216a4a4215fbec3286f4dc` — merge de `80f357b` sobre `d81cece`. Por isso o bundle mostra `0bbc90f`; não é apresentado como inconsistência do pacote.
- Artifact baixado: `10861445580`, `Atlas-dev-app`, ZIP de 54.266.872 bytes.
- SHA-256 recalculado localmente: `ace9d3c1069d7a9ecc295c73588fe2d0125fa123e8e40a0afb15e4ef8083422f`, idêntico ao digest informado pelo GitHub.

Foram extraídos os fontes de `Atlas.app/Contents/Resources/core-src` do pacote, e não executado o binário nativo. Os hashes Git blob de sete arquivos centrais foram recalculados e confrontados com os hashes retornados pelo GitHub no head revisado: todos coincidiram. O manifesto em `evidencias/source_manifest.json` registra quais arquivos foram comparados; não afirma comparação byte a byte de todos os arquivos do repositório.

## 3. O que foi realmente testado

### 3.1 Testes do projeto, vistos nos logs do CI

No job macOS da execução acima: **634 testes Python aprovados, 1 ignorado; 37 testes Swift aprovados**. Ruff, mypy e o scanner utilizado pelo projeto passaram. O teste ignorado é a chamada opt-in a um provedor real. O bundle foi construído e seu início foi verificado sem depender do Python do sistema. Há avisos de concorrência Swift nos testes; a compilação consultada passou. O job de captura de tela não demonstra uso interativo completo por uma pessoa.

Esses resultados pertencem ao CI do repositório, não a uma execução local minha da suíte completa. Não são inválidos por utilizarem doubles, mas cobrem apenas os comportamentos exercitados.

### 3.2 Execução independente desta revisão

Ambiente: Linux, Python 3.13.5, bibliotecas disponíveis no ambiente de revisão, diferentes em parte das versões fixadas no bundle. Foram executadas as classes reais do núcleo Python, banco SQLite e migrações reais, TaskEngine, ConversationService, AgentRunner, Broker, ArtifactManager, DocumentStore, Verifier e controles de orçamento/saída. O provedor foi substituído por um gravador local com respostas estruturadas sintéticas. O EgressGuard real ficou ativo.

Os testes chamam componentes de produção e provocam interleavings controlados; não passam pela interface SwiftUI ou por uma conexão IPC de ponta a ponta. No caso de extração PARTIAL foi preparada uma fixture de metadados. No caso de recurso aprovado foi injetada uma exceção após o commit, não desligado fisicamente um computador. A leitura longa utilizou TXT sintético. Esses limites são essenciais para interpretar os resultados.

**Não executado:** aplicativo interativo no Mac; binários nativos; suíte completa local; API real; VM; navegador; e-mail ou WhatsApp; cartões; distribuição/notarização; medição de desempenho no Mac. Não foram utilizadas credenciais reais ou dados pessoais. Nenhuma chamada externa de inferência ocorreu.

O script de reprodução foi construído nesta revisão; não foi importado da suíte do PR. Ele preserva as condições defeituosas como evidência. Seu resultado `DEFECT_REPRODUCED` NÃO significa aprovação do produto.

## 4. Avanços a preservar

A documentação e o código mostram melhorias: recuperação compartilhada de memória, metadados de privacidade em mais caminhos, canal de parada separado na aplicação, revisão de instruções no broker, keeper/watchdog, recibos duráveis, vínculo atômico de entradas na criação, extração documental por formato, leitura paginada, modos de inteligência, outbox e telas de arquivos/memória. Há também geração de formatos Office/PDF e pedido estruturado de recurso. Nem todas essas capacidades foram retestadas independentemente nesta revisão.

Dois controles locais confirmaram resultados positivos: uma mensagem sensível inicial foi bloqueada antes do provedor; e um documento TXT com 85 segmentos foi lido por ferramentas/broker reais em um fluxo de 30 etapas, com cobertura completa e sem falsamente acumular passos sem progresso. O modelo desse fluxo foi roteirizado; isso valida mecanismos, não autonomia/qualidade com um LLM real.

## 5. Quadro de achados

**P1:** prioridade alta antes de confiar no caminho afetado ou ampliar autonomia. **P2:** correção funcional/consistência necessária na próxima rodada. São prioridades de engenharia, não notas CVSS nem provas de exploração remota.

| ID | Prioridade | Achado | Casos locais |
|---|---|---|---|
| R5-01 | P1 | Dados sensíveis perdem a classificação em correções, respostas e notificações | `sensitive_correction`, `sensitive_answer`, `sensitive_outbox` |
| R5-02 | P1 | O pedido integral do proprietário é substituído pelo resumo produzido pelo modelo | `lost_original` |
| R5-03 | P1 | Um pedido em interpretação ainda pode gerar trabalho novo depois de “pare tudo” | `stop_during_interpretation` |
| R5-04 | P1 | Uma decisão “finish” antiga ainda conclui a tarefa depois de uma correção material | `old_finish_after_correction` |
| R5-05 | P1 | Verificação por palavras-chave e equações ainda aprova entregas erradas | `irrelevant_report`, `bad_total` |
| R5-06 | P1 | Extração PARCIAL pode ser marcada como leitura completa e validar a entrega | `partial_coverage` |
| R5-07 | P2 | Anexo enviado como resposta fica na conversa, mas não entra na tarefa | `answered_attachment` |
| R5-08 | P2 | Validação de URL confunde cadastro de fonte com consulta autenticada da tarefa | `source_scope` |
| R5-09 | P2 | Decisão sobre recurso pode persistir sem retomar o trabalho e sem reenvio recuperável | `capability_crash` |

## 6. Achados detalhados e ordem de correção

### R5-01 — Dados sensíveis perdem a classificação em correções, respostas e notificações

**Prioridade:** P1  
**Rastreabilidade:** A3-02; contrato v2, capítulos 6.3, 8 e 9.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/agent/loop.py:285–300](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/agent/loop.py#L285-L300); [runtime/agent/loop.py:402–472](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/agent/loop.py#L402-L472); [runtime/tasks/engine.py:533–612](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/tasks/engine.py#L533-L612); [runtime/notifications/outbox.py:23–104](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/notifications/outbox.py#L23-L104)

**O que foi observado.** Executei três caminhos com sentinelas fictícias. Uma correção e uma resposta foram reconhecidas no banco como SENSITIVE, mas entraram no payload destinado ao provedor como INTERNAL. A outbox, ao publicar o resultado de uma tarefa sensível, gerou uma mensagem INTERNAL; uma conversa posterior reutilizou seu conteúdo sem o consentimento necessário. O cliente utilizado foi o BudgetedModelClient real, com EgressGuard real habilitado. O provedor final era apenas um gravador local, não uma API externa.

O controle positivo com uma mensagem sensível inicial foi corretamente bloqueado antes de chamar esse provedor. Portanto, não se trata da ausência total do Egress Guard: a classificação se perde em transformações posteriores.

**Causa.** TaskEngine.instructions não retorna classificação. AgentRunner._context constrói itens de instrução com a classificação padrão. _owner_messages consulta texto/papel/tipo, mas descarta classificação e origem detalhada. A inserção da outbox em messages também não inclui classification. A proteção na saída confia em metadados já degradados.

**Impacto.** Um documento ou dado pessoal que o proprietário esperava manter restrito pode ser exposto numa chamada posterior. Não houve vazamento real nesta revisão: foram usados somente dados sintéticos e não houve tráfego para um provedor.

**Como corrigir.** Preservar classification, source_ref, source_message_id, finalidade e lineage em toda instrução, resposta, observação, resumo e evento de notificação. Derivar a classificação efetiva das fontes utilizadas, sem permitir redução por valor padrão. Implementar migração e política conservadora para registros legados sem metadados; não reclassificar silenciosamente todo o passado como público/interno. Revalidar consentimento por provedor e finalidade imediatamente antes do transporte. Evitar resolver apenas elevando task.data_policy: isso não protege cópias que reaparecem em outra conversa. Quando necessário, bloquear ou pedir consentimento escopado; não descartar um trecho obrigatório e fingir que foi analisado.

**Aceite obrigatório.** Sem consentimento, nenhuma das três sentinelas pode chegar ao adaptador; o teste positivo de mensagem inicial deve continuar bloqueando. Com consentimento exato, somente os dados e a finalidade autorizados podem ser enviados. Repetir em correção ao vivo, retomada, outbox, resumo, troca de provedor, revogação e restauração. Incluir asserts sobre os bytes efetivamente entregues ao provedor, não só sobre o status de uma tabela.

### R5-02 — O pedido integral do proprietário é substituído pelo resumo produzido pelo modelo

**Prioridade:** P1  
**Rastreabilidade:** Contrato v2, capítulos 4, 5.1, 5.2 e 7.3; continuidade de A3-18.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [core/conversation.py:941–983](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/core/conversation.py#L941-L983); [core/conversation.py:1111–1132](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/core/conversation.py#L1111-L1132)

**O que foi observado.** Enviei um pedido com entrega até 15/11/2026, exclusão de contratos renováveis, limite de R$ 8.000 e impostos separados. O interpretador controlado devolveu o resumo “Compare fornecedores de módulos.”. A mensagem completa continuou no histórico, mas a instrução ORIGINAL da tarefa ficou só com o resumo. As restrições não chegaram ao registro operacional que o executor utiliza como pedido original.

**Causa.** _act_on_chat escolhe decision.objective; _delegate usa esse texto tanto em objective quanto em original_request e na derivação dos critérios. O campo original_request existe, mas recebe a interpretação do modelo, não a mensagem autenticada.

**Impacto.** O usuário dá instruções completas, mas o funcionário trabalha com uma versão que pode omitir prazo, orçamento, proibições e condições. O fato de o histórico conservar o original não corrige automaticamente o contexto da tarefa.

**Como corrigir.** Separar título/resumo interpretado de pedido canônico. Recuperar o texto integral pelo source_message_id autenticado e persistir sua versão e hash na publicação atômica da tarefa. Objetivo resumido serve para a interface, não para substituir a autoridade do pedido. Extrair requisitos e critérios do material integral e manter rastreabilidade para cada trecho; condições numéricas e exclusões não podem depender só do resumo. Garantir que anexos, instruções de diálogo pertinentes e correções tenham referências versionadas. Só omitir um trecho do contexto com cobertura/recuperação comprovada, nunca descartá-lo do estado canônico.

**Aceite obrigatório.** Usar resumos que omitam propositalmente data, teto, imposto, fornecedor excluído ou obrigação. A tarefa deve conservar todas as condições e o próximo contexto deve contê-las ou recuperá-las. O teste deve verificar texto, referências, critérios e efeito, sem aceitar coincidência na resposta do modelo. Conferir que uma delegação explícita e uma inferida preservam o mesmo pedido.

### R5-03 — Um pedido em interpretação ainda pode gerar trabalho novo depois de “pare tudo”

**Prioridade:** P1  
**Rastreabilidade:** A3-04; contrato v2, capítulos 5 e 6.2.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/tasks/engine.py:614–674](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/tasks/engine.py#L614-L674); [core/conversation.py:1111–1132](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/core/conversation.py#L1111-L1132); [core/conversation.py:941–983](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/core/conversation.py#L941-L983)

**O que foi observado.** Enquanto a interpretação de uma mensagem estava em andamento no provedor controlado, executei o stop_all real. O sistema incrementou control_epoch e não havia tarefa para pausar. A interpretação terminou depois e publicou uma nova tarefa. Sem outro pedido do usuário após a parada, o TaskEngine concedeu lease para essa tarefa e seu estado tornou-se RUNNING.

**Causa.** A parada atua nas tarefas já existentes. A época de controle é registrada, mas o caminho de interpretação/publicação não a vincula ao pedido original nem a compara antes de criar ou tornar elegível o trabalho.

**Impacto.** O usuário recebe a confirmação de parada, mas um trabalho originado antes desse comando pode começar depois dele. O novo socket de controle corrige a entrega do comando; não cobre sozinho a ordenação de todos os efeitos posteriores.

**Como corrigir.** Capturar control_epoch no recebimento durável de cada intenção executável. Na mesma transação que publica a tarefa, conferir se essa época ainda é autorizada; se mudou, manter a intenção suspensa/cancelada conforme a política e comunicar o estado. Revalidar também na aquisição do lease e no despacho. Definir claramente a semântica para pedidos autenticamente novos após a parada e para retomada explícita. Não obrigar um bloqueio eterno, mas impedir que respostas tardias antigas se passem por novos comandos. Propagar esse controle a interpretações, subtarefas e rotinas agendadas.

**Aceite obrigatório.** Intercalar stop entre recebimento→inferência, inferência→publicação, publicação→lease e lease→despacho. Em nenhum caso o pedido antigo pode iniciar novos efeitos após a parada aplicada. Uma nova delegação/retomada autorizada deve funcionar. Repetir com duas conexões reais e barreiras de sincronização; medir também o botão/atalho real no Mac.

### R5-04 — Uma decisão “finish” antiga ainda conclui a tarefa depois de uma correção material

**Prioridade:** P1  
**Rastreabilidade:** A3-03 e A3-07; contrato v2, capítulos 6.3 e 13.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/agent/loop.py:501–633](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/agent/loop.py#L501-L633); [runtime/agent/loop.py:735–756](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/agent/loop.py#L735-L756); [runtime/tasks/engine.py:544–612](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/tasks/engine.py#L544-L612); [runtime/verification/verifier.py:254–288](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/verification/verifier.py#L254-L288)

**O que foi observado.** Preparei uma entrega antiga sobre maçãs. Durante a chamada ao modelo, antes de devolver finish, apliquei uma instrução material para abandonar maçãs e tratar somente de bananas. A tarefa chegou à revisão de instrução 2 e, mesmo assim, terminou COMPLETED entregando o arquivo antigo sobre maçãs.

**Causa.** O broker verifica a revisão para ferramentas, o que é uma melhoria. Porém, o ramo finish não verifica novamente a revisão usada para produzir a decisão antes de verificar/concluir. A conclusão consulta a versão atual da tarefa para completar, sem provar que sua evidência cobre essa versão. Os critérios também podem continuar derivados do objetivo antigo.

**Impacto.** O sistema pode dizer “concluí conforme solicitado” mesmo após receber uma mudança que invalida o resultado. Corrigir apenas o despacho de ferramentas não protege a decisão de conclusão.

**Como corrigir.** Vincular decisão, plano, critérios, avaliação e evidências à instruction_revision. Material change deve invalidar os critérios/atestados afetados e replanejar a parte restante. Conferir a revisão após a inferência, antes de verificar e no commit final que move para COMPLETED; utilizar compare-and-set transacional e nunca atualizar a revisão esperada só para passar na validação. Aplicar a mesma disciplina a ask_owner e request_capability quando sua pertinência mudou. Reaproveitar resultados não afetados com vínculo explícito.

**Aceite obrigatório.** O teste de maçãs→bananas não pode concluir com a entrega anterior. Repetir com correção entre verificação e commit final, mudança de destinatário/teto e atualização de anexos. A evidência deve declarar exatamente a revisão avaliada. Uma alteração sem impacto nos critérios pode manter evidências, mas deve ter justificativa registrada.

### R5-05 — Verificação por palavras-chave e equações ainda aprova entregas erradas

**Prioridade:** P1  
**Rastreabilidade:** A3-07; contrato v2, capítulo 13.3.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/verification/criteria.py:37–94](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/verification/criteria.py#L37-L94); [runtime/verification/verifier.py:135–170](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/verification/verifier.py#L135-L170)

**O que foi observado.** O Verifier real aprovou um arquivo legível com palavras como fornecedores, preço e prazo que afirmava expressamente: “Não comparei nenhuma opção e não fiz recomendação. As condições solicitadas não foram verificadas.”. O resultado foi passed=true, sem gaps.

Também aprovou um orçamento em prosa com subtotal R$ 100, frete R$ 20 e total R$ 500. Como controle, a expressão explícita “100 + 20 = 500” foi rejeitada. A falha depende da representação e da cobertura semântica, não de ausência total de checagem aritmética.

**Causa.** coverage verifica a presença de aproximadamente metade dos radicais de palavras escolhidos do pedido. Isso não demonstra comparação, recomendação ou atendimento às restrições. calculations inspeciona equações em uma forma textual delimitada; totais em frases/tabelas podem passar sem verificação.

**Impacto.** O rótulo “entrega verificada” confere confiança indevida a documentos que não resolveram o pedido ou contêm contas erradas. A evidência por critério é útil, mas o conteúdo de cada verificador ainda precisa representar o critério real.

**Como corrigir.** Manter integridade como controle separado. Definir resultados tipados por tarefa (ex.: alternativas, valores com unidade/moeda, condições, exclusões, comparação e conclusão) com origem nos materiais e no pedido integral. Recalcular somas/taxas/percentuais por código e validar os valores estruturados que alimentaram texto, planilha e PDF. Para requisitos de conteúdo, usar critérios semânticos explícitos e revisão complementar, com incerteza/REQUIRES_REVIEW quando não houver prova suficiente; não fingir que outro LLM prova tudo. Não classificar ausência de conta reconhecida como conta conferida. Heurísticas de palavras podem ajudar triagem, mas não autorizar COMPLETED sozinhas. Não proibir apenas as frases exatas usadas no teste.

**Aceite obrigatório.** Relatórios irrelevantes com todas as palavras-chave, negações de conclusão, preço/prioridade invertidos, totais errados em prosa/tabela/planilha, impostos omitidos e referências inventadas devem falhar ou produzir parcial/revisão explícita. Relatórios corretos com paráfrases e sem as palavras literais devem passar. Conferir a mesma informação em todos os formatos gerados.

### R5-06 — Extração PARCIAL pode ser marcada como leitura completa e validar a entrega

**Prioridade:** P1  
**Rastreabilidade:** A3-09 e A3-10; contrato v2, capítulos 10 e 13.3.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/verification/verifier.py:216–240](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/verification/verifier.py#L216-L240)

**O que foi observado.** Preparei uma fixture no banco real com extração PARTIAL, um trecho disponível e aviso de página essencial não extraída. Marquei a leitura desse trecho disponível. O verificador aceitou a entrega como aprovada. Este teste injeta o resultado parcial da extração; não é a reprodução de um PDF real digitalizado nem valida o extrator de todos os formatos.

**Causa.** _inputs_read rejeita UNSUPPORTED e FAILED, mas não PARTIAL. A comparação considera o número de trechos produzidos contra trechos lidos; uma página que não foi extraída não entra nessa contagem.

**Impacto.** “Li todos os trechos extraídos” pode virar “li o documento inteiro”, embora uma cláusula decisiva tenha ficado ilegível. Isso afeta a confiança na análise documental.

**Como corrigir.** Separar cobertura de extração, cobertura de recuperação/leitura e adequação ao pedido. Persistir página/célula/seção esperada, extraída, ilegível ou faltante e avisos associados. PARTIAL exige tratamento: outra extração/visão autorizada, pedido de material legível ou escopo parcial explicitamente aceito. Não apagar avisos para passar; não reclassificar PARTIAL como falha total quando ainda é possível entregar uma análise parcial útil.

**Aceite obrigatório.** Fixture PARTIAL nunca deve passar como análise integral. Adicionar arquivo real sintético com página ilegível ou imagem e cláusula essencial; verificar a limitação no resultado e no estado. Se o proprietário autorizar escopo reduzido, registrar a revisão do escopo e a cobertura exata, sem afirmar que recuperou a página.

### R5-07 — Anexo enviado como resposta fica na conversa, mas não entra na tarefa

**Prioridade:** P2  
**Rastreabilidade:** A3-12, A3-14 e A3-15; contrato v2, capítulos 5.2 e 7.2.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [core/conversation.py:858–879](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/core/conversation.py#L858-L879)

**O que foi observado.** Uma tarefa aguardava documento. Importei um TXT fictício e respondi à pergunta por reply_to_message_id, enviando artifact_ids. A resposta foi aceita, a tarefa passou para READY e o anexo ficou ligado à mensagem. Porém, o número de vínculos de entrada da tarefa para esse arquivo permaneceu zero.

**Causa.** O caminho específico _answer altera tipo/vínculo da mensagem e retoma a tarefa, mas não transfere os anexos da resposta para artifact_links da tarefa. O tratamento de “anexar à tarefa” existe por outro caminho e não cobre essa combinação.

**Impacto.** O usuário fornece o documento solicitado e o funcionário pode continuar sem conseguir utilizá-lo, perguntar novamente ou produzir uma entrega incompleta.

**Como corrigir.** Unificar a operação de resposta: validar pergunta, tarefa, proprietário, revisão, anexos e classificação; vincular arquivos e resposta; atualizar instrução/critério/escopo quando necessário; só então disponibilizar a tarefa. Tudo em transação única ou estágio não executável. Não criar uma segunda tarefa para contornar o problema; não duplicar o arquivo se a resposta for reenviada.

**Aceite obrigatório.** Responder com um e vários arquivos, com texto e sem texto quando permitido; todos os vínculos devem existir antes de READY/lease. Verificar classificação, contexto, deduplicação, resposta fora de ordem e pergunta de outra tarefa. O worker deve efetivamente ler o novo arquivo.

### R5-08 — Validação de URL confunde cadastro de fonte com consulta autenticada da tarefa

**Prioridade:** P2  
**Rastreabilidade:** A3-07 e A3-26; contrato v2, capítulos 9, 13.3 e 16.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/verification/verifier.py:190–213](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/verification/verifier.py#L190-L213)

**O que foi observado.** Cadastrei uma fonte web fictícia, sem acesso HTTP, no escopo de outro empregado/proprietário. A validação _sources da tarefa atual aceitou essa URL. A fixture usa o método público de cadastro de fonte com employee_id do outro empregado. A aceitação foi observada no componente de validação de fontes; não implica vazamento nem navegação real.

**Causa.** A consulta procura apenas kind=web e ref=URL na tabela sources. Não exige employee_id, tarefa, recibo de recuperação, conteúdo/hash nem relação entre a fonte e a afirmação avaliada.

**Impacto.** Quando a navegação for acrescentada, um cadastro de URL poderá ser apresentado como evidência de que o Atlas consultou aquela fonte para aquele trabalho. O defeito existe mesmo sem tentar uma URL maliciosa.

**Como corrigir.** Criar relação de uso de fonte com owner/employee/task, URL final canônica, captura/versão, timestamp, hash e recibo do adaptador. Permitir reutilização legítima de fonte arquivada do mesmo escopo somente por acesso autorizado e registro explícito, com validade temporal. “Fonte cadastrada”, “fonte obtida”, “fonte consultada nesta tarefa” e “fonte sustenta esta afirmação” são estados diferentes. Cadastro textual isolado não é prova.

**Aceite obrigatório.** Rejeitar fonte de outro escopo, URL apenas cadastrada, consulta expirada para fato temporal e referência que não sustente a afirmação. Aceitar fonte realmente recuperada e vinculada, inclusive arquivo local autorizado de captura anterior, sem exigir nova busca desnecessária quando o dado for estável.

### R5-09 — Decisão sobre recurso pode persistir sem retomar o trabalho e sem reenvio recuperável

**Prioridade:** P2  
**Rastreabilidade:** N18; contrato v2, capítulos 5, 12.3 e 16.5.  
**Evidência:** reprodução controlada contra os módulos reais do pacote, nas condições descritas.

**Arquivos:** [runtime/capabilities/requests.py:86–140](https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/runtime/capabilities/requests.py#L86-L140)

**O que foi observado.** Criei um pedido de recurso sintético. Injetei falha depois de o status APPROVED ser gravado, antes da atualização da instrução. A solicitação ficou APPROVED, a tarefa WAITING_USER e a revisão da instrução não mudou. Repetir a decisão respondeu VERSION_CONFLICT: request already APPROVED. Não houve assinatura, compra ou gasto.

**Causa.** decide confirma o status numa transação e executa update_instruction e transition depois, em outras operações. O reenvio rejeita status não PENDING sem conciliar o trabalho faltante.

**Impacto.** Você aprova um recurso, mas o funcionário permanece parado; tentar novamente não resolve porque a decisão já está registrada. A interface pode informar aprovação sem completar o fluxo associado.

**Como corrigir.** Registrar decisão autenticada, envelope/hash, nova instrução, invalidações pertinentes, condição de retomada e outbox atomicamente. Quando envolver operação externa, usar saga/recibo recuperável em vez de prometer transação distribuída. Repetir a mesma decisão deve devolver recibo consistente ou concluir a etapa local faltante; alteração de conteúdo com a mesma chave é conflito. Não transformar aprovação do pedido de recurso em compra automática ou consentimento de dados.

**Aceite obrigatório.** Falhar antes/depois de cada commit e durante entrega; reiniciar serviços e reenviar a mesma decisão. Deve haver uma decisão, uma instrução aplicável e estado recuperável, sem nova compra. Testar também rejeição, expiração, alteração de preço/condições e cancelamento da tarefa.

## 7. Relação com os 32 achados antigos

Não é correto contar estes nove achados como nove erros obrigatoriamente novos nem como prova de que os 32 anteriores continuam intactos. Alguns reabrem a cobertura de achados antigos por rotas diferentes; outros decorrem das capacidades acrescentadas no PR. `docs/AUDIT_REMEDIATION.md` deve mostrar o caminho testado e seu limite, não apenas “corrigido” em nível amplo.

Privacidade inicial pode estar corrigida e privacidade das derivações ainda falhar. A parada pode chegar prontamente ao serviço e ainda permitir publicação tardia de trabalho. A correção pode impedir um clique antigo e não impedir uma conclusão antiga. A outbox pode não perder mensagens e ainda perder sua classificação. O verificador pode produzir evidência separada por critério e ainda usar um critério insuficiente. Essas combinações precisam de testes que cruzem componentes.

## 8. Aderência à visão completa

A própria matriz de capacidades do PR distingue Alpha de Beta/V1. O usuário pediu um funcionário persistente com computador, contas, arquivos e memória próprios — não somente um chatbot ou uma ferramenta de análise de documentos. Não reduzir o escopo geral aos exemplos de propostas, viagens ou calendário.

| Área contratada | Situação declarada no PR | O que precisa constituir evidência de entrega |
|---|---|---|
| N14 — workspace virtualizado e rede mediada | Não implementado | Boot em Mac compatível, isolamento de host/rede, arquivos próprios e ciclo de vida comprovados |
| N15 — Execution Box | Não implementado | Código experimental sem cofre, pastas pessoais, rede livre ou poderes administrativos |
| N16 — navegador, pesquisa, takeover | Não implementado | Pesquisa real, perfis separados, fontes recuperadas e controle humano exclusivo |
| N17 — contas e e-mail operacional | Não implementado | Conta dedicada autorizada, recuperação do proprietário, escopos, envio e recibos reais |
| N18 — pedido de recurso | Implementação local com R5-09 | Decisão recuperável, solicitação clara; aprovar recurso não compra nem autoriza divulgar dados |
| N19 — skills | Tabelas, sem ciclo completo | Teste, avaliação de permissões, promoção, versionamento e rollback demonstrados |
| N20 — voz | Não implementado | Fala/transcrição com mesma identidade e tarefas; distinguir parar fala de parar trabalho |
| N21 — companion remoto | Não implementado | Pareamento, criptografia ponta a ponta, fila offline, revogação e entrega real no celular |
| N22 — onboarding, privacidade, cifra e login item | Parcial/pendente | Instalação para leigo, controles reais, banco/arquivos protegidos e disponibilidade verdadeira |
| N23 — distribuição | Pacote ad-hoc e SBOM | Assinatura/notarização, instalação limpa, atualização e recuperação homologadas |
| N13 — inteligência real | Modelos simulados nos testes | Avaliações com conta e teto autorizados, amostras e custo medidos |

OCR/visão de documentos digitalizados/imagens e revisão visual dos arquivos gerados também permanecem pendentes segundo a matriz. Não expor uma função não implementada como se estivesse pronta. Não remediar a ausência da VM abrindo shell ou navegador pessoais.

A falta de Mac ou de credencial só bloqueia a homologação e operações que efetivamente dependem desse recurso. O implementador deve continuar o código e os testes não bloqueados e pedir ao proprietário apenas o recurso indispensável, sem exigir conhecimento de programação. Acesso externo ou gasto não está autorizado por este relatório.

## 9. Próxima entrega recomendada

**Rodada imediata:** R5-01, R5-02, R5-03 e R5-04, seguidos de R5-05/R5-06. Fazer R5-07/R5-08/R5-09 no mesmo ciclo de estabilização, respeitando dependências. Os nove precisam de teste que falha sob a propriedade correta antes do reparo e passa depois. Não remover guardas, inverter permissões, substituir por respostas fixas nem silenciar gaps.

**Depois:** rodar o cenário integrado com a interface de desenvolvimento no Mac, documentos sintéticos e modelo real somente após autorização de conta e orçamento. Preservar testes controlados para falhas difíceis. Publicar matriz distinguindo implementado, testado em componentes, integrado, usado interativamente e homologado com modelo real.

**Em paralelo, sem atalhos de segurança:** continuar os pacotes do contrato v2 ainda ausentes. O término deste relatório não substitui o contrato nem transforma a correção desses nove itens em conclusão da V1.

### Cenário mínimo integrado

1. Delegar por conversa natural um pedido com prazo, teto, exclusões e anexos; o estado canônico conserva tudo.
2. Responder à pergunta do Atlas enviando outro documento; ele fica vinculado à mesma tarefa antes da retomada.
3. Inserir correção sensível: sem consentimento de envio, o dado não chega à API, nem por notificação/resumo.
4. Corrigir a condição enquanto a resposta do modelo está pendente; a proposta e o finish anteriores não concluem a revisão nova.
5. Acionar “pare tudo” durante a interpretação inicial; nenhum trabalho antigo começa depois da confirmação.
6. Ler documento longo e documento com extração parcial; distinguir integral de parcial e não ocultar a página não analisada.
7. Entregar relatório com totais recalculados, condições verificadas e fontes vinculadas; documento errado não conclui.
8. Injetar falha na decisão de recurso, reiniciar e recuperar sem perder a decisão ou aprovar nova compra.
9. Abrir/salvar o resultado pelo mesmo bundle testado, com nome/extensão, fontes e limitações.

Esses passos são testes de mecanismos generalistas. Não hardcodar os exemplos nem seus textos no produto.

## 10. Fontes primárias e evidências

- PR e status: https://github.com/ViniciusMilanez82/atlas/pull/5
- Matriz declarada: https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/docs/CAPABILITY_MATRIX.md
- Remediação declarada: https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/docs/AUDIT_REMEDIATION.md
- Contrato vigente adotado: https://github.com/ViniciusMilanez82/atlas/blob/80f357b44663b190a4cacc8038accf27d0c11c13/docs/spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md
- Execução CI: https://github.com/ViniciusMilanez82/atlas/actions/runs/36128752671
- Job macOS e logs consultados: https://github.com/ViniciusMilanez82/atlas/actions/runs/36128752671/job/108050875369
- Artifact fonte: https://github.com/ViniciusMilanez82/atlas/actions/runs/36128752671/artifacts/10861445580
- Reprodução local: `repro/test_pr5_review.py`; resultados `repro/results.json` e `repro/run.log`.
- Verificação de origem: `evidencias/source_manifest.json`.

Os links por arquivo nos achados estão fixados no head revisado, com intervalos de código; não apontam silenciosamente para uma branch futura. As referências servem para localizar a implementação, enquanto os resultados locais demonstram o comportamento nas condições documentadas.

**Limite final:** revisão por amostragem dirigida a riscos, com execução parcial do núcleo Python. Não é auditoria integral de segurança, certificado de ausência de bugs, avaliação de todos os modelos ou homologação da aplicação macOS. O repositório não foi modificado durante esta revisão.
