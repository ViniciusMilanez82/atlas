# ATLAS — Progresso

Registro por tarefa: o que foi implementado, arquivos, comandos, testes, limitações, riscos e
próxima tarefa. Testes marcados **NÃO EXECUTADO** indicam a dependência exata.

## Situação dos gates

| Gate | Estado |
| --- | --- |
| READY TO CODE | Atingido (spec 23.1) |
| G0 (contrato v2) | Atingido — baseline, contrato adotado, matriz e regressões |
| G1 (contrato v2) | Correções e regressões concluídas no núcleo; validação no Mac do proprietário pendente (D-01) |
| READY FOR BETA | **Não atingido** |
| READY FOR RELEASE | **Não atingido** |

## Contrato v2.0 — sessão de 2026-09-24 (branch `impl/contract-v2`)

Contrato vigente: `docs/spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md` (ADR-015). Baseline factual em
`docs/BASELINE.md`; matriz dos achados em `docs/AUDIT_REMEDIATION.md`; capacidades em
`docs/CAPABILITY_MATRIX.md`.

**Feito nesta sessão.** G0 completo; os 32 achados A3 corrigidos com regressão executada (reprodução
antes da correção registrada em cada commit); pacotes N02-N05 (autoridade, inbox/outbox, supervisão,
egress/orçamento) e partes de N06-N12 (conhecimento comum, intenções, extração de documentos, critérios,
uploads, interface) no nível de núcleo e ViewModel. Quatro achados novos (B-01..B-04) registrados e tratados.

**Evidência (comandos exatos).**

```text
Windows local: %USERPROFILE%\.venvstlas\Scripts\python.exe scripts/check.py
  ruff=PASS secrets=PASS mypy=PASS (88 arquivos) pytest: 592 passed, 8 skipped
  skips: 2 daemon E2E + 1 servidor UDS + 1 teste A3-28 com processos (sem Unix sockets no Windows),
         1 symlink (privilégio), 1 chamada real opt-in (D-03), 1 probe Swift e 1 Keychain real (D-01)
CI (GitHub Actions, commits da branch): core-linux, core-macos e app-evidence verdes até 7aa1c24;
  Swift no macOS 15: 35 testes, 0 falhas (inclui A304RegressionTests, G3RegressionTests e
  SupervisorTests com processos reais: segunda instância recusada, parada com prazo)
  bundle Atlas.app gerado com as novas dependências e iniciado sem Python do sistema
```

**Estados, separados.** Implementado e testado em integração: sim (ver matriz). Compilado no macOS: sim.
Modelo real: **não** (D-03). Uso interativo por uma pessoa num Mac: **não** (D-01). VM, navegador, voz,
companion, contas, skills: **não implementados** (N14-N21).

**Custos incorridos:** zero. Nenhuma credencial usada ou solicitada.

**Próximos itens desbloqueados (ordem):** N11 geração de PDF/DOCX/XLSX/PPTX como entregáveis; N09 cálculos
e datas estruturados (agenda com fusos/recorrências); N06 tela Memória e índice semântico local; N12 telas
Trabalho/Memória/Arquivos ligadas aos estados; N13 modos de inteligência (router com perfis reais) — a
validação real depende de conta e teto (D-03); N14/N15 dependem de um Mac com virtualização (D-01).

---

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

---

## Etapas 4 e 5 (Alpha no núcleo e no runner macOS) — 2026-09-23 — branch `impl/alpha-app`

**Implementado.**
- **Daemon `python -m core`:**
  - na primeira execução, cria a identidade; depois, recupera o estado após reinício;
  - grava o token do app num arquivo 0600 e serve o IPC por Unix socket;
  - o worker executa tarefas só com a inteligência configurada: credencial no Keychain, tetos de
    orçamento e modelo validado pelo "Testar inteligência";
  - sem isso, as tarefas ficam na fila e a saúde informa o motivo exato.
- **Novos métodos IPC:** `identity.get`, `credentials.register` (só pelo app local; nunca devolve o
  segredo), `intelligence.check`, `artifacts.list`, `approvals.list`.
