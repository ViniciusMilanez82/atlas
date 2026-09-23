# ATLAS — Progresso

Registro por tarefa: o que foi implementado, arquivos, comandos, testes, limitações, riscos e
próxima tarefa. Testes marcados **NÃO EXECUTADO** indicam a dependência exata.

## Situação dos gates

| Gate | Estado |
| --- | --- |
| READY TO CODE | Atingido (spec 23.1) |
| READY FOR BETA | **Não atingido** |
| READY FOR RELEASE | **Não atingido** |

## Diagnóstico do ambiente — 2026-09-23

| Item | Resultado |
| --- | --- |
| SO | Windows 11 Home 10.0.26200, x86_64 (MINGW64/Git Bash) |
| Python | 3.14.2 (venv em `%USERPROFILE%\.venvs\atlas`, fora do OneDrive) |
| SQLite | 3.50.4, FTS5 disponível (teste `create virtual table ... using fts5` executado) |
| Git / Node / Docker / WSL | 2.52.0 / 22.22.0 / 29.3.0 / 2.6.3 |
| Swift, Xcode, Virtualization.framework, Keychain | **Ausentes** — bloqueio material para M1, M4, M13, M16 e M17 (ADR-009, D-01) |
| Disco livre | 683 GB |

Conclusão: o núcleo Python pode ser construído e testado aqui. Tudo que depende de macOS fica
NÃO EXECUTADO até existir um Mac de desenvolvimento.

---

## M0 — Fundação (AT-001, AT-002) — 2026-09-23

**Objetivo.** Repositório, convenções, documentos obrigatórios, contratos e verificação mínima.

**Critérios de aceite (spec 18/19).** Checkout limpo executa a suíte; sem credenciais ou dados
reais no histórico; fixtures válidas passam; campos extras, enums inválidos e dinheiro sem moeda
falham; requisitos rastreáveis.

**Implementado.**
- Repositório git próprio em `Atlas/` (branch `main`), árvore do capítulo 21, `.gitignore`,
  `.gitattributes`, `pyproject.toml`, `requirements-dev.lock`, `THIRD_PARTY_LICENSES.md`.
- Spec preservada: `docs/spec/` (md, docx, pdf, prompt) + `SHA256SUMS`; `docs/MASTER_SPEC.md`
  é cópia byte a byte, verificada por teste.
- Contratos JSON Schema 2020-12 em `shared/schemas`: common, task, action_proposal, tool_result,
  approval, journal_event, ipc_request (22 métodos, parâmetros estritos por método),
  ipc_response, config. Fixtures sintéticas em `shared/fixtures/valid`.
- Primitivas: JSON canônico com hash (floats proibidos), `Money` por expoente ISO 4217,
  relógio UTC injetável, IDs, erros normalizados com mapeamento JSON-RPC, carga de config.
- `config/atlas.default.yaml` (spec 7.5) validado; nulos de orçamento bloqueiam chamadas pagas.
- `scripts/check.py` (ruff, segredos, mypy --strict, pytest) e `scripts/scan_secrets.py`.
- Documentos: ARCHITECTURE, THREAT_MODEL, REQUIREMENTS_TRACEABILITY, BUILD_AND_RUN, OPERATIONS,
  BACKLOG, EXTERNAL_DEPENDENCIES, ADR-000..012.
- CI em `.github/workflows/ci.yml` (Linux e macOS para o núcleo Python).

**Comandos executados e resultado.** Ver bloco de evidência abaixo.

**Não executado.** CI (sem repositório remoto, D-10). Build Swift (D-01).

**Limitações.** Os schemas ainda não são consumidos por Swift/TypeScript porque esses
componentes não existem. O transporte IPC (UDS, framing de 1 MiB) é M4.

**Riscos.** Nomes de pacote genéricos (`shared`, `storage`, `security`, `runtime`) exigem venv
próprio (ADR-010).

**Próxima tarefa.** M2: AT-005.1 (conexão SQLite e migrações).

---

## M2 — Dados e chaves (AT-005.1–5.5, AT-006.1–6.2) — 2026-09-23

**Objetivo.** Banco local com migrações, restrições, journal, recuperação após crash, backup
verificado e referências de credencial sem segredo bruto.

