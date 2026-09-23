# ADR-008 — Segurança antecipada

**Referência:** spec 18, 22.1  
**Status:** Aceita
**Data:** 2026-09-23

## Decisão
Política, Vault, aprovações, orçamento, broker e Action Ledger são implementados e testados antes de qualquer navegação ou ferramenta com efeito externo. Nenhum marco posterior libera bypass de controle incompleto.

## Consequências
A ordem de implementação neste host é M0, depois M2 (dados), M3 (autoridade), M5 (tarefas) e as partes de M6 e M12 independentes de plataforma.