- **Supervisor (Swift):**
  - inicia o serviço de Keychain e o núcleo com tokens em arquivos 0600 dentro de pastas 0700;
  - reinicia o núcleo após um crash, com backoff limitado;
  - encerra os dois de verdade.
- **App SwiftUI:** Conversa, Trabalho, Aprovações, Configurações e Diagnóstico. Sair do app encerra
  os serviços; fechar só a janela os mantém.
- **Pacote Atlas.app de desenvolvimento** (ADR-014): Python embutido com hash fixado, verificação
  headless e artefato `Atlas-dev.zip` no CI.
- **Backups cifrados** com AES-256-GCM.

**Evidência (CI macos-15, commit 60a73ca):**

```text
swift test: 7 tests, 0 failures. SupervisorTests: sobe o Keychain e o núcleo, conversa por IPC,
            derruba o núcleo com SIGKILL, confirma que foi reiniciado com nova sessão, encerra tudo
            e confirma que o processo terminou
pytest macOS: 420 passed, 1 skipped (chamada real opt-in, D-03), incluindo
  test_daemon_e2e::test_alpha_flow_with_real_keychain_and_fake_model: chave no Keychain real
  via IPC, orçamento salvo, "Testar inteligência" contra um servidor de modelo FALSO local,
  tarefa delegada concluída pelo worker com entregável verificado, estado preservado
  após reinício e nenhuma chamada repetida
Atlas.app: runtime conferido ("python.tgz: OK"), assinatura ad-hoc; atlas-bundle-check com
  env -i PATH=/usr/bin:/bin (sem Python do sistema) iniciou o Supervisor, falou com o núcleo
  e criou uma tarefa
Artefato: Atlas-dev-app (Atlas-dev.zip, ~31 MB)
```

**NÃO EXECUTADO / NÃO PROVADO:**
- Uso interativo do app, item de login (SMAppService) e comportamento no Mac do proprietário (D-01).
- Chamada a um modelo real (D-03).
- VM de trabalho, navegador e pesquisa pública.
- Criptografia do banco em uso (D-09).
- Voz, canal remoto e notarização (D-07).

**Custos incorridos:** zero.

---

## Alpha 2 — correções da revisão 2a7fd85 — 2026-09-24 — branch `impl/alpha2`

**Classificação dos achados.**

| Achado | Classificação | Resultado |
| --- | --- | --- |
| A1 configurações | reproduzido (2º salvamento enviava revisão 0) | corrigido com teste |
| A2 conversa | reproduzido (toda frase virava tarefa; sem respostas) | corrigido com teste |
| A3 UI bloqueante e reconexão | reproduzido | corrigido com teste (servidor falso e processos reais) |
| A4 anexos | reproduzido | corrigido com teste |
| A5 catálogo e validação | reproduzido | corrigido com teste |
| A6 modelo real | não aplicável sem credencial | BLOQUEADO (D-03) |
| A7 retomada, retries e agenda | reproduzido | corrigido com teste |
| A8 preço e ledger do teste | reproduzido | corrigido com teste |
| Cenário visual de 10 passos | bloqueado | BLOQUEADO (D-01); nenhum screenshot de mock foi produzido |

**Implementado.**
- **Conversa (`core/conversation.py`):** mensagens do dono e do funcionário persistidas e tipadas.
  O roteamento é determinístico onde possível: "pare", resposta a pergunta pendente, pedido de
  memória com confirmação, status gerado do banco, correção ligada à tarefa aberta e delegação
  explícita. O resto vai ao modelo só se a inteligência estiver configurada; sem ela, a resposta
  diz o motivo e oferece «Delegar como tarefa». Nenhuma saudação cria tarefa.
- **IPC novo:** `settings.get`, `conversations.current`, `conversations.history` (paginado),
  `memories.confirm`, `artifacts.upload` (em partes, reenvio idempotente), `artifacts.import`
  e `artifacts.read` (com hash por trecho). `tasks.create` aceita `client_request_id`.
