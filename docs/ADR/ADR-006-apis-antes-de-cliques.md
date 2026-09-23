# ADR-006 — APIs e drivers antes de cliques livres

**Referência:** spec 10.2, 22.1  
**Status:** Aceita. Implementação em M9.
**Data:** 2026-09-23

## Decisão
Ordem de preferência: API oficial ou integração tipada, depois Playwright estruturado com binários fixados, e só então interação visual como último recurso. Escrita em site autenticado não homologado fica em modo assistido.

## Consequências
Cada driver de escrita é uma ferramenta registrada, com classe de efeito e verificação próprias.
