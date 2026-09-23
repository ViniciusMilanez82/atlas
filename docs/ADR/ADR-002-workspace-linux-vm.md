# ADR-002 — Workspace Linux ARM64 em VM

**Referência:** spec 4.1, 5.2, 22.1  
**Status:** Aceita (baseline). Prova M1 NÃO EXECUTADA (sem Mac).
**Data:** 2026-09-23

## Contexto
O Atlas precisa de um escritório digital próprio, sem acesso ao desktop pessoal.

## Alternativas consideradas
1. VM Linux ARM64 via Virtualization.framework. 2. VM macOS. 3. Contêiner Docker. 4. Perfil separado de navegador no host.

## Decisão
VM Linux ARM64 é o WorkspaceProvider de produção. O contrato Python `WorkspaceProvider` é definido de forma independente do provider. Um MockWorkspace existe só em `tests/fakes`, identificado como fake.

## Consequências
Docker e perfis de navegador no host são rejeitados como fronteira (spec 1.3, 5.3). Se a VM falhar, o sistema para com diagnóstico, sem fallback no host.
