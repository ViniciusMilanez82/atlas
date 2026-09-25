# Incremento de produto local — N20 / N22

Base: `462df21ff283ec5a35fe0385c821900ac645ad96` (PR7, após CI aprovado).
Fonte local: artefato `Atlas-source-evidence`, execução 36163449494, artifact 10876692133.
SHA-256 do ZIP externo: 615d580d96de575b1c07c5eb6c90117c75915dd2366674f5ec94fad6b855fe63.
SHA-256 do arquivo fonte interno: 4d96c7b17fd02c66caf93e472763dbebd54e06d928c57dbb1fd5a6b58c49bea4.

## Implementação

- Wizard: identidade → inteligência/orçamento → privacidade → conclusão.
- Identidade persiste por revisão, com CAS e dono local; mesmos IDs, memória e tarefas preservados.
- `setup.complete` distingue inteligência disponível de uso limitado explicitamente aceito, sem chamar modelos ou conceder consentimentos.
- Perfil vigente entra como apresentação em conversa e tarefas; nome citado como dado, idioma validado e fuso IANA.
- Privacidade e pesquisa pública ganham interface. O backend de consentimentos existente continua a única autoridade de saída.
- Edição de orçamento/modelos preserva privacidade, rede, segurança e perfis adicionais. Conflitos pedem releitura, sem sobrescrita cega.
- Ditado nativo somente local, com permissão explícita, limite de 60 segundos, cancelamento e proteção contra callbacks atrasados. Produz rascunho, não envia por conta própria.
- Síntese nativa explícita “Ouvir resposta”; parar áudio não pausa tarefas. Desligamento e saída da tela fecham captura.

## Evidência local disponível

Linux x86_64, Python 3.13.5, dependências instaladas no ambiente, não o lockfile do CI.
`pytest tests/regression/test_product_setup.py` antes dos handlers: 6 failed, 8 passed (rejeições já cobertas).
Depois: 14 passed; com apresentação de perfil: 15 casos.
`pytest tests/regression/test_product_setup.py tests/regression/test_a3_01.py tests/regression/test_a3_18.py tests/regression/test_r5_01.py`: 33 passed.
`swiftc -frontend -parse ...`: sintaxe das novas fontes/testes e aplicação validada; isto NÃO é compilação/link de frameworks macOS.
`git diff --check`, compilação Python e varredura de segredos: aprovados.

Baseline local completa ANTES deste incremento: 752 passed, 4 skipped, 1 failed (SBOM identifica corretamente versões instaladas diferentes do lockfile). Ruff e mypy não estão instalados; tentativa de instalação falhou por indisponibilidade de DNS. Esses gates não foram desabilitados e deverão rodar no CI com dependências corretas. CI da base remota 36163454092: success.

Testes Swift novos são doubles da captura/saída e transporte, não validação interativa. Nenhum áudio real gravado, nenhum modelo real chamado, nenhuma interface executada por pessoa num Mac nesta sessão.

Execução local completa APÓS o incremento: **767 passed, 4 skipped, 1 failed**. A única falha permanece a verificação SBOM das versões locais, também presente na baseline. Os 15 novos testes de setup passaram. Nenhum gate foi removido.

## Aceite interativo ainda obrigatório

Instalar bundle em Mac compatível; salvar identidade; salvar orçamento duas vezes; conceder/revogar só a finalidade desejada; confirmar que permissões sobreviveram ao salvamento; escolher modo limitado; reabrir. Com credencial e teto autorizados, validar inteligência pelo botão existente.

Ditar com pt-BR disponível localmente, negar/revogar permissão, cancelar durante diálogo de permissão, finalizar/revisar/corrigir o rascunho, enviar uma mensagem comum; ouvir resposta, parar fala e parar trabalho durante outra operação. Verificar indicador do microfone e ausência de gravações persistidas. Idioma local indisponível deve produzir erro honesto, sem reconhecimento remoto.

## Produto restante

VM e fronteira de rede no Mac, Execution Box, navegador/perfis/takeover, contas/e-mail, skills, companion E2EE, cifra em repouso, login item, notarização/atualizações e avaliação com provedor real continuam no contrato. Este incremento não é entrega integral da V1.