**Critérios de aceite.** Dados persistem; interrupção antes/depois do commit não gera estado
inválido; restauração confere hash e versão; credenciais não aparecem em logs; processo não
autorizado e ferramenta genérica não recebem segredo; chave ausente gera diagnóstico.

**Implementado.**
- `storage/db.py`: WAL, `synchronous=FULL`, FK obrigatória, `BEGIN IMMEDIATE`, transação aninhada proibida.
- `storage/migrate.py`: migrações contíguas com SHA-256; migração alterada depois de aplicada e
  banco de build mais nova são recusados; migração com erro não deixa schema parcial.
- `storage/migrations/0001_initial.sql`: modelo da spec 13.2 em tabelas `STRICT`, enums por CHECK,
  dinheiro sempre com moeda, estado BLOCKED exige motivo, lease só em RUNNING, aprovação R5
  impossível, memória SECRET proibida, FTS5 para memória, journal append-only por trigger,
  termos de aprovação e entrada de ação imutáveis por trigger.
- `storage/journal.py`: eventos validados pelo schema, `sequence_id` monotônico, resumo redigido.
- `storage/backup/backup.py`: backup consistente + manifesto; verificação de hash, formato,
  versão, `integrity_check` e contagem de linhas; restauração revoga aprovações e mandatos,
  cancela ações não despachadas, marca em voo como UNKNOWN, bloqueia a tarefa e libera leases.
- `security/vault/vault.py`: `credential_refs` no banco, segredo só no backend; liberação só ao
  Control Plane, para a finalidade e destino registrados; revogação e validade; `SecretValue`
  não imprime, não serializa e não entra em JSON canônico; diagnóstico explícito sem backend.
- `shared/redaction.py`: filtro de logging e redação por valor registrado e por padrão.
- `tzdata==2026.4` como dependência fixa (Windows não traz base IANA; comportamento igual no macOS).

**Evidência.**

```text
$ python scripts/check.py
ruff: All checks passed!
secret scan: 0 finding(s)
mypy: Success: no issues found in 27 source files
pytest: 162 passed, 1 skipped
SUMMARY: ruff=PASS, secrets=PASS, mypy=PASS, pytest=PASS
```

**NÃO EXECUTADO.** `tests/security/test_vault.py::test_keychain_backend_round_trip` — requer
Mac real e o backend Keychain do Supervisor Swift (AT-006.3, D-01). Criptografia do banco e do
backup (AT-005.6, T-12) — requer escolha de biblioteca e prova em Mac (D-01, D-09).

**Limitações.** O teste de crash usa `os._exit` no processo filho; não simula queda de energia
no nível do disco. Backups não são cifrados.

**Próxima tarefa.** M3: AT-007.1 (Tool Registry confiável) e AT-007.2 (Policy Engine).

---

## M3 — Autoridade e núcleo do M5 — Tarefas (AT-007, AT-008, AT-010.1–10.4, AT-012.1, AT-017) — 2026-09-23

**Objetivo.** Nenhum efeito externo sem política, autorização aplicável, reserva de orçamento,
lease válido e registro no Action Ledger. Tarefas persistentes com parada e recuperação reais.

**Critérios de aceite.** DENY/ASK/ALLOW, expiração, revogação e replay testados; proibição domina;
erro interno nega; mudança de valor ou destinatário invalida aprovação; corrida entre workers não
repete consumo; crash e worker obsoleto não provocam despacho indevido; parada < 2 s; falha após
envio não gera reenvio sem verificação; tetos concorrentes respeitados.

**Implementado.**
- `runtime/tools/registry.py`: manifesto confiável; registro começa desabilitado; recusa shell de
  host, leitura/exportação de segredo, escrita de política; efeito incoerente com capacidades é
  recusado (e-mail não pode se declarar leitura; compra é IRREVERSIBLE/R4); hash do manifesto
  conferido a cada uso.
- `security/policy/engine.py`: ordem completude → proibições → restrições da tarefa → dados →
  risco; SECRET nunca sai; SENSITIVE e PERSONAL elevam risco; R2 só é ALLOW no canal verificado;
  R3 pede aprovação salvo mandato; R4 sempre aprovação forte; falha interna = DENY; `policy_version`
  derivada das regras e registrável na tabela `policies`.
