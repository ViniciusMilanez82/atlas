# ATLAS — Matriz de rastreabilidade de requisitos

Cada requisito obrigatório aponta para marco, implementação e teste (spec 21).
IDs `REQ-<seção>-<n>` são atribuídos aqui aos requisitos DEVE/NÃO DEVE da spec; UX-, AT- e GA-
mantêm a numeração original.

**Estados:** `OK` implementado e testado neste host · `PARCIAL` parte independente de plataforma
feita · `PLANEJADO` ainda não iniciado · `NÃO EXECUTADO` depende de Mac/credencial (ver
EXTERNAL_DEPENDENCIES) · `DIRETRIZ` regra de processo verificada por revisão.

## Visão e limites (cap. 2–3)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-2-1 | Sem acesso por padrão a e-mail, fotos, navegador ou sessões pessoais; arquivos só por importação explícita | M1/M8 | Artifact Broker; VM | GA-08, sentinelas M1 | NÃO EXECUTADO (D-01) |
| REQ-2-2 | Não declarar ser humano; cadastros sem identidade inventada | M6/M10 | regras de sistema do ContextBuilder | eval M10 | PLANEJADO |
| REQ-2-3 | "Pare" altera estado operacional | M5 | `runtime/tasks` stop_all | `tests/integration/test_task_engine.py` | OK |
| UX-001 | Instalação gráfica assinada e notarizada, sem toolchain manual | M16 | `packaging/` | GA-16 | NÃO EXECUTADO (D-01, D-07) |
| UX-002 | Identidade com employee_id estável; estilo não altera permissões | M4 | tabela `employees` | teste de schema M2 | PARCIAL |
| UX-003 | Diagnóstico de arquitetura, macOS, memória, disco, virtualização | M4 | Supervisor | — | NÃO EXECUTADO (D-01) |
| UX-004 | Modo de inteligência real; aviso de cobrança da API | M4/M6 | onboarding | — | PLANEJADO |
| UX-005 | Perfil seguro; compras sem autorização; teto com moeda e período | M3/M6 | config + budget | `test_config_cannot_widen_security`, `test_budget.py` | PARCIAL |
| UX-006 | Canal do proprietário verificado; pareamento local | M14 | — | GA-13 | PLANEJADO |
| REQ-3-1 | Oito telas obrigatórias (3.2) | M4 | `apps/macos` | — | NÃO EXECUTADO (D-01) |
| REQ-3-2 | Tarefa criada antes de afirmar que começou; status gerado de eventos | M5/M10 | journal + TaskEngine | — | OK no núcleo (`core/service.py`, `tests/integration/test_ipc.py`); UI: M4 |
| REQ-3-3 | Fechar janela, pausar e encerrar são operações distintas | M4/M5 | TaskEngine + Supervisor | parcial em `test_task_engine.py` | PARCIAL |

## Arquitetura, ciclo de vida e isolamento (cap. 4–5)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-4-1 | Swift/SwiftUI + Supervisor Swift + Runtime Python + VM Linux ARM64 | M1/M4 | ADR-001, ADR-002 | — | NÃO EXECUTADO (D-01) |
| REQ-4-2 | Fronteiras de componentes da tabela 4.2 | todos | ARCHITECTURE, ADR-012 | testes de broker | PARCIAL |
| REQ-4-3 | Nuvem de modelos recebe só o contexto necessário | M6 | ContextBuilder | — | PARCIAL (ContextBuilder com orçamento de contexto; uso real: M10) |
| REQ-4-4 | SQLite + FTS5; sem Postgres/Redis/K8s | M2 | `storage/` | `test_storage.py` | OK |
| REQ-5-1 | Ciclos de vida separados; SMAppService; sem autologin nem desligar FileVault | M1/M4 | Supervisor | — | NÃO EXECUTADO (D-01) |
| REQ-5-2 | VM independe da janela | M1 | Workspace Host | AT-003 | NÃO EXECUTADO (D-01) |
| REQ-5-3 | Contrato WorkspaceProvider completo; snapshot só como capability real | M1/M8 | `runtime/workspace` | — | PLANEJADO |
| REQ-5-4 | Sem fallback no Mac pessoal; MockWorkspace só em testes | M1 | ADR-002 | `test_test_fakes_are_not_importable_from_production_packages` | PARCIAL |
| REQ-5-5 | Artifact Broker valida caminho, tamanho, tipo, symlink, compactados, quotas | M8 | — | — | PARCIAL (host: `runtime/artifacts/manager.py`, `tests/integration/test_artifacts.py`; guest: D-01) |
| REQ-5-6 | Rede mediada fora do guest; bloqueia LAN, loopback, metadados, DNS alternativo | M1 | — | AT-004 | NÃO EXECUTADO (D-01) |
| REQ-5-7 | Escrita em site autenticado não homologado é assistida | M9 | — | GA-05 | PLANEJADO |
| REQ-5-8 | Três níveis de execução; skill não substitui browser/broker; sem shell no host | M8 | Tool Registry | `test_no_production_code_spawns_a_host_shell` | PARCIAL |

