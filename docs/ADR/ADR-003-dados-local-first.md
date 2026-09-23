# ADR-003 — Dados local-first

**Referência:** spec 4.4, 22.1  
**Status:** Aceita
**Data:** 2026-09-23

## Decisão
Identidade, conversas, tarefas, políticas, aprovações, memória, arquivos, credenciais e auditoria ficam locais. SQLite com WAL é o banco operacional e FTS5 é a base da busca textual. Não há PostgreSQL, Redis ou Kubernetes na instalação pessoal.

## Consequências
O estado não depende de SDK de provedor. Backup e restauração locais precisam de prova (M2). A criptografia do banco é pendência controlada de M2 (ver THREAT_MODEL).