- **Inteligência:** validação do modelo separada da validação de preço. Tabela não verificada
  bloqueia chamadas pagas até o dono aceitá-la como estimativa. O "Testar inteligência" passa
  pelo mesmo ledger e teto mensal, um de cada vez.
- **Agente:** catálogo vindo dos manifestos habilitados. Toda decisão é validada, inclusive a
  entrada contra o esquema da ferramenta, antes do broker. A retomada usa o último plano, as
  observações persistidas e as respostas do dono. Perguntas e resultados chegam à conversa.
- **Worker:** promove retentativas vencidas e executa a agenda.
- **Correção encontrada pelos testes:** o adaptador OpenAI não normalizava queda de conexão sem
  resposta, que virava "internal error".
- **App (Swift):**
  - cliente com prazo e correlação de respostas;
  - `AtlasConnection` faz todo I/O fora do MainActor, relê a sessão após reinício e nunca
    repete mutações;
  - `AtlasViewModel` é testável sem interface;
  - a interface tem balões, anexos por seletor e arrastar, prévia só em texto, salvar como com
    hash, dinheiro legível, aceite de preços e saúde com "Reiniciar serviços".
- **Versão mínima:** o pacote agora declara macOS 15.0, a única versão homologada.

**Evidência (CI, commit b81aa32).**

```text
Windows (local): ruff, segredos e mypy PASS; pytest 446 passed, 7 skipped
core-linux:      449 passed, 4 skipped
core-macos:      pytest 452 passed, 1 skipped (chamada real opt-in, D-03)
swift test:      24 tests, 0 failures
  ConnectionTests (servidor Unix FALSO): reconexão com sessão nova, prazo, mutação não repetida,
    sessão expirada, resposta não correlacionada, I/O fora da thread principal
  ViewModelTests (transporte FALSO): três salvamentos e reabertura, conflito recuperável,
    conversa sem tarefa implícita, reenvio com o mesmo id, um único teste pago por vez,
    HTML mostrado como texto, exportação só com hash conferido, dinheiro legível
  SupervisorTests (processos REAIS): a mesma conexão sobrevive a SIGKILL do núcleo com histórico
    preservado, limite de reinícios informado e "Reiniciar serviços" recupera, falha do serviço
    de Keychain é reportada
atlas-bundle-check: pacote sem Python do sistema respondeu "Oi" com o motivo real
  ("no API credential registered") e ofereceu delegar
```

**Estados, separados.**

| Estado | Situação |
| --- | --- |
| Implementado | A1–A5, A7, A8 no núcleo e no app |
| Compilado | Sim, macOS 15 (CI) |
| Testado em integração | Sim: IPC real, servidor de modelo FALSO local, processos reais do Supervisor |
| Testado com modelo real | **Não** (D-03) |
| Validado interativamente | **Não** (D-01): nenhum uso do app por uma pessoa num Mac |
| Pronto para distribuição | **Não**: assinatura ad-hoc, sem notarização (D-07), sem SMAppService validado |

**Custos incorridos:** zero. Nenhuma credencial foi solicitada ou usada.

**Primeira abertura real no runner (job `app-evidence`, macOS 15 limpo).**
[docs/evidence/alpha2-first-launch-ci-runner.png](evidence/alpha2-first-launch-ci-runner.png) é uma
captura de tela real, não um mock. O `Atlas.app` foi aberto com `open`. Supervisor, Keychain e núcleo
subiram, e a janela mostra "Conectado". A inteligência aparece como "Não configurada" com o motivo
real. Nenhum processo do app tinha socket de rede aberto. Ao sair, app e serviços terminaram.

Achado investigado: numa execução anterior apareceu o aviso "Allow Python to find devices on local
networks?". A bisseção num runner limpo mostrou que ele não vem do app, nem do Python embutido, nem
do núcleo. Ele vinha da suíte de testes, que roda antes no mesmo job.

**Isso não prova:** que uma pessoa usou o app, os passos 2 a 10 do cenário visual e o comportamento
no Mac do proprietário (D-01).
