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
