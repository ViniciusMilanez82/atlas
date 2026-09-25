# ATLAS — Remediação da revisão independente do PR #5 (R5-01..R5-09)

Entrada: `docs/spec/review-pr5/` (revisão do head `80f357b`, merge `5a997e3`; hashes conferidos com
`SHA256SUMS.txt`). Branch de trabalho: `impl/review-pr5`. Atualizado em 2026-09-25.

## Etapa 0 — baseline e reprodução

- **HEAD de partida:** `5a997e3` (merge do PR #5), árvore limpa, sem commits posteriores do proprietário.
- **Baseline local (Windows, Python 3.14 do venv, sem Mac):** `scripts/check.py` verde — 627 passed,
  8 skipped antes deste trabalho. Swift/UI/pacote só no runner macOS do CI; VM e provedores reais não
  existem neste ambiente (D-01, D-03).
- **Script da revisão no código antigo** (`repro/test_pr5_review.py`, cópia fora do pacote; no Windows
  foi preciso `PYTHONUTF8=1` porque o script grava `.txt` com a codificação padrão do sistema):
  12 `DEFECT_REPRODUCED` + 2 `CONTROL_PASSED` — o mesmo resultado da revisão.
  Evidência: `docs/spec/review-pr5/repro/local_run_5a997e3.log` e `local_results_5a997e3.json`.
- `DEFECT_REPRODUCED` não é aprovação: cada achado ganhou regressões **na suíte real** que afirmam a
  propriedade correta. Cada arquivo foi executado contra o código antigo (worktree em `5a997e3`, só com os
  testes copiados) e contra o código novo.

## Quadro

Estados: **CORRIGIDO (componentes + integração local)**. Nenhum item tem validação no Mac (HW) nem com
modelo real (REAL) — ver pendências.

| ID | Prioridade | Estado | Causa confirmada | Regressão (falha antes → passa depois) | Commits | Evidência | Pendência |
|---|---|---|---|---|---|---|---|
| R5-01 | P1 | Corrigido | `TaskEngine.instructions` sem classe; `_owner_messages`/`_context` com INTERNAL por omissão; outbox inserindo mensagem sem classe; acks/status citando tarefas sensíveis como INTERNAL | `tests/regression/test_r5_01.py`: 8 falham antes, 10/10 passam | `b61fb3b`, `179ea89` | payload do provedor gravado; consentimento exato por finalidade, revogação | Resumo automático ainda não existe (nada a propagar); troca de provedor coberta pelo teto mínimo do catálogo; validar com modelo real (D-03) |
| R5-02 | P1 | Corrigido | `_delegate` gravava `decision.objective` (resumo do modelo) como `original_request` e derivava critérios dele | `test_r5_02.py`: 4 falham antes, 4/4 passam | `c793b1c` | texto, hash, `source_message_id`, condições por trecho, contexto seguinte e verificador | Extração de condições é determinística e conservadora: condições não reconhecidas continuam só no texto ORIGINAL (sempre enviado) |
| R5-03 | P1 | Corrigido | época de controle não era capturada no recebimento nem comparada na publicação/lease/despacho | `test_r5_03.py`: 6 falham antes (lease→despacho já protegido pelo fencing), 7/7 passam | `1b40dea` | 4 intercalações, subtarefa, reinício, duas conexões IPC reais | Botão/atalho real no Mac (D-01); ADR-017 |
| R5-04 | P1 | Corrigido | ramo `finish` sem revalidar a revisão; `complete` buscava a versão atual para passar; critérios e evidências sem revisão | `test_r5_04.py`: 6 falham antes, 6/6 passam | `5a0b657` | decisão descartada após correção; CAS na conclusão; evidência e outbox com a mesma revisão; teto/anexo reabrem critérios | Reaproveitamento seletivo de evidência por critério não afetado (hoje: toda mudança material reabre tudo; nota não material mantém com justificativa) |
| R5-05 | P1 | Corrigido | cobertura por metade das palavras; conta só na forma `a op b = c` | `test_r5_05.py`: 8 falham antes, 9/9 passam (1 controle já passava) | `d3ff3ce` | negação do trabalho, estrutura esperada, totais em prosa/tabela/planilha, critério invertido, item omitido, referência inventada, opção excluída, paráfrase correta aceita | Julgamento semântico amplo não é provável por código: o que não é verificável aparece como limitação, não como selo; revisão complementar por modelo não foi adotada como prova |
| R5-06 | P1 | Corrigido | `_inputs_read` não tratava PARTIAL; página não extraída fora da contagem | `test_r5_06.py`: 4 falham antes, 5/5 passam (controle de leitura longa já passava) | `d3ff3ce` | PDF real sintético com página só-imagem; áreas ausentes no estado, no aviso e no verificador; escopo reduzido explícito | OCR/visão (N08/N16) continua pendente; botão de "aceitar escopo reduzido" no app (API/IPC prontos) |
| R5-07 | P2 | Corrigido | `_answer` não transferia anexos para `artifact_links` da tarefa; `_attach_to_task` em dois commits | `test_r5_07.py`: 6 falham antes, 6/6 passam | `b81c59d` | vínculo + revisão + READY num commit; idempotência; outra tarefa recusada; worker lê o arquivo | Jornada no app com clipe real (D-01) |
| R5-08 | P2 | Corrigido | `_sources` aceitava qualquer `sources.kind='web'` global | `test_r5_08.py`: 6 falham antes, 6/6 passam | `94b9e0c`, `c47c465` | escopo por tarefa/empregado, reutilização autorizada, validade, captura que sustenta a afirmação | O adaptador de pesquisa real (N16) ainda não existe: hoje nenhuma URL é aceita como fonte, o que é o comportamento correto |
| R5-09 | P2 | Corrigido | `decide` gravava o status numa transação e instrução/estado em outras; reenvio recusava por "already APPROVED" | `test_r5_09.py`: 7 falham antes, 8/8 passam | `a42ea4c` | falha injetada após cada escrita, no commit, reinício, reenvio, rejeição, expiração, novas condições, cancelamento; nada comprado | Operações externas de contratação seguem inexistentes e exigirão aprovação material própria |

## Evidência de CI

Execução `36156008899` no commit `b3ec253` (todas as correções R5 + docs): **core-linux** 692 passed,
4 skipped; **core-macos** 695 passed, 1 skipped (o ignorado é a chamada opt-in ao provedor real, D-03);
**app-evidence** Swift 37 testes, 0 falhas, bundle construído. ruff, segredos e mypy verdes. Local
(Windows): 688 passed, 8 skipped (os extras dependem de Unix sockets/macOS e rodam no CI).

## Script da revisão depois das correções

`docs/spec/review-pr5/repro/local_run_after_fixes.log`: nenhum dos 12 cenários defeituosos reproduz
mais (os asserts do script afirmam o comportamento antigo e agora falham). Leitura dos resultados:

- `sensitive_correction` / `sensitive_answer`: `RequiredContextWithheld` antes de qualquer envio — correto.
- `stop_during_interpretation`: "task in PAUSED cannot be leased" — correto.
- `partial_coverage`: erro do harness (o `INSERT` posicional não conhece as colunas novas de
  `document_extractions`); a propriedade é provada por `test_r5_06.py::test_reviewer_fixture_partial_never_passes_as_complete`.
- Controle `positive_sensitive_original_blocked`: continua passando.
- Controle `positive_long_reading`: a leitura longa continua funcionando (cobertura completa em 32
  passos, sem acumular passos sem progresso), mas a entrega do script — "Comparação de fornecedores"
  sem nenhuma opção comparada — agora é recusada pelo R5-05. O controle equivalente na suíte
  (`test_r5_06.py::test_positive_control_long_reading_completes`) usa uma comparação real e conclui.

## Relação com os 32 achados A3

Os A3 abaixo tinham a rota original corrigida, mas outra rota da mesma classe foi reaberta pela revisão.
`docs/AUDIT_REMEDIATION.md` agora registra isso por linha; "32 corrigidos" significa "32 rotas
reproduzidas e corrigidas", não "32 classes encerradas".

| A3 | Rota corrigida no PR #5 | Rota reaberta | Remediação |
|---|---|---|---|
| A3-02 | mensagem inicial, memória, anexo | correção, resposta, outbox, eco/ack, legado | R5-01 |
| A3-03 | proposta de ferramenta obsoleta | `finish` obsoleto, correção entre verificação e commit | R5-04 |
| A3-04 | canal de parada próprio | interpretação em andamento publicando depois do STOP | R5-03 |
| A3-07 | fontes inventadas, conta `a op b = c` | negação do trabalho, total em prosa/tabela/planilha, critério invertido, fonte de outro escopo | R5-05, R5-08 |
| A3-09/A3-10 | decodificação por formato, leitura paginada | extração PARCIAL tratada como leitura integral | R5-06 |
| A3-12/14/15 | publicação atômica, alvo explícito da resposta | anexo enviado como resposta fora da tarefa | R5-07 |
| A3-18 | itens obrigatórios no contexto | pedido integral substituído pelo resumo | R5-02 |
| A3-26 | memória de outro empregado | fonte web de outro empregado | R5-08 |

## Migrações novas

`0020` classificação/origem em instruções, outbox e mensagens (legado nunca rebaixado); `0021` hash do
pedido canônico e critérios `condition`/`substance`; `0022` época de controle em recibos e tarefas;
`0023` evidência com revisão e critérios substituídos; `0024` áreas ausentes da extração e aceite de
escopo reduzido; `0025` recuperações de fonte e reutilização autorizada; `0026` decisão de recurso com
hash e estados EXPIRED/SUPERSEDED/CANCELLED. Nenhuma migração aplicada foi editada.

## Pendências materiais (não resolvidas por código neste ambiente)

- **D-01 — Mac:** jornada interativa com o mesmo bundle (conversar, anexar como resposta, corrigir durante
  o trabalho, parar durante a interpretação, abrir/salvar, recuperar falhas). Nada aqui é homologação macOS.
- **D-03 — modelo real:** nenhuma medição com provedor real; custo zero dos testes locais não estima produção.
- A UI ainda não expõe "aceitar escopo reduzido" (R5-06) nem "autorizar reutilizar captura" (R5-08);
  as APIs existem e têm regressão.
