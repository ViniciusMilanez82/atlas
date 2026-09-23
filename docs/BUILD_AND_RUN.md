# ATLAS — Build e execução

## 1. Estado atual

Só existe o **núcleo Python** (contratos, dados, autoridade, tarefas). Não há aplicativo para
abrir ainda. O app macOS, a VM e o instalador dependem de Mac (ADR-009).

## 2. Pré-requisitos verificados (diagnóstico de 2026-09-23)

| Item | Host atual (Windows 11 x86_64) | Necessário para o produto |
| --- | --- | --- |
| Python | 3.14.2 | 3.12+ |
| SQLite (via Python) | 3.50.4 com FTS5 | FTS5 obrigatório |
| Git | 2.52.0 | qualquer recente |
| Node | 22.22.0 | companion web (M14) |
| Swift / Xcode | **ausente** | App, Supervisor, Workspace Host |
| Virtualization.framework | **ausente** (Windows) | VM Linux ARM64 (M1) |
| Keychain | **ausente** (Windows) | Vault de produção (M2) |

## 3. Preparar o ambiente de desenvolvimento

O ambiente virtual fica fora do OneDrive para não sincronizar milhares de arquivos (ADR-010).

Windows (Git Bash ou PowerShell):

```bash
python -m venv "$USERPROFILE/.venvs/atlas"
"$USERPROFILE/.venvs/atlas/Scripts/python.exe" -m pip install -r requirements-dev.lock
```

macOS:

```bash
python3 -m venv ~/.venvs/atlas
~/.venvs/atlas/bin/python -m pip install -r requirements-dev.lock
```

## 4. Verificar

```bash
# tudo: ruff, varredura de segredos, mypy --strict, pytest
<venv-python> scripts/check.py
# só testes
<venv-python> -m pytest -q
# testes que exigem Mac real ficam marcados e são pulados fora do macOS
<venv-python> -m pytest -q -m macos
```

O resumo final do `check.py` mostra `PASS`/`FAIL` por etapa. Cole a saída em PROGRESS.md
como evidência.

## 5. Marcadores de teste

| Marcador | Significado |
| --- | --- |
| `macos` | Requer Mac real (Keychain, VM, Swift). Fora do macOS: **NÃO EXECUTADO**. |
| `provider` | Chamada real e faturável a provedor. Exige credencial no Vault e orçamento autorizado. |
| `slow` | Longo; roda no CI completo. |

## 6. CI

`.github/workflows/ci.yml` roda o núcleo Python em Linux e macOS a cada push no repositório
privado https://github.com/ViniciusMilanez82/atlas. No runner macOS o teste do Keychain roda de
verdade e fica como falha esperada estrita até o backend Swift existir (AT-006.3). Build Swift,
VM e testes de isolamento ainda não fazem parte do CI (dependem de D-01).
