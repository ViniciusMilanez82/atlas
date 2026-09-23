# ADR-012 — Limite transacional do Control Plane

**Referência:** spec 9.3, 13.3  
**Status:** Aceita
**Data:** 2026-09-23

## Contexto
A spec pede que o Runtime seja o escritor lógico das entidades de trabalho, que operações de autoridade sejam confirmadas pelo Control Plane e que dois serviços não concorram sobre invariantes de aprovação sem limite transacional definido.

## Alternativas consideradas
1. Dois bancos (trabalho e autoridade) com dois processos escritores. 2. Um banco e um processo núcleo (`atlas-core`) que hospeda persistência e Control Plane, com o Runtime em processo separado falando só por IPC.

## Decisão
Alternativa 2. Um único arquivo SQLite, aberto para escrita por um único processo. O Runtime (LLM, planejamento, ferramentas) decide as mudanças de trabalho e as envia ao núcleo por IPC. A API de IPC não expõe escrita em políticas, mandatos, aprovações, reservas ou ledger. O broker verifica lease, fencing token, política, aprovação e reserva de orçamento na mesma transação que marca a ação como DISPATCHING.

## Consequências
Invariantes de autoridade ficam atômicos. Nesta fase o núcleo é uma biblioteca testada em processo. A separação em processos é validada em M4/M5 com o Supervisor.
