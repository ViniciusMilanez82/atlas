# ATLAS — Remediação dos achados A3-01..A3-32 (contrato v2, Anexo A)

Baseline: `d81cece` (Alpha 2). Branch: `impl/contract-v2`. Atualizado em 2026-09-24.

**Triagem no HEAD** (cap. 25.2): todos os 32 foram primeiro **CONFIRMADOS ESTATICAMENTE** no código real
(arquivo/função citados no Anexo A) e depois **REPRODUZIDOS** por um teste executado contra o código
anterior à correção, salvo onde indicado. Nenhum estava corrigido previamente.

**Níveis de evidência** (cap. 27.2): IMP = implementado; UNIT = teste unitário; INT = integração com classes
reais, SQLite e IPC real (socketpair/UDS); E2E-CI = daemon real ou processos reais no runner; MAC-CI = Swift
compilado e testado no runner macOS 15 (sem pessoa usando a interface); HW = Mac do proprietário (D-01);
REAL = provedor real (D-03). Nenhum item tem HW ou REAL ainda.

| ID | Reprodução antes da correção | Correção (commit) | Regressão | Evidência |
| --- | --- | --- | --- | --- |
| A3-01 | Após 120 mensagens e reinício, "Como se chama o meu cão?" foi ao modelo sem a memória confirmada | `c07c654` KnowledgeContextService comum a conversa e tarefas | `tests/regression/test_a3_01.py` | IMP, INT |
| A3-02 | Sentinelas SENSITIVE (memória, anexo, eco da conversa) chegaram ao payload do modelo | `9a79555` classificação até o payload + Egress Guard por provedor/finalidade | `test_a3_02.py` | IMP, INT |
| A3-03 | Relatório "por preço" foi despachado após a correção "priorize prazo" (2 escritas) | `d2fad8f` revisões de instrução; broker recusa proposta obsoleta | `test_a3_03.py` | IMP, INT |
| A3-04 | `stopAll()` → `send()` ignorado com `isSending`; fila única | `d2fad8f` `control.stop` + conexão de controle própria no app | `test_a3_04.py` + `A304RegressionTests.swift` | IMP, INT, MAC-CI (VM com transporte falso); botão real: HW pendente |
| A3-05 | Chamada de 3×TTL deixou lease vencido e tarefa RUNNING sem heartbeat | `f2a925a` LeaseKeeper + Watchdog + agenda fora do worker | `test_a3_05.py` | IMP, INT |
| A3-06 | `summary` null/int/list: TypeError derrubou o `run`; chat malformado virou "chat" | `85953ce`, `bc30c23` validação do schema completo; worker supervisionado; saúde honesta | `test_a3_06.py` | IMP, INT, E2E-CI (daemon) |
| A3-07 | Receita de bolo com fontes inventadas e conta errada PASSOU no verificador | `024d892` critérios derivados do pedido, evidência por critério | `test_a3_07_08.py` | IMP, INT |
| A3-08 | `(?i)\bTODO\b` marcava "Todo o trabalho foi concluído" | `024d892` marcadores explícitos apenas | `test_a3_07_08.py` | IMP, UNIT |
| A3-09 | DOCX decodificado como UTF-8: 14 169 caracteres de substituição, valor da tabela ausente | `7aa1c24` extratores por formato (ADR-016) | `test_a3_09_10.py` | IMP, INT; bundle com dependências gerado no CI |
| A3-10 | `text[:200_000]` e `json.dumps(...)[:20_000]` (estático) + T13 | `7aa1c24` leitura paginada com cobertura; JSON nunca cortado | `test_a3_09_10.py` | IMP, INT |
| A3-11 | Queda antes da resposta → reenvio devolvia `duplicate` com `reply=None` para sempre | `916cefe` `request_receipts` com retomada idempotente | `test_a3_11.py` | IMP, INT |
| A3-12 | Worker via tarefa CREATED com 0 de 3 anexos logo após o commit | `64e9575` publicação atômica | `test_a3_12.py` | IMP, INT |
| A3-13 | "Como está o tempo no Rio?" → status; "Lembrete:" → memória "te: ..." | `c62e191` STATUS exige referência a trabalho; MEMORY no texto original | `test_a3_13_14_15.py` | IMP, INT |
| A3-14 | Status e assunto novo consumidos como resposta à pergunta pendente | `c62e191` alvo explícito; inferência só inequívoca; ambiguidade pergunta qual | `test_a3_13_14_15.py` + `G3RegressionTests` | IMP, INT, MAC-CI (VM) |
| A3-15 | App enviava `delegate || !ids.isEmpty` | `c62e191`, `8a6a5a4` guardar / anexar à tarefa / analisar distintos | `test_a3_13_14_15.py` + `G3RegressionTests` | IMP, INT, MAC-CI (VM) |
| A3-16 | Memória expirada voltou a aparecer após correção só do texto | `4d6ba74` janela preservada salvo mudança explícita | `test_a3_16_17.py` | IMP, INT |
| A3-17 | Após `memories.delete`, sentinela ainda foi ao modelo pelo histórico | `4d6ba74` apagar/parar de usar, tombstones reaplicados no restore | `test_a3_16_17.py` | IMP, INT |
| A3-18 | Correção de 4 KB descartada em histórico saturado; resposta antiga como VERIFIED FACT | `7b0b3bd` itens obrigatórios reservados; histórico como não verificado | `test_a3_18.py` | IMP, INT |
| A3-19 | Cliente criado antes da redução do teto continuou gastando | `bb9f142` orçamento vigente lido em cada reserva | `test_a3_19.py` | IMP, INT |
| A3-20 | 301/302/303/307/308 seguidos para outra origem | `dd42d2b` sem redirects; loopback exato só em modo de teste; allowlist | `test_a3_20.py` | IMP, INT |
| A3-21 | `attach` retornava em silêncio com `isAttaching` | `8a6a5a4` fila por arquivo com resultado explícito | `G3RegressionTests.testTenDroppedFiles...` | IMP, MAC-CI (VM); arrastar real: HW pendente |
| A3-22 | Reenvio recalculava anexos; importação sem recibo ("upload not found") | `fc5707c` (core), `8a6a5a4` (app) envelope imutável + recibo de importação | `test_a3_24.py` + `G3RegressionTests` | IMP, INT, MAC-CI (VM) |
| A3-23 | `merge` só acrescentava; `refresh` só lia 50 | `5db4aa3` (core), `8a6a5a4` (app) sequência/revisão, upsert, sem lacunas | `test_a3_23_30.py` + `G3RegressionTests` | IMP, INT, MAC-CI (VM) |
| A3-24 | Mesmo trecho por duas conexões gravado duas vezes | `fc5707c` `upload_sessions` transacional, cota, TTL, varredura | `test_a3_24.py` | IMP, INT |
| A3-25 | 10 MiB em 20 trechos = 200 MiB lidos+hash (20×) | `fc5707c` verificação única fixada por (tamanho, mtime, inode) | `test_a3_25.py` (1/10/50 MiB ≤ 2×) | IMP, INT |
| A3-26 | Proprietário A corrigiu memória do empregado B | `5b9a3e6` verificação central por objeto (14 chamadas cruzadas) | `test_a3_26.py` | IMP, INT |
| A3-27 | Com falha de entrega, tarefa em WAITING_USER e pergunta perdida | `1d164d3` outbox na mesma transação + dispatcher | `test_a3_27.py` | IMP, INT |
| A3-28 | Sem trava; servidor apagava socket existente | `9bc5e5b` trava no daemon e no Supervisor | `test_a3_28.py` + `SupervisorTests.testSecondSupervisorDoesNotTakeOver` | IMP, INT, E2E-CI, MAC-CI (processos reais) |
| A3-29 | Duas chaves ativas; validação só por provider/modelo | `bb9f142` validação presa a credencial/endpoint/modelo/capacidade | `test_a3_29.py` | IMP, INT |
| A3-30 | Pausar/Retomar/Cancelar sempre visíveis; BLOCKED sem caminho | `5db4aa3`, `8a6a5a4` `available_actions` + `tasks.reevaluate` | `test_a3_23_30.py` + `G3RegressionTests` | IMP, INT, MAC-CI (VM) |
| A3-31 | `waitUntilExit` sem prazo no MainActor | `9bc5e5b` parada com prazo fora do MainActor, relatório do que foi forçado | `SupervisorTests.testStopIsBoundedWhenAServiceIgnoresTerm` | IMP, MAC-CI (processos reais); saída do app: HW pendente |
| A3-32 | Salvar como começava com "entrega" | `8a6a5a4` nome/extensão reais e tipo fixo | `G3RegressionTests.testSuggestedFileName...` | IMP, MAC-CI (VM); painel real: HW pendente |

## Achados novos durante a implementação

| ID | Descrição | Correção |
| --- | --- | --- |
| B-01 | `run_in_process` fazia `join` antes de ler a fila: resultado grande bloqueava o filho, que era morto no prazo | `7aa1c24` lê primeiro, depois `join` |
| B-02 | Registrar uma segunda chave deixava duas referências ativas e a inteligência dizia "no API credential registered" | `bb9f142` a nova chave revoga a anterior do mesmo endpoint |
| B-03 | E2E do daemon no macOS: saúde consultada antes da primeira volta do worker | `bc30c23` estado `starting` explícito |
| B-04 | Teste A3-03 citava documento não lido; o verificador novo recusou corretamente | `024d892` roteiro do teste lê os dois documentos |

## O que ainda depende de recurso externo

- **D-01 (Mac do proprietário / pessoa usando o app):** botões, arrastar arquivos, painel Salvar como e
  saída do app foram testados no nível do ViewModel e compilados no runner; falta a jornada interativa.
- **D-03 (conta e teto de API autorizados):** nenhum comportamento com modelo real foi medido.