- `security/approvals/engine.py` e `mandates.py`: aprovação vinculada ao hash canônico e ao nonce
  exibidos; só o proprietário decide; R4 só no app local com confirmação forte; reserva/consumo
  atômicos; UNKNOWN mantém a aprovação retida; mandatos até R3, padrão de destino específico,
  teto por uso, número de usos e validade.
- `security/budget/budget.py`: categorias separadas (inferência, ferramenta paga, compra); sem teto
  = bloqueado; limites por tarefa e mês; alertas 70/90; reserva concorrente segura.
- `security/broker/ledger.py` e `broker.py`: três fases (autorizar em uma transação, executar,
  liquidar); sucesso sem recibo exigido vira UNKNOWN; exceção do adaptador em efeito externo vira
  UNKNOWN; reconciliação só com evidência e pelo proprietário ou reconciliador confiável.
- `runtime/tasks/state_machine.py` e `engine.py`: estados da spec 9.2, versão otimista, lease com
  fencing token (sair de RUNNING sempre avança o token), pausa/retomada com reavaliação,
  cancelamento que preserva efeitos passados, "pare tudo", conclusão só com critérios com
  evidência, checkpoint sem raciocínio privado, recuperação após reinício sem redespacho.
- Migrações 0002 (origem da pausa) e 0003 (vínculo da ação com aprovação, mandato e reserva).

**Bugs encontrados e corrigidos pelos testes.** `AtlasError` como dataclass congelada não podia
ser relançado por gerenciadores de contexto; aprovação aprovada mas vencida derrubava a transação
em vez de pedir nova aprovação.

**Evidência.**

```text
$ python scripts/check.py
ruff: All checks passed!
secret scan: 0 finding(s)
mypy --strict: Success: no issues found in 47 source files
pytest: 283 passed, 1 skipped (Keychain: NÃO EXECUTADO, requer Mac)
SUMMARY: ruff=PASS, secrets=PASS, mypy=PASS, pytest=PASS
```

Medição de parada (GA-12, ambiente local Windows, 25 tarefas, 10 com lease): `stop_all` abaixo de
2000 ms, verificado por asserção em `test_stop_all_under_two_seconds`.

**NÃO EXECUTADO.** Separação real dos processos atlas-core e Runtime (ADR-012) e o cartão de
aprovação na interface: dependem do Supervisor e do app (M4, D-01).

**Limitações.** Os adaptadores usados nos testes são falsos (`tests/fakes`); não existe ainda
nenhum adaptador de produção com efeito externo. Timeout por ferramenta está declarado no
manifesto mas ainda não é imposto pelo broker. Períodos de orçamento usam o mês em UTC.

**Próxima tarefa.** AT-010.5 (limites de tentativa e checkpoints) e AT-010.6 (jobs agendados),
depois M6 (adaptador de modelo sem chamada real até D-03) e M7 (memória).

---

## M5 (restante) e M7 — Limites, agendamento e memória (AT-010.5, AT-010.6, AT-013) — 2026-09-23

**Objetivo.** Loops param sozinhos; jobs recorrentes respeitam fuso e não repetem ocorrências
perdidas; memória duradoura com fonte, correção e exclusão.

**Critérios de aceite.** Até 3 tentativas por erro transitório, 2 replanejamentos sem progresso e
20 passos sem resultado verificável, configuráveis só dentro de limites seguros; backoff com
jitter; ocorrências perdidas consolidadas com confirmação; memória persiste após reinício;
correção substitui a resposta antiga sem perder a fonte; fonte externa não vira mandato nem
preferência; índices reconstruídos mantêm o resultado.

**Implementado.**
- `runtime/tasks/limits.py`: `ProgressGuard` (RETRYING com backoff e jitter; BLOCKED com
  RETRY_LIMIT ou NO_PROGRESS), `promote_due_retries`, `CircuitBreaker` por provedor.
- `runtime/tasks/scheduler.py`: jobs por intervalo ou por horário local diário com horário de
  verão correto; políticas CONSOLIDATE_AND_CONFIRM, SKIP e RUN_ONCE; deduplicação por
  `job_runs(job_id, occurrence_at)`.
