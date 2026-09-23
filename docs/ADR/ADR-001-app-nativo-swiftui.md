# ADR-001 — App nativo em SwiftUI

**Referência:** spec 4.1, 22.1  
**Status:** Aceita (baseline da spec). Implementação NÃO INICIADA por falta de Mac (ver ADR-009).
**Data:** 2026-09-23

## Contexto
O produto é um aplicativo macOS de instalação simples, com voz, notificações, itens de login e Keychain.

## Alternativas consideradas
1. SwiftUI nativo. 2. Electron ou Tauri com interface web. 3. Mac Catalyst.

## Decisão
SwiftUI para a interface e Swift para o Supervisor, conforme a spec. O app só fala com o núcleo por IPC (ADR-011) e não contém regra de autorização.

## Consequências
Exige Xcode e Mac Apple Silicon para compilar e testar. Nada do app pode ser validado no host Windows atual.
