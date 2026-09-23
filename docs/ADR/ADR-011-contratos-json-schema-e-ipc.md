# ADR-011 — Contratos em JSON Schema e IPC JSON-RPC

**Referência:** spec 13.4 a 13.7  
**Status:** Aceita
**Data:** 2026-09-23

## Decisão
`shared/schemas/*.schema.json` (draft 2020-12) é a fonte de verdade dos contratos entre Swift, Python e TypeScript. Todo objeto é fechado (`additionalProperties: false`). Dinheiro é inteiro em unidade mínima com moeda obrigatória. IDs são UUID gerados pelo sistema. Parâmetros de IPC não aceitam `actor`, porque o ator vem do canal autenticado. O hash de aprovação usa JSON canônico (chaves ordenadas, sem espaços, floats proibidos).

## Consequências
Qualquer mudança de contrato altera o schema e os testes de contrato. Swift e TypeScript validarão contra os mesmos arquivos quando existirem.