- `runtime/memory/manager.py`: confiança da fonte derivada do canal (o Runtime não consegue
  forjar mensagem do proprietário); só o proprietário confirma; identidade, preferência e
  procedimento só são corrigidos pelo proprietário; segredos e textos com cara de credencial
  são recusados; janela de validade; isolamento por funcionário; consulta FTS5 neutralizada;
  exclusão remove conteúdo e índice; reconstrução do índice.
- Migração 0004 (`task_progress`, `job_runs`, horário local e dono do job).

**Evidência.**

```text
$ python scripts/check.py
ruff: All checks passed!
secret scan: 0 finding(s)
mypy --strict: Success
pytest: 309 passed, 1 skipped (Keychain: NÃO EXECUTADO, requer Mac)
SUMMARY: ruff=PASS, secrets=PASS, mypy=PASS, pytest=PASS
```

**Limitações.** Sem índice semântico (depende de modelo de embeddings e de D-03). O motor de
memória ainda não é chamado por um Planner, que é M6/M10.

**Próxima tarefa.** M6 sem chamada real: interfaces `ModelProvider`/`ModelRouter`/`ContextBuilder`,
roteamento por capacidade e orçamento, e um provedor falso para testes. A chamada real ao modelo e
a validação dos IDs dependem de D-03.

---

## M6 sem chamada real — Modelos, roteamento e contexto (AT-011 parcial, AT-012.2) — 2026-09-23

**Objetivo.** Contratos próprios de modelo, custo conservador, roteamento por capacidade,
consentimento e orçamento, e contexto ordenado por autoridade, sem gastar crédito.

**Implementado.**
- `runtime/models/types.py`: `ModelProvider` (capabilities, generate, stream, cancel,
  estimate_usage, health), resposta normalizada e erros tipados.
- `runtime/models/pricing.py`: fórmula de custo sem contar cache duas vezes, arredondamento para
  cima; tabela de referência da spec marcada `verified=False`.
- `runtime/models/router.py`: só modelos validados e com consentimento; provedor primário
  (OpenAI) antes do secundário; SECRET nunca vai para modelo; SENSITIVE exige consentimento
  próprio; fallback em 429/indisponível dentro do mesmo provedor; troca de provedor só com
  consentimento; erro de credencial pede reautorização; recusa de política não é contornada;
  parâmetros não suportados não são enviados; reserva de orçamento antes da chamada e liquidação
  pelo uso informado, com registro em `usage_ledger`.
- `runtime/models/context.py`: regras do produto, política, instrução do proprietário, objetivo,
  fatos e conteúdo externo, nessa ordem; conteúdo externo cercado por delimitador aleatório que
  não pode ser fechado; itens SECRET descartados; redação aplicada; corte pelo menos autoritativo.

**Bug encontrado pelos testes.** Com os dois provedores permitidos, o roteador escolhia o
secundário como primário. Corrigido com o conceito de provedor primário (spec 7.1).

**Evidência.**

```text
$ python scripts/check.py
ruff: All checks passed!
secret scan: 0 finding(s)
mypy --strict: Success
pytest: 331 passed, 2 skipped
SUMMARY: ruff=PASS, secrets=PASS, mypy=PASS, pytest=PASS
```

**NÃO EXECUTADO.** `tests/integration/test_models.py::test_real_provider_intelligence_check` —
requer conta de API, orçamento e consentimento do proprietário (D-03). Os IDs `gpt-6-sol`,
`gpt-6-astra`, `gpt-6-luna` e `claude-opus-5-5` e seus preços continuam não validados.

**Limitações.** Não há adaptador HTTP real de nenhum provedor. O índice semântico da memória
também depende de modelo.

**Próxima tarefa (sem Mac nem credencial).** AT-014 parte host: Artifact Manager com hash,
validação de caminho, tamanho, tipo, symlink e compactados; M11: validadores objetivos de
entrega; transporte IPC JSON-RPC com framing de 1 MiB.

---

## Publicação e primeiro CI — 2026-09-23

