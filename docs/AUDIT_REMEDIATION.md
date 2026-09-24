# ATLAS — Remediação dos achados A3-01..A3-32 (contrato v2, Anexo A)

Classificação da triagem no HEAD `d81cece` (cap. 25.2): **REPRODUZIDO** (um teste executado no código
real demonstrou a falha antes da correção), **CONFIRMADO ESTÁTICO** (inspeção rastreável, sem execução),
**CORRIGIDO PREVIAMENTE**, **RISCO CONDICIONAL** ou **NÃO CONFIRMADO**.

Estado da correção: **ABERTO**, **CORRIGIDO** (com regressão verde no commit indicado) ou
**PARCIAL** (parte Python feita; parte que exige Mac/UI pendente, com causa). Cada linha aponta o teste
de regressão. "Mac" = só validável no runner macOS/no Mac real.

| ID | Triagem no HEAD (evidência) | Estado | Regressão / commit |
| --- | --- | --- | --- |
| A3-01 | CONFIRMADO ESTÁTICO: `core/conversation.py::_chat` lê só `history(..., 20)`; não chama `MemoryManager.search` | ABERTO | `tests/regression/test_a3_01.py` |
| A3-02 | CONFIRMADO ESTÁTICO: `MemoryHit` sem sensibilidade; `loop.py::_context` cria `ContextItem` com classificação padrão INTERNAL; `_chat` usa `data_classification="INTERNAL"` | ABERTO | `tests/regression/test_a3_02.py` |
| A3-03 | CONFIRMADO ESTÁTICO: correção vira mensagem; `loop.py::run` só lê mensagens em `_resume_state` | ABERTO | `tests/regression/test_a3_03.py` |
| A3-04 | CONFIRMADO ESTÁTICO: `AtlasViewModel.stopAll` chama `send("pare tudo")`, que retorna se `isSending`; `AtlasConnection` usa uma única fila serial | ABERTO | `tests/regression/test_a3_04.py` + Swift |
| A3-05 | CONFIRMADO ESTÁTICO: `DEFAULT_LEASE_TTL=60s`, heartbeat só entre passos, `ModelRequest.timeout_s=60`; worker só seleciona CREATED/READY | ABERTO | `tests/regression/test_a3_05.py` |
| A3-06 | CONFIRMADO ESTÁTICO: `_decide` valida só objeto+enum; `decision.get("summary", "")[:300]` quebra com `null`; worker captura só `AtlasError` | ABERTO | `tests/regression/test_a3_06.py` |
| A3-07 | CONFIRMADO ESTÁTICO: `daemon.worker` usa `min_chars=200` e `min_sources=nº de anexos`; `_complete` satisfaz todos os critérios com uma evidência | ABERTO | `tests/regression/test_a3_07.py` |
| A3-08 | CONFIRMADO ESTÁTICO: `PLACEHOLDERS` com `(?i)\bTODO\b` | ABERTO | `tests/regression/test_a3_08.py` |
| A3-09 | CONFIRMADO ESTÁTICO: `builtin.read_text` faz `decode("utf-8", errors="replace")` de PDF/Office | ABERTO | `tests/regression/test_a3_09.py` |
| A3-10 | CONFIRMADO ESTÁTICO: `text[:200_000]` e `json.dumps(output)[:20_000]` | ABERTO | `tests/regression/test_a3_10.py` |
| A3-11 | CONFIRMADO ESTÁTICO: `handle` grava a mensagem e depois processa; reenvio devolve `duplicate` com `reply=None` | ABERTO | `tests/regression/test_a3_11.py` |
| A3-12 | CONFIRMADO ESTÁTICO: `TaskEngine.create` confirma CREATED; vínculos de anexos em outra transação | ABERTO | `tests/regression/test_a3_12.py` |
| A3-13 | CONFIRMADO ESTÁTICO: `_STATUS` aceita "como esta o tempo"; `_MEMORY` aceita prefixo "lembre" de "lembrete" | ABERTO | `tests/regression/test_a3_13.py` |
| A3-14 | CONFIRMADO ESTÁTICO: `_pending_question` com uma pergunta pendente captura qualquer mensagem | ABERTO | `tests/regression/test_a3_14.py` |
| A3-15 | CONFIRMADO ESTÁTICO: `deliver` envia `delegate || !ids.isEmpty` | ABERTO | `tests/regression/test_a3_15.py` + Swift |
| A3-16 | CONFIRMADO ESTÁTICO: `MemoryManager.correct` insere versão sem `valid_from/valid_until` | ABERTO | `tests/regression/test_a3_16.py` |
| A3-17 | CONFIRMADO ESTÁTICO: `delete` limpa versões/FTS, mas mensagens e observações mantêm o texto | ABERTO | `tests/regression/test_a3_17.py` |
| A3-18 | CONFIRMADO ESTÁTICO: `ContextBuilder.build` guloso por autoridade/ordem; mensagem atual pode cair em `dropped`; respostas do modelo viram `VERIFIED_FACT` em `_chat` | ABERTO | `tests/regression/test_a3_18.py` |
| A3-19 | CONFIRMADO ESTÁTICO: `BudgetLimits` é snapshot em `BudgetManager`; clientes criados antes não releem settings | ABERTO | `tests/regression/test_a3_19.py` |
| A3-20 | CONFIRMADO ESTÁTICO: `urlopen` segue redirects com `Authorization`; `startswith("http://127.0.0.1")` | ABERTO | `tests/regression/test_a3_20.py` |
| A3-21 | CONFIRMADO ESTÁTICO: `onDrop` cria uma Task por arquivo; `attach` retorna se `isAttaching` | ABERTO | Swift (Mac) |
| A3-22 | CONFIRMADO ESTÁTICO: `failedDraft` sem anexos/replyTo; importação sem recibo consultável | ABERTO | `tests/regression/test_a3_22.py` + Swift |
| A3-23 | CONFIRMADO ESTÁTICO: `merge` só acrescenta IDs novos; `refresh` lê só a última página | ABERTO | `tests/regression/test_a3_23.py` + Swift |
| A3-24 | CONFIRMADO ESTÁTICO: `_uploads_lock` por instância de `CoreService`; sem TTL/quota agregada | ABERTO | `tests/regression/test_a3_24.py` |
| A3-25 | CONFIRMADO ESTÁTICO: `_read` chama `read_bytes` (arquivo inteiro + hash) por chunk | ABERTO | `tests/regression/test_a3_25.py` |
| A3-26 | CONFIRMADO ESTÁTICO: delegação por `reply_to_message_id` não confere conversa/empregado; `_mem_correct` não liga memória à sessão | ABERTO | `tests/regression/test_a3_26.py` |
| A3-27 | CONFIRMADO ESTÁTICO: estado muda antes de `notify`; `_tell_owner` engole exceções | ABERTO | `tests/regression/test_a3_27.py` |
| A3-28 | CONFIRMADO ESTÁTICO: sem trava interprocesso; `UnixSocketServer` apaga o socket existente | ABERTO | `tests/regression/test_a3_28.py` + Swift |
| A3-29 | CONFIRMADO ESTÁTICO: `status()` procura validação só por `provider/model_id` | ABERTO | `tests/regression/test_a3_29.py` |
| A3-30 | CONFIRMADO ESTÁTICO: `TaskRow` mostra Pausar/Retomar/Cancelar sempre; `resume` só aceita PAUSED | ABERTO | `tests/regression/test_a3_30.py` + Swift |
| A3-31 | CONFIRMADO ESTÁTICO: `AppController.shutdown` (MainActor) → `Supervisor.stop` → `waitUntilExit` sem prazo | ABERTO | Swift (Mac) |
| A3-32 | CONFIRMADO ESTÁTICO: `NSSavePanel.nameFieldStringValue = "entrega"` | ABERTO | Swift (Mac) |

Os testes de regressão registram a reprodução (execução contra o código anterior) na mensagem do commit
que os introduz e em `docs/PROGRESS.md`.
