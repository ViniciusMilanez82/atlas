# Implementação direta após PR #6 — precisão e tempo (N09 / T06)

Data: 2026-09-25. Base: `942b5164d5a2dda510899cf7c8dc2b85d1848315` (PR #6 integrado).
Branch: `fix/post-pr6-runtime-guards`. Alterações limitadas ao cálculo/calendário e seus testes.
Não representa homologação da V1 nem revisão integral do PR #6.

## Falhas reproduzidas em código real

1. `1234567890123456,78 - 1234567890123456,77` retornava `0.0`, não `0.01`: o literal passava por float no AST antes do Decimal.
2. O cálculo dependia da precisão/rounding do chamador. Importar o módulo ainda alterava o contexto decimal global.
3. Um literal extremo podia produzir Infinity, e expressões inválidas/overflow escapavam do erro controlado.
4. Recorrência DAILY iniciada em 2010 não encontrava a ocorrência em 25/09/2026: o limite era consumido desde a origem, mesmo fora da janela.
5. Horário explícito `2026-11-01T01:15:00-05:00` em America/New_York era mudado para 05:15Z em vez de 06:15Z.
6. Horários civis inexistentes/ambíguos eram normalizados silenciosamente. Intervalos UTC válidos cruzando a hora repetida eram recusados pela comparação civil.
7. Recorrências inválidas, IDs repetidos e conflitos fora da janela podiam produzir uma resposta enganosa.

## Correção implementada

- Tokenização aritmética restrita, separadores coerentes com a notação escolhida e Decimal construído do texto original, não do float.
- Contexto local: 34 dígitos, ROUND_HALF_EVEN, magnitude limitada a expoentes ajustados ±1000; potência inteira até ±100; expressão até 500 caracteres/profundidade 64. Operações podem arredondar a 34 dígitos: não se promete precisão matemática infinita.
- Erros numéricos normalizados como ComputeError; formatação sem NaN/Infinity e sem mudar o contexto do chamador.
- Expansão salta para perto da janela preservando ordinais/count/until/exceções e eventos longos que a atravessam.
- Máximo de 2000 ocorrências e 10000 conflitos: excesso é erro explícito pedindo redução da consulta, jamais sucesso truncado.
- Instante com offset preservado. Horário civil sem offset usa round-trip dos dois folds; gap ou ambiguidade não resolvida exige esclarecimento. Recorrências futuras em horário ambíguo também falham explicitamente: não se inventa uma política de DST.
- Conflitos limitados à janela solicitada. Dias civis de 23/25 horas e recorrência semanal às 09h preservados.

Não foram alterados schemas de autoridade, permissões, Vault, contas, banco ou rede. Não foi ativada ferramenta externa. As assinaturas públicas e adapters calc.evaluate/calendar.analyze foram preservados. Estes são recursos gerais, não um módulo de calendário familiar.

## Evidências e limites

Origem local do núcleo: artefato GitHub Actions 10874233177 / execução 36158654251 / head 676d5f08779b7238b7f89c82fa9aa34a13d5b932. SHA-256 do ZIP recalculado: `93e7b34ec10bcb885dd9c3fbd8bef83eda66feb2bc997463327adbf5f1fb4112`. O blob compute.py foi conferido contra a main base (`677e0026abe2507f37641e6d654071d5373f1913`).

Ambiente local: Linux x86_64, Python 3.13.5, dependências disponíveis no ambiente (não o conjunto lockado do CI). Comando: `python -m pytest -q tests/regression/test_compute_precision_time.py`.

- Antes da alteração: **30 failed, 14 passed**.
- Depois: **44 passed**.
- Os testes usam funções reais e os adapters BuiltinTools reais, com entradas sintéticas. O teste de adapter não é o percurso completo pelo broker/UI.
- A suíte completa, lint e mypy devem rodar no CI com as versões fixadas; esses resultados não são presumidos pelo teste local.
- Não executado localmente: UI macOS, Swift, VM, provedor de IA real, suíte completa. Não houve chave, dado pessoal, gasto de API ou merge automático.

## Rastreabilidade

Aprofunda N09/T06 do contrato v2. Os demais requisitos e pendências continuam no backlog original. A conclusão de uma tarefa de calendário depende desta resposta completa ou de uma limitação explícita; não usar a ausência de ocorrências causada por limite interno para afirmar disponibilidade.

Referências primárias consultadas: Python 3.12 decimal (construção por string e localcontext), https://docs.python.org/3.12/library/decimal.html ; datetime/zoneinfo e folds, https://docs.python.org/3.12/library/datetime.html .