Repositório privado criado a pedido do proprietário: https://github.com/ViniciusMilanez82/atlas.
Primeira execução do CI: Linux aprovado; macOS falhou porque o teste do Keychain rodou de
verdade num Mac e o backend não existe (AT-006.3). O teste passou a ser falha esperada estrita
no macOS. Segunda execução: `core-linux` e `core-macos` aprovados
(macOS: 331 passed, 1 skipped, 1 xfailed).

---

## Continuação após a revisão do commit 21422f3 — 2026-09-23

Branch `impl/alpha-continuation` (sem merge). Base conferida: HEAD era o próprio 21422f3, sem diff
intermediário. Baseline: Windows 11 x86_64, Python 3.14.2, suíte 331 passed / 2 skipped
(unit 87, contract 87, integration 96+1 skip, security 48+1 skip, recovery 13).

### Etapa 0 — achados reproduzidos antes de corrigir

| Achado | Reprodução no código da revisão | Correção |
| --- | --- | --- |
| R-03 | Manifesto com `timeout_s=1`; `submit` só retornou após 3,0 s, quando o teste liberou o adaptador | 41f9a1c + `tests/security/test_broker_deadlines.py` |
| R-04 | Adaptador lançou `ConnectionResetError`: exceção vazou e a reserva ficou RESERVED sem registro da tentativa | 5047b00 + `tests/integration/test_inference_attempts.py` |
| R-02 | `test_real_provider_intelligence_check` chamava `pytest.skip` incondicional | ea79619: teste real opt-in; ausência de pré-requisito falha como BLOQUEADO |
| CI | Comentário do workflow dizia que não havia remoto | corrigido em 41f9a1c |

### Etapa 1 — robustez

**1A (R-03).** O broker aplica o prazo do manifesto. O modo thread serve adaptadores confiáveis e
cooperativos: o evento de cancelamento dispara e, depois de uma tolerância, o resultado tardio é
registrado. O modo processo serve código não cooperativo: o processo é encerrado no prazo, não
recebe credenciais e não é sandbox de segurança. Escrita interrompida vira UNKNOWN; só leitura pura
vira falha repetível. `request_cancel` alcança a operação em voo sem tocar no banco.
Testes: adaptador que nunca retorna, timeout antes do efeito, resposta perdida após o efeito,
cancelamento em voo, conclusão tardia (inclusive após cancelar a tarefa), worker obsoleto, reinício
sem duplicação, processo morto antes e depois de efeito possível.

**1B (R-04).** Tentativa de inferência registrada com a reserva antes do envio (migração 0005).
Estados RELEASED, SETTLED, ESTIMATED, UNKNOWN e RESOLVED. Reconciliação exige evidência e autoridade.
Janela de retenção liquida de forma conservadora e auditável. Não há liberação cega em `finally`.
Testes cobrem todos os casos listados pela revisão, inclusive concorrência e reinício.

### Etapa 2 — adaptador real de modelo

`runtime/models/openai_responses.py` segue a documentação oficial consultada em 2026-09-23. O
formato foi conferido para `POST /v1/responses`, `text.format` json_schema estrito, recusa como
conteúdo `refusal`, SSE `response.output_text.delta` e `response.completed`, e `x-request-id`. Os
testes usam um servidor HTTP local controlado, sem rede e sem custo.
`scripts/intelligence_check.py` executa o "Testar inteligência" do proprietário com teto explícito.

**NÃO EXECUTADO:** chamada real. Falta conta de API, teto e consentimento (D-03). **Custos
incorridos: zero.**

### Etapa 3 — tarefa completa no núcleo

- Artifact Manager do host (6f8c33a): importação e exportação explícitas, conteúdo contra extensão,
  arquivos compactados inspecionados, versões, detecção de adulteração, exportação que nunca sobrescreve.
- Verificador (6f8c33a): uma tarefa só conclui com evidência objetiva.
- Laço do agente (bee1ff9): plano persistido, decisão em JSON estrito, memória e saídas não
  confiáveis no contexto, despacho pelo broker com lease, limites, reparo e entrega verificada.
  Ferramentas internas de produção: `artifact.read_text`, `artifact.write_text`, `memory.search`.
- IPC (f4b6a48): sessões por token, ator vindo da sessão, 17 métodos, "pare" muda estado, resposta
  só cita tarefa existente. O CI do macOS achou o limite de 104 bytes do caminho do socket (corrigido).

