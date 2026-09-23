# ATLAS — Backlog executável

Derivado da spec capítulo 19 e dos marcos do capítulo 18. Cada item é pequeno e revisável.
**Host** indica onde pode ser executado: `any` (qualquer SO com Python), `mac` (Mac real),
`mac+cred` (Mac e credencial do proprietário).

Estados: `FEITO` (testes executados e aprovados), `EM CURSO`, `A FAZER`, `BLOQUEADO (D-xx)`.

## M0 — Fundação

| ID | Tarefa | Depende | Host | Aceite | Estado |
| --- | --- | --- | --- | --- | --- |
| AT-001.1 | Repositório, árvore da spec, `.gitignore`, `pyproject`, venv fora do OneDrive | — | any | checkout limpo roda a suíte | FEITO |
| AT-001.2 | Spec preservada byte a byte + SHA256SUMS + teste de integridade | 001.1 | any | teste de hash passa | FEITO |
| AT-001.3 | `scripts/check.py` e `scripts/scan_secrets.py` | 001.1 | any | scanner acha chave plantada; repositório limpo | FEITO |
| AT-001.4 | Documentos obrigatórios, ADR-001..012, backlog, dependências | 001.1 | any | teste de docs passa | FEITO |
| AT-001.5 | Lockfile de dependências e registro de licenças | 001.1 | any | `requirements-dev.lock` + `THIRD_PARTY_LICENSES.md` | FEITO |
| AT-001.6 | Workflow de CI (Linux: núcleo Python; macOS: marcado) | 001.3 | any | YAML válido; execução depende de D-10 | FEITO (não executado: sem remoto) |
| AT-002.1 | Schemas: common, Task, ActionProposal, ToolResult, Approval, JournalEvent, IPC, config | 001.1 | any | fixtures válidas passam; extras, enums e dinheiro sem moeda falham | FEITO |
| AT-002.2 | Primitivas: JSON canônico, Money por moeda, relógio UTC, IDs, erros normalizados | 002.1 | any | testes unitários | FEITO |

## M2 — Dados e chaves

| ID | Tarefa | Depende | Host | Aceite | Estado |
| --- | --- | --- | --- | --- | --- |
| AT-005.1 | Conexão SQLite (WAL, FK, busy_timeout) e executor de migrações versionadas | M0 | any | migração idempotente; versão registrada | FEITO |
| AT-005.2 | Schema relacional inicial (spec 13.2) com FKs e CHECKs | 005.1 | any | ação sem tarefa, aprovação sem ação e entrega sem artefato falham | FEITO |
| AT-005.3 | Journal de eventos com `sequence_id` monotônico e validação de schema | 005.2 | any | eventos retomáveis por sequence_id | FEITO |
| AT-005.4 | Teste de interrupção antes/depois do commit | 005.2 | any | nenhum estado inválido | FEITO |
| AT-005.5 | Backup consistente + manifesto + restore com verificação e revogação de autorizações | 005.2 | any | hash/versão conferidos; aprovações revogadas | FEITO |
| AT-006.1 | `CredentialRef`, interface `VaultBackend`, uso escopado por finalidade/destino | 005.2 | any | ferramenta genérica não obtém segredo | FEITO |
| AT-006.2 | Filtro de redação para logs e eventos | 006.1 | any | segredo nunca aparece em log | FEITO |
| AT-006.3 | Backend Keychain via Supervisor Swift | 006.1 | mac | teste com Keychain real | BLOQUEADO (D-01) |
| AT-005.6 | Criptografia do banco (SQLCipher ou equivalente) | 005.5 | mac | restore cifrado; chave no Keychain | BLOQUEADO (D-01, D-09) |

## M3 — Autoridade

| ID | Tarefa | Depende | Host | Aceite | Estado |
| --- | --- | --- | --- | --- | --- |
| AT-007.1 | Tool Registry confiável (manifesto, classe de efeito, desabilitado por padrão) | M2 | any | ferramenta sem registro/desabilitada não roda | FEITO |
| AT-007.2 | Policy Engine R0–R5, capacidades, dados sensíveis, mandatos, fail-closed | 007.1 | any | DENY domina; erro nega; versão auditada | FEITO |
| AT-008.1 | Approval Engine: hash canônico, nonce, validade, usos, reserva/consumo atômicos, revogação | 007.2 | any | mudança material invalida; replay e corrida não repetem | FEITO |
| AT-008.2 | Mandatos recorrentes limitados | 008.1 | any | mandato não cobre R5 nem fora do escopo | FEITO |
| AT-012.1 | Orçamento: tetos por tarefa e período, reservas concorrentes, alertas 70/90 | M2 | any | concorrência respeita teto; sem teto = bloqueado | FEITO |
| AT-017.1 | Action Ledger (PROPOSED..UNKNOWN) | 005.2 | any | intenção persistida antes do despacho | FEITO |
| AT-017.2 | Broker de despacho: schema, registro, lease/fencing, política, aprovação, orçamento, ledger em 1 transação | 007.2, 008.1, 012.1, 017.1, 010.1 | any | worker obsoleto recusado; injeção não amplia | FEITO |

## M5 — Task Engine

| ID | Tarefa | Depende | Host | Aceite | Estado |
| --- | --- | --- | --- | --- | --- |
| AT-010.1 | Máquina de estados da spec 9.2 com versão otimista | 005.2 | any | transições inválidas falham | FEITO |
| AT-010.2 | Leases com expiração, heartbeat e fencing token | 010.1 | any | worker antigo perde despacho | FEITO |
| AT-010.3 | Pausa, retomada, cancelamento e "pare tudo" | 010.2 | any | parada < 2 s no teste local | FEITO |
| AT-010.4 | Recuperação pós-reinício (leases, DISPATCHING→UNKNOWN, reavaliação) | 010.2, 017.1 | any | sem repetição cega | FEITO |
| AT-010.5 | Checkpoints e limites de tentativa (3 transitórias, 2 replanejamentos, 20 passos) | 010.1 | any | loops param | A FAZER |
| AT-010.6 | Jobs agendados com fuso IANA e política de execuções perdidas | 010.1 | any | ocorrências perdidas consolidadas | A FAZER |

## M6 em diante (resumo; detalhar ao iniciar cada marco)

| ID | Tarefa | Host | Estado |
| --- | --- | --- | --- |
| AT-011 | Adaptador OpenAI (catálogo, health, streaming, resposta normalizada) | any + D-03 para chamada real | A FAZER |
| AT-012.2 | Router por capacidade/privacidade/orçamento; modos simples | any | A FAZER |
| AT-013 | Memória: camadas, proveniência, FTS5, correção versionada, exclusão | any | A FAZER |
| AT-014 | Registry de ferramentas + Artifact Broker (any) e Execution Box (mac) | any / mac | A FAZER |
| AT-015 | Playwright no guest, perfis, takeover | mac | BLOQUEADO (D-01) |
| AT-016 | Planner e Verifier | any + D-03 | A FAZER |
| AT-018 | Voz e canal remoto | mac + D-05/D-06/D-11 | BLOQUEADO |
| AT-019 | Skills, atualização assinada, rollback | mac + D-07 | BLOQUEADO |
| AT-020 | Release e aceitação | mac + D-07 | BLOQUEADO |
| AT-003/004 | Provas de VM, tela, rede e sentinelas de host | mac | BLOQUEADO (D-01) |
| AT-009 | App SwiftUI, onboarding, chat, diagnóstico | mac | BLOQUEADO (D-01) |