## Inteligência e custos (cap. 6–7)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-6-1 | Contratos próprios; estado fora do SDK | M6 | `runtime/models/types.py` | `tests/integration/test_models.py` | OK (sem chamada real; D-03) |
| REQ-6-2 | Loop central persistido passo a passo | M10 | — | — | PARCIAL (`runtime/agent/loop.py`, `tests/integration/test_agent_loop.py` com modelo falso) |
| REQ-6-3 | ContextBuilder por ordem de autoridade; externo nunca vira instrução | M6 | `runtime/models/context.py` | `tests/integration/test_models.py::TestContextBuilder` | OK (sem chamada real; D-03) |
| REQ-6-4 | ModelProvider com retorno normalizado; só parâmetros suportados | M6 | `runtime/models/types.py` | `tests/integration/test_models.py` | OK (sem chamada real; D-03) |
| REQ-6-5 | Router; fallback não amplia permissões nem troca fornecedor sem consentimento | M6 | `runtime/models/router.py` | `tests/integration/test_models.py::TestBudgetedClient` | OK (sem chamada real; D-03) |
| REQ-6-6 | Máx. 2 workers de pesquisa e 1 executor de efeitos por workspace | M10 | config schema | `test_config_cannot_widen_security` | PARCIAL |
| REQ-7-1 | Adaptador OpenAI primeiro; Anthropic só com testes e consentimento; Luna sem autoridade | M6 | — | — | PARCIAL (roteador com provedor primário e consentimento; adaptador real: D-03) |
| REQ-7-2 | Modos automático/econômico/máxima qualidade/manual | M6 | config schema (enum) | teste de enum | OK (sem chamada real; D-03) |
| REQ-7-3 | "Testar inteligência"; nunca derivar ID; chaves só no Vault | M6 | — | — | PARCIAL (`scripts/intelligence_check.py`; execução real: D-03) |
| REQ-7-4 | Orçamentos separados; tetos; reservas; alertas 70/90; para ao atingir | M6 | `security/budget` | `test_budget.py` | OK |
| REQ-7-5 | Config declarativa validada; nulos = pendente | M0 | `shared/config.py`, `config.schema.json` | `TestConfig` | OK |

## Memória (cap. 8)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-8-1 | Camadas; política/credencial não são memória; inferências ficam `proposed` | M7 | `runtime/memory/manager.py` | `tests/integration/test_memory.py` | OK |
| REQ-8-2 | Registro mínimo e estados proposed/confirmed/disputed/superseded/deleted | M2/M7 | tabelas `memories`, `memory_versions` | `test_storage.py` | OK |
| REQ-8-3 | Busca híbrida; índices reconstruíveis; correção versionada | M7 | FTS5 | GA-01, GA-04 | PARCIAL (FTS5 + reconstrução OK; índice semântico depende de modelo, M6) |
| REQ-8-4 | Dados temporais UTC + IANA; dia inteiro com semântica própria | M7 | `shared/clock.py` | GA-02 | PARCIAL |
| REQ-8-5 | Aprendizado seguro; skill nova passa por sandbox e testes | M15 | — | — | PLANEJADO |

## Tarefas (cap. 9)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-9-1 | Entidades Objective..Evidence; tarefa com campos obrigatórios | M2/M5 | schema SQL, `task.schema.json` | contrato + storage | PARCIAL |
| REQ-9-2 | Máquina de estados 9.2; UNKNOWN → BLOCKED(EXTERNAL_EFFECT_UNKNOWN) | M5 | `runtime/tasks/state_machine.py` | `test_task_state_machine.py` | OK |
| REQ-9-3 | Leases, heartbeat, fencing; checkpoints; jobs com fuso | M5 | `runtime/tasks/engine.py` | `test_task_engine.py` | OK |
| REQ-9-4 | Limites de tentativa; backoff com jitter; circuit breaker | M5/M6 | `runtime/tasks/limits.py` | `tests/integration/test_limits_and_scheduler.py` | OK (limites + prazo de ferramenta em `security/broker/executor.py`) |

