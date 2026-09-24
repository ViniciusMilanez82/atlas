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
| AT-001.6 | Workflow de CI (Linux: núcleo Python; macOS: marcado) | 001.3 | any | YAML válido; execução depende de D-10 | FEITO (CI verde em Linux e macOS) |
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
| AT-006.3 | Backend Keychain via Supervisor Swift | 006.1 | mac | teste com Keychain real | FEITO no runner macOS; ciclo de vida do Supervisor no Mac do proprietário: D-01 |
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
| AT-010.5 | Checkpoints e limites de tentativa (3 transitórias, 2 replanejamentos, 20 passos) | 010.1 | any | loops param | FEITO |
| AT-010.6 | Jobs agendados com fuso IANA e política de execuções perdidas | 010.1 | any | ocorrências perdidas consolidadas | FEITO |

## M6 em diante (resumo; detalhar ao iniciar cada marco)

| ID | Tarefa | Host | Estado |
| --- | --- | --- | --- |
| AT-011 | Adaptador OpenAI (catálogo, health, streaming, resposta normalizada) | any + D-03 para chamada real | FEITO sem chamada real (adaptador Responses + teste local); validação real BLOQUEADA (D-03) |
| AT-012.2 | Router por capacidade/privacidade/orçamento; modos simples | any | FEITO |
| AT-013 | Memória: camadas, proveniência, FTS5, correção versionada, exclusão | any | FEITO (texto/FTS5, proveniência, correção, exclusão); índice semântico: pós-M6 |
| AT-014 | Registry de ferramentas + Artifact Broker (any) e Execution Box (mac) | any / mac | PARCIAL: Artifact Manager do host FEITO; Execution Box BLOQUEADO (D-01) |
| AT-015 | Playwright no guest, perfis, takeover | mac | BLOQUEADO (D-01) |
| AT-016 | Planner e Verifier | any + D-03 | PARCIAL: laço + verificador FEITOS com modelo falso; qualidade real depende de D-03 |
| AT-018 | Voz e canal remoto | mac + D-05/D-06/D-11 | BLOQUEADO |
| AT-019 | Skills, atualização assinada, rollback | mac + D-07 | BLOQUEADO |
| AT-020 | Release e aceitação | mac + D-07 | BLOQUEADO |
| AT-003/004 | Provas de VM, tela, rede e sentinelas de host | mac | BLOQUEADO (D-01) |
| AT-009 | App SwiftUI, onboarding, chat, diagnóstico | mac | BLOQUEADO (D-01) |

## Revisão 21422f3 — achados e continuação (branch `impl/alpha-continuation`)

| ID | Tarefa | Estado |
| --- | --- | --- |
| R-03 | Prazo, cancelamento em voo e conclusão tardia de ferramentas | FEITO (41f9a1c) |
| R-04 | Ciclo de vida das reservas de inferência | FEITO (5047b00) |
| R-02 | Teste real de provedor executável e opt-in | FEITO (ea79619); execução real BLOQUEADA (D-03) |
| E2 | Adaptador OpenAI Responses + "Testar inteligência" | FEITO sem chamada real (ea79619) |
| E3a | Artifact Manager (host) | FEITO (6f8c33a) |
| E3b | Verificador objetivo | FEITO (6f8c33a) |
| E3c | Laço do agente + ferramentas internas | FEITO com modelo falso (bee1ff9) |
| E3d | IPC autenticado + serviço atlas-core | FEITO (f4b6a48, correção de caminho no macOS) |
| E4a | Swift AtlasKit: framing, cliente IPC, KeychainStore, teste Swift<->Python | FEITO no runner macOS (b7e95af) |
| E4b | Ponte Keychain do Supervisor para o Vault Python (retira o xfail) | FEITO e testado no runner macOS |
| E4c | App SwiftUI, Supervisor, pacote com Python embutido | FEITO e compilado/testado no runner macOS (Supervisor com processos reais, pacote headless); uso interativo e SMAppService: D-01 |
| E4d | Criptografia de backups (AES-256-GCM) | FEITO; criptografia do banco em uso segue pendente (D-09) |
| E5a | Daemon atlas-core + worker + métodos do app | FEITO; fluxo Alpha com Keychain real e modelo falso aprovado no CI macOS |
| E4e | Workspace Linux ARM64 (Virtualization.framework), guest agent, rede mediada | BLOQUEADO (D-01: runner de CI não substitui Mac com virtualização) |

## Revisão Alpha 1 (2a7fd85) — correções Alpha 2 (branch `impl/alpha2`)

| ID | Tarefa | Classificação | Estado |
| --- | --- | --- | --- |
| A1 | Segundo salvamento das configurações falhava (revisão fixa em 0) | reproduzido | FEITO: `settings.get`, revisão lida do núcleo, testes de três salvamentos, reabertura e concorrência |
| A2 | Conversa unidirecional; cada frase virava tarefa | reproduzido | FEITO no núcleo e no app; validação interativa: D-01 |
| A3 | I/O de socket no MainActor; sem reconexão na mesma janela | reproduzido | FEITO: `AtlasConnection`; testes com servidor falso e com processos reais no CI |
| A4 | Sem anexos reais no app | reproduzido | FEITO: upload em partes, importação validada, prévia só texto, salvar com hash |
| A5 | Modelo via só nomes de ferramentas; entrada não validada antes do broker | reproduzido | FEITO |
| A6 | Nenhuma chamada a modelo real | não aplicável sem D-03 | BLOQUEADO (D-03) |
| A7 | Retomada recomeçava o plano; retries e agenda fora do worker | reproduzido | FEITO |
| A8 | "Testar inteligência" fora do ledger global; preço não verificado tratado como teto | reproduzido | FEITO |
| A9 | Cenário visual de 10 passos no Mac | bloqueado | BLOQUEADO (D-01): sem screenshots de mock |
