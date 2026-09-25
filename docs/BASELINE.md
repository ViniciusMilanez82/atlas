# ATLAS — Baseline factual (G0 / N01)

Registrada em 2026-09-24, antes de qualquer alteração exigida pelo contrato v2.0 (ADR-015).

## Repositório

| Item | Valor |
| --- | --- |
| Branch principal | `main` |
| HEAD | `d81cece2713ccb5b12e58902e55b05a614467951` (Merge PR #4, tag `v0.1.0-alpha.2`) |
| Igual à baseline do contrato? | **Sim.** Nenhum commit posterior; árvore limpa (`git status`: clean) |
| Branch de trabalho | `impl/contract-v2` |
| Último CI em `main` | run 36011007155 — success (core-linux, core-macos, app-evidence) |

## Ambiente desta sessão (host de desenvolvimento)

| Recurso | Situação |
| --- | --- |
| SO | Windows 11 Home 10.0.26200 (x86_64) |
| Python | 3.14.2 (venv `%USERPROFILE%\.venvs\atlas`), SQLite 3.50.4 com FTS5 |
| Git / Node | 2.52.0 / 22.22.0 |
| Swift, Xcode, Keychain, Virtualization.framework | **Ausentes** neste host (ADR-009) |
| macOS real | **Indisponível** nesta sessão. Swift é compilado/testado no runner `macos-15` do GitHub Actions |
| Unix domain sockets | Indisponíveis no Windows: testes de daemon/IPC real rodam no CI Linux/macOS |
| Provedor de IA real | **Não autorizado/configurado** (sem chave, sem teto). Nenhuma chamada paga feita |
| Conta operacional, domínio/relay, assinatura Apple | **Não disponíveis** |

## Suíte executada na baseline (sem alterações)

Comando: `%USERPROFILE%\.venvs\atlas\Scripts\python.exe scripts/check.py`

```text
ruff=PASS  secrets=PASS (0 findings em 202 arquivos)  mypy=PASS (73 arquivos)
pytest: 446 passed, 7 skipped in 45.33s
SKIPPED: 2x daemon E2E (UDS), 1x symlink (privilégio Windows), 1x IPC UDS server,
         1x chamada real opt-in (D-03), 1x probe Swift (D-01), 1x Keychain real (D-01)
```

Camadas diferenciadas (cap. 25.1):

| Camada | Onde roda | Estado na baseline |
| --- | --- | --- |
| Python unitário/integração | Windows local + CI Linux/macOS | verde |
| IPC real (UDS) e daemon E2E | CI Linux/macOS | verde no CI (run 36011007155) |
| Swift (AtlasKit, ViewModel, Supervisor com processos reais) | CI macOS 15 | 24 testes verdes |
| Keychain real | CI macOS 15 | verde |
| Bundle `.app` (Python embutido) | CI macOS 15 | gerado e iniciado sem Python do sistema |
| Interface interativa por uma pessoa | — | **não executado** (D-01) |
| VM / Workspace | — | **não existe** |
| Provedor real | — | **não executado** (D-03) |

## Diferença para a baseline do contrato

Nenhuma: o HEAD é o commit auditado. Portanto os 32 achados foram reavaliados diretamente neste
código; o resultado de cada triagem está em `docs/AUDIT_REMEDIATION.md`.