## Ferramentas e navegador (cap. 10)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-10-1 | Tool Registry com manifesto; desabilitado até validação; efeito declarado pelo adaptador | M3/M8 | `runtime/tools/registry.py` | `test_broker.py` | OK |
| REQ-10-2 | API > Playwright > visual; binários fixados; sem Chrome pessoal | M9 | ADR-006 | — | NÃO EXECUTADO (D-01) |
| REQ-10-3 | Perfis de browser separados | M9 | — | — | NÃO EXECUTADO (D-01) |
| REQ-10-4 | Não driblar CAPTCHA/MFA/paywall; proposta de serviço pago completa | M9/M10 | — | GA-05, GA-06 | PLANEJADO |
| REQ-10-5 | Takeover exclusivo; cliques enfileirados descartados | M9 | — | AT-015 | NÃO EXECUTADO (D-01) |

## Segurança e autorização (cap. 11)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-11-1 | Policy Engine ALLOW/ASK/DENY com reason_code e policy_version; fail-closed; proibições primeiro | M3 | `security/policy/engine.py` | `test_policy.py` | OK |
| REQ-11-2 | Classes R0–R5 com padrões da tabela 11.1; dados sensíveis elevam exigência | M3 | idem | idem | OK |
| REQ-11-3 | Mandatos limitados | M3 | `security/approvals` | `test_broker.py` | OK |
| REQ-11-4 | Objeto de aprovação 11.2; status; reserva atômica | M3 | `approval.schema.json`, `security/approvals` | contrato + `test_broker.py` | OK |
| REQ-11-5 | Mudança material invalida aprovação | M3 | hash canônico | `test_broker.py` | OK |
| REQ-11-6 | LLM não emite autorização; texto externo não autoriza; R4 com confirmação forte | M3/M4 | `decide` exige ator owner autenticado localmente | `test_broker.py`, `test_prompt_injection.py` | PARCIAL (autoridade OK; cartão de aprovação na UI: M4) |
| REQ-11-7 | Vault: Keychain; banco guarda só credential_ref; sem `read_secret` | M2 | `security/vault`, `platform/macos/AtlasKit/.../KeychainStore.swift` | `test_vault.py`; XCTest `KeychainStoreTests` (CI macOS) | OK no runner macOS (`security/vault/keychain_backend.py`, `atlas-keychain-agent`, `test_keychain_backend_round_trip`); ciclo de vida do Supervisor: D-01 |
| REQ-11-8 | Controles da tabela 11.5 | vários | THREAT_MODEL | ver T-01..T-11 | PARCIAL |

## Efeitos externos (cap. 12)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-12-1 | Action Ledger com estados; intenção persistida antes do envio | M3/M12 | `security/broker/ledger.py` | `test_broker.py` | OK |
| REQ-12-2 | UNKNOWN preservado; repetir só com prova ou idempotência confiável | M12 | idem | `test_ledger_recovery.py` | OK |
| REQ-12-3 | Cancelamento impede novos despachos; "pare tudo" < 2 s | M5 | TaskEngine | `test_task_engine.py` | OK |
| REQ-12-4 | Retomada: expira leases, reconcilia, revalida aprovações | M5/M12 | `recover_after_restart` | `test_ledger_recovery.py` | OK |

## Dados e contratos (cap. 13)

