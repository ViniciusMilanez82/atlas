# ADR-005 — Interfaces de modelo próprias

**Referência:** spec 6.1, 6.4, 22.1  
**Status:** Aceita. Implementação em M6.
**Data:** 2026-09-23

## Decisão
Contratos próprios para ModelProvider, ModelRouter, ContextBuilder, Planner, ToolBroker, Verifier e MemoryManager. SDKs podem ser usados dentro de adaptadores, sem guardar o estado canônico. IDs de modelo são validados contra a conta antes do uso.

## Consequências
Trocar de fornecedor não apaga tarefas, memória ou identidade. Os IDs do catálogo da spec (gpt-6-sol, gpt-6-astra, gpt-6-luna, claude-opus-5-5) continuam NÃO VALIDADOS até um teste real autorizado.
