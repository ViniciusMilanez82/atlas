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
