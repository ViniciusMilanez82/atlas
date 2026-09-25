# Resumo de evidência CI consultada

Data da consulta: 25/09/2026.

Fonte primária: job `108050875369`, execução `36128752671` de `ViniciusMilanez82/atlas`.

https://github.com/ViniciusMilanez82/atlas/actions/runs/36128752671/job/108050875369

Trechos observados no log (horários UTC):

- 11:19:41 — checkout `0bbc90fc813eb19be5216a4a4215fbec3286f4dc`, merge temporário de `80f357b44663b190a4cacc8038accf27d0c11c13` sobre `d81cece2713ccb5b12e58902e55b05a614467951`.
- 11:21:55 — Swift: `Executed 37 tests, with 0 failures`.
- 11:24:46 — Python: `634 passed, 1 skipped in 164.31s`.
- O skip identifica a chamada opt-in ao provedor real, condicionada a `ATLAS_REAL_PROVIDER_TEST=1`.
- 11:24:46 — `SUMMARY: ruff=PASS, secrets=PASS, mypy=PASS, pytest=PASS`.
- 11:25:18 — bundle `Atlas.app` construído, `0bbc90f`, assinatura ad-hoc, sem notarização.
- 11:25:20 — bundle-check responde com worker `ok`, inteligência não configurada (sem credencial), workspace/voice/remote indisponíveis.
- 11:25:31 — artifact `10861445580`; tamanho 54.266.872 bytes; SHA-256 `ace9d3c1069d7a9ecc295c73588fe2d0125fa123e8e40a0afb15e4ef8083422f`.

Este documento é um resumo/transcrição seletiva, não o arquivo completo dos logs. A revisão consultou o conteúdo retornado pelo conector GitHub. Os números pertencem ao CI; não foram obtidos por executar a suíte inteira no ambiente local de revisão.
