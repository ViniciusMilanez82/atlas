# ADR-010 — Layout Python e ferramentas

**Referência:** spec 21  
**Status:** Aceita
**Data:** 2026-09-23

## Decisão
As pastas de topo da spec (`shared`, `storage`, `security`, `runtime`) são pacotes Python importáveis a partir da raiz (`pythonpath = ["."]`). `platform/` não é pacote Python, para não colidir com o módulo `platform` da biblioteca padrão. O contrato Python do workspace fica em `runtime/workspace`. Ferramentas: pytest, ruff, mypy --strict e jsonschema, com versões fixadas em `requirements-dev.lock`. O ambiente virtual fica fora do OneDrive (`%USERPROFILE%\.venvs\atlas`) para não sincronizar milhares de arquivos.

## Consequências
Importações ficam como `from security.policy.engine import PolicyEngine`. Nomes genéricos de pacote exigem que o projeto rode em ambiente virtual próprio.
