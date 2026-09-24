# ADR-015 — Adoção do Contrato Integral de Implementação v2.0

**Referência:** docs/spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md (cap. 0.2, 26–28)
**Status:** Aceita
**Data:** 2026-09-24

## Contexto
O proprietário entregou o contrato v2.0 (31 capítulos, anexos A/B/C): 32 ordens de correção da
auditoria da Alpha 2 (A3-01..A3-32), 40 cenários de aceite (T01..T40) e 24 pacotes até a V1
(N01..N24). A Especificação Técnica v1.0 (`docs/MASTER_SPEC.md`, `docs/spec/Atlas_Especificacao_Tecnica_v1_0.*`)
continua sendo o histórico da visão.

## Alternativas consideradas
1. Reescrever `MASTER_SPEC.md` com o conteúdo novo — rejeitada: o contrato proíbe alterar o histórico.
2. Manter só um resumo do contrato no repositório — rejeitada: o contrato prevalece sobre índices.
3. Adicionar o pacote íntegro em `docs/spec/v2/`, com hashes, e apontar o índice para ele — escolhida.

## Decisão
- O contrato vigente é `docs/spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md`; o pacote é copiado sem edição
  e conferido por `docs/spec/v2/SHA256SUMS.txt`.
- Precedência (cap. 0.2): segurança e autorização > contrato v2 > contratos legados compatíveis >
  sugestões de biblioteca/layout.
- Os documentos de acompanhamento exigidos (cap. 27.4) passam a ser: `docs/BASELINE.md`,
  `docs/AUDIT_REMEDIATION.md`, `docs/CAPABILITY_MATRIX.md`, `docs/PROGRESS.md`,
  `docs/REQUIREMENTS_TRACEABILITY.md` e os demais já existentes.
- O app macOS permanece em `platform/macos/AtlasKit` (cap. 3.1); não será criado `apps/macos`.
- `AGENTS.md` na raiz incorpora `docs/spec/v2/AGENTS_ATLAS.md` (não havia AGENTS.md anterior).

## Consequências
- Cada achado A3 é reavaliado no HEAD com evidência antes de ser classificado.
- Nenhum gate é declarado com mock, skip ou teste sem asserção. Itens que dependem de Mac real,
  provedor pago, conta ou assinatura ficam BLOQUEADOS com causa, sem bloquear o resto do trabalho.
- "Alpha corrigida" não é V1: o status público continua Alpha até os gates G4–G10.