| ID | Requisito | Marco | Implementação | Teste | Estado |
| --- | --- | --- | --- | --- | --- |
| REQ-13-1 | UUID, UTC, dinheiro em unidade mínima por moeda, enums fechados, schema_version | M0 | `shared/*`, schemas | contrato + unit | OK |
| REQ-13-2 | Modelo relacional 13.2 com FKs; ação exige tarefa; aprovação exige ação; entrega exige artefato | M2 | `storage/migrations` | `test_storage.py` | OK |
| REQ-13-3 | SQLite com WAL e migrações; criptografia auditada | M2 | `storage/db.py` | `test_storage.py` | PARCIAL (cripto: D-01/D-09) |
| REQ-13-4 | IPC UDS, JSON-RPC 2.0, schema, 1 MiB, request_id e correlation_id | M0/M4 | `ipc_request.schema.json` | contrato | PARCIAL (framing 1 MiB, sessões, UDS 0700 + UID do par em `core/ipc`; autenticação de processo pelo Supervisor: M4) |
| REQ-13-5 | Métodos obrigatórios e erros normalizados | M0 | schemas + `shared/errors.py` | contrato | PARCIAL (17 métodos implementados; workspace e importação por upload respondem erro explícito) |
| REQ-13-6 | ActionProposal sem campos de autoridade | M0 | `action_proposal.schema.json` | `test_llm_proposal_cannot_carry_authority_fields` | OK |
| REQ-13-7 | ToolResult com untrusted; success isolado não prova efeito | M0/M11 | `tool_result.schema.json` | contrato | OK (`security/broker/broker.py`; recibo exigido; prazo imposto) |

## Voz, canais, artefatos, privacidade, observabilidade (cap. 14–17)

| ID | Requisito | Marco | Estado |
| --- | --- | --- | --- |
| REQ-14-1 | Voz pt-BR, transcrição visível, interrupção; incerteza pede confirmação | M13 | NÃO EXECUTADO (D-01, D-11) |
| REQ-14-2 | Canal remoto com pareamento, fila durável, E2E, offline honesto | M14 | PLANEJADO (D-06) |
| REQ-14-3 | E-mail dedicado; WhatsApp só por API oficial | M14/pós-V1 | PLANEJADO (D-05, D-12) |
| REQ-15-1 | Artifact Manager com hash, versões, MIME | M8 | PARCIAL (host OK; formatos binários além de detecção: futuros) |
| REQ-15-2 | Verificação objetiva; frase do modelo não basta | M11 | PARCIAL (texto/JSON: `runtime/verification/verifier.py`; planilhas e código: futuros) |
| REQ-15-3 | COMPLETED só com critérios obrigatórios satisfeitos | M5/M11 | OK no núcleo (`test_verifier.py`, `test_agent_loop.py::test_false_completion_is_never_accepted`) |
| REQ-16-1 | Mínimo necessário; fixtures sintéticas | todos | OK para fixtures atuais (varredura de segredos/CPF) |
| REQ-16-2 | Retenção configurável | M7/M15 | PLANEJADO |
| REQ-16-3 | Exclusão de índices; backup testado por restauração | M2/M7 | OK para memória e backup; artefatos: M8 |
| REQ-16-4 | Atualização assinada; ponto de recuperação antes de migração | M16 | NÃO EXECUTADO (D-07) |
| REQ-17-1 | Eventos com campos 17.1; redação de sensíveis | M2 | OK |
| REQ-17-2 | Metas de aceitação medidas | M17 | NÃO EXECUTADO (D-01) |

## Cenários de aceitação (cap. 20)

| ID | Cenário | Depende de | Estado |
| --- | --- | --- | --- |
| GA-01 | Memória e reinício | M7 | OK |
| GA-02 | Cruzamento temporal | M7 | PLANEJADO |
| GA-03 | Pesquisa e relatório | M9–M11, D-03 | PARCIAL (fluxo com documentos e modelo falso; pesquisa pública real requer browser no guest, D-01) |
| GA-04 | Preferência corrigida | M7 | OK |
| GA-05 | Obstáculo legítimo | M9 | NÃO EXECUTADO (D-01) |
| GA-06 | Recurso pago | M3, M10 | PARCIAL (autorização testada; fluxo completo em M10) |
| GA-07 | Mudança material | M3 | OK |
| GA-08 | Prompt injection | M3, M6 | PARCIAL (camada de autoridade + laço com modelo enganado: `test_injected_document_cannot_make_the_agent_send_email`) |
| GA-09 | Código novo | M8 | NÃO EXECUTADO (D-01) |
| GA-10 | Crash após envio | M12 | OK |
| GA-11 | Orçamento | M6 | OK (inferência e ferramentas pagas com reserva concorrente) |
| GA-12 | Comando de parada | M5 | OK |
| GA-13 | Operação remota | M14 | PLANEJADO |
| GA-14 | Mac indisponível | M14 | PLANEJADO |
| GA-15 | Backup e exclusão | M2, M7 | PARCIAL (backup/restore e exclusão de memória OK; artefatos: M8) |
| GA-16 | Instalação limpa | M16 | NÃO EXECUTADO (D-01, D-07) |
