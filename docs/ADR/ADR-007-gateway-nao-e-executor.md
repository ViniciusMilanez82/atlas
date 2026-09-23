# ADR-007 — Gateway não é executor

**Referência:** spec 4.3, 14.2, 22.1  
**Status:** Aceita. Implementação em M14.
**Data:** 2026-09-23

## Decisão
O relay remoto só enfileira e entrega mensagens. Não executa tarefas nem guarda autoridade. Com o Mac offline, informa "aguardando o computador do Atlas ficar disponível".

## Consequências
Disponibilidade remota não equivale a Mac sempre ligado. Criptografia ponta a ponta tem desenho e testes próprios.
