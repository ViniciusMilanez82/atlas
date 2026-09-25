# Revisão do PR #5 — como usar

Este pacote é um adendo ao contrato integral v2, não uma reescrita do produto e não o aplicativo pronto.

Para o proprietário: envie o pacote à IA que já trabalha no Atlas e cole `Atlas_Prompt_Pos_PR5.txt`. A IA deverá conferir o HEAD e preservar os commits existentes. O PR #5 já foi integrado; não é preciso abrir outro repositório.

## Arquivos

- `Atlas_Revisao_PR5_80f357b.md`: escopo, nove achados, reproduções, correções e testes.
- `Atlas_Prompt_Pos_PR5.txt`: instruções executáveis de continuação.
- `repro/test_pr5_review.py`: script independente contra as classes reais do núcleo, com provedor gravador local. Não chama API real.
- `repro/results.json` e `repro/run.log`: resultados da execução feita nesta revisão.
- `evidencias/source_manifest.json`: hash do artifact e comparação de sete blobs com o head do PR.
- `evidencias/achados.json`: os nove achados em estrutura legível por ferramentas.
- `evidencias/ci_observado.md`: resumo dos trechos observados nos logs do GitHub; não substitui os logs originais.
- `SHA256SUMS.txt`: integridade dos arquivos do pacote.

## Rodar a reprodução

Use o ambiente de desenvolvimento do repositório e as dependências compatíveis. O código-fonte não é duplicado neste ZIP; a IA já deverá ter acesso ao repositório. Não execute sobre dados reais: o script cria bancos e arquivos temporários próprios.

macOS/Linux, apontando ao checkout autorizado do Atlas:

```sh
PYTHONPATH="/caminho/do/atlas" python "/caminho/deste/pacote/repro/test_pr5_review.py"
```

PowerShell, num ambiente de desenvolvimento Windows compatível:

```powershell
$env:PYTHONPATH = "C:\caminho\atlas"
python "C:\caminho\pacote\repro\test_pr5_review.py"
```

A execução auditada foi Linux/Python 3.13.5. Outras plataformas/versões não foram executadas aqui. O script utiliza APIs internas do snapshot revisado; nomes podem precisar de adaptação depois de novos commits. Ele grava os resultados ao lado do próprio arquivo.

## Atenção: reprodução não é aceite

O script é executado como script, não como suíte pytest. `DEFECT_REPRODUCED` informa que o comportamento incorreto foi confirmado. Ele possui asserts do resultado defeituoso do snapshot. Código de saída zero não significa qualidade: observe cada resultado. Depois do reparo, os asserts das reproduções antigas podem deixar de valer; isso, sozinho, não prova correção, pois um erro no harness também pode causar falha.

A IA deve transpor cada cenário para regressões da aplicação que afirmem a propriedade CORRETA, incluindo controles positivos. “Todos os reprodutores passaram” nunca é um critério de release.

Não desative proteção de dados, validações, aprovações ou testes para produzir um resultado verde. Não confunda o provedor falso usado aqui com validação em uma conta de API real.
