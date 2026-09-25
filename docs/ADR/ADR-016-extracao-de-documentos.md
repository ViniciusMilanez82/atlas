# ADR-016 — Extração de documentos por formato, com proveniência e cobertura

**Referência:** contrato v2, cap. 10 e 14; achados A3-09 e A3-10; pacote N08
**Status:** Aceita
**Data:** 2026-09-24

## Contexto
A Alpha 2 aceitava PDF/DOCX/XLSX/PPTX/imagens, mas a ferramenta do agente decodificava os bytes como
UTF-8 (`errors="replace"`) e cortava o texto em 200 mil caracteres e a observação em 20 mil, inclusive
no meio do JSON. Receber um arquivo era apresentado como compreendê-lo.

## Alternativas consideradas
1. Aplicativos de escritório do usuário (AppleScript/LibreOffice) — rejeitada: o contrato proíbe exigir
   aplicativos do usuário e executar macros para "ler".
2. Serviço de extração em nuvem — rejeitada como padrão: divulgação de dados (cap. 9) e custo.
3. Bibliotecas Python mantidas, puras ou com wheels arm64 para o Python 3.12 embutido — escolhida.

## Decisão
- `pypdf` 6.19.0 (BSD), `python-docx` 1.2.0, `openpyxl` 3.1.5 e `python-pptx` 1.0.2 (MIT), com
  dependências `lxml`, `et-xmlfile`, `Pillow`, `XlsxWriter` fixadas nos lockfiles (dev e bundle).
  Wheels `cp312 macosx arm64/universal2` conferidos para o Python embutido.
- `runtime/documents/extract.py`: funções puras por formato, segmentos com localizador (página, faixa de
  células, slide, parágrafos, linhas), avisos (abas/linhas ocultas, vínculos externos não abertos,
  valores de fórmula não recalculados, codificação detectada) e estados READY_FOR_ANALYSIS, PARTIAL,
  UNSUPPORTED ("armazenado, mas ainda não analisável") e FAILED com diagnóstico.
- A extração roda em processo filho com prazo (`run_in_process`). É contenção de recursos, não sandbox;
  código não confiável continua destinado à Execution Box (N15).
- `runtime/documents/store.py`: segmentos persistidos (migração 0017) com FTS; `documents.read` pagina
  segmentos completos (`next_cursor`, `has_more`, total) e registra a cobertura por tarefa;
  `documents.search` é consulta focal e não conta como leitura integral.
- PDF digitalizado e imagens ficam UNSUPPORTED até OCR/visão autorizados existirem (não são inventados).

## Consequências
- O verificador pode exigir cobertura integral dos documentos de entrada (A3-07).
- Tamanho do bundle aumenta (lxml e Pillow). Ficam pendentes: OCR/visão com consentimento, notas de rodapé e
  comentários de DOCX (declarados nos avisos), tabelas complexas de PDF por posição.
- Falha no parser do terceiro não derruba o núcleo (processo filho) e vira diagnóstico específico.