**Evidência do fluxo** (`tests/integration/test_agent_loop.py`, com modelo roteirizado identificado
como falso): o proprietário importa duas propostas sintéticas e confirma a preferência "resumo na
primeira linha". O agente lê as duas propostas pelo broker e escreve o relatório, que começa com o
resumo porque a memória chegou ao contexto. O verificador confere hash, abertura, conteúdo, fontes e
ausência de placeholders, e a tarefa fica COMPLETED. Um "terminei" sem arquivo termina BLOCKED
(NO_PROGRESS). "Pare" no meio encerra o laço. Um documento com instrução injetada não consegue
enviar e-mail: a ação é negada com `TASK_FORBIDS_EXTERNAL_WRITES`.

**Esse fluxo não prova qualidade de um modelo real, pesquisa na web nem autonomia real.**

### Evidência de testes

```text
local (Windows):  413 passed, 4 skipped
CI core-linux:    415 passed, 2 skipped
CI core-macos:    415 passed, 1 skipped, 1 xfailed   (xfail = Keychain backend ainda inexistente)
ruff, mypy --strict (5 pacotes), varredura de segredos: PASS
```

### Riscos remanescentes

- Nenhum modelo real foi chamado; comportamento e custo reais desconhecidos.
- O modo thread não mata adaptador que ignore o cancelamento; só adaptadores confiáveis podem usá-lo.
- O modo processo não isola o disco; código não confiável exige a VM (D-01).
- Não há app, Supervisor, Keychain de produção, VM, browser, voz nem canal remoto.

### Próxima etapa

Etapa 4 no runner macOS: pacote Swift com cliente IPC e Keychain, compilado e testado no CI, e teste
entre linguagens contra o núcleo Python. A experiência interativa e a VM continuam exigindo Mac real (D-01).

### Etapa 4 (parcial) — Swift no runner macOS — commit b7e95af

`platform/macos/AtlasKit` (SwiftPM) com o mesmo enquadramento do núcleo Python, cliente IPC por
Unix socket com handshake de sessão, `KeychainStore` (senha genérica, somente neste dispositivo,
acessível só com o Mac desbloqueado) e a ferramenta `atlas-ipc-probe`.

Evidência no CI (run 35865863494, macos-15, Apple Swift 6.1.2):

```text
swift test: Executed 6 tests, with 0 failures   (framing, limites, caminho do socket,
            Keychain real: gravar, ler, atualizar, excluir, isolamento por serviço)
pytest macOS: 416 passed, 1 skipped (chamada real opt-in, D-03), 1 xfailed (ponte Keychain->Vault)
test_swift_ipc_probe: o cliente Swift compilado criou uma tarefa no núcleo Python pelo socket;
            um campo "actor" forjado foi rejeitado com INVALID_INPUT
```

**O que isso NÃO prova:** app interativo, Supervisor, retomada no Mac do proprietário, VM, rede
mediada. O runner não substitui o Mac de desenvolvimento (D-01).

### Etapa 4 — ponte Keychain → Vault (AT-006.3) — 2026-09-23

`atlas-keychain-agent` (Swift) é o serviço de Keychain do Supervisor:
- diretório 0700, socket 0600 e UID do par verificado com `getpeereid`;
- token de sessão lido de arquivo 0600;
- operações put, get e delete num serviço de Keychain dedicado.

`KeychainAgentBackend` (Python) implementa o `VaultBackend`. `platform_backend()` passa a usá-lo no
macOS quando o Supervisor configura `ATLAS_KEYCHAIN_SOCKET` e `ATLAS_KEYCHAIN_TOKEN_FILE`.

Evidência (CI macos-15): `test_keychain_backend_round_trip` executado de verdade.
- O banco guarda só a referência.
- O segredo volta do Keychain no uso escopado.
- A revogação apaga o item do Keychain.
- Um token errado é recusado.

O `xfail` estrito foi removido porque backend e teste agora são reais.

```text
CI core-macos: 418 passed, 1 skipped (chamada real opt-in, D-03)
CI core-linux: 416 passed, 3 skipped (testes de macOS não executados)
```

**Ainda não prova:** o Supervisor iniciando o serviço via launchd/SMAppService no Mac do proprietário (D-01).
