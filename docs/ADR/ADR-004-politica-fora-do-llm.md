# ADR-004 — Política fora do LLM

**Referência:** spec 6.1, 11, 22.1  
**Status:** Aceita. Implementação em `security/policy` (M3).
**Data:** 2026-09-23

## Decisão
A Policy Engine é código determinístico. Recebe ação normalizada, ator autenticado e contexto verificável, e retorna ALLOW, ASK ou DENY com reason_code e policy_version. Efeito e risco vêm do registro confiável de ferramentas, nunca da proposta do LLM. Falha interna resulta em DENY.

## Consequências
Nenhum texto (prompt, página, e-mail, skill) muda permissões. Proibições (R5, capacidades desligadas) são avaliadas antes de qualquer regra permissiva.
