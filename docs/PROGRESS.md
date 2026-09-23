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
