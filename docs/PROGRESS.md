# ATLAS — Progresso atual

Atualização: 2026-09-25. Contrato vigente: [v2 integral](spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md).

O registro anterior foi preservado **integralmente, sem alteração de conteúdo**, em
[PROGRESS_through_PR6.md](PROGRESS_through_PR6.md) (blob Git `05b30cfa5c23c514250504fa00e6a1e698cba3eb`).
Este índice adiciona os incrementos posteriores; não reescreve fatos, resultados ou pendências históricas.
As referências relativas do registro anterior permanecem no mesmo diretório.

## Estado do produto

**Alpha em desenvolvimento. Não é Beta nem V1 completa.** Nenhuma validação interativa por pessoa no Mac,
nenhuma chamada a modelo real e nenhum gasto de API foram realizados nesta rodada.

Main de origem: `942b5164d5a2dda510899cf7c8dc2b85d1848315` (PR6 integrado).
Mudanças posteriores estão no PR7, branch `fix/post-pr6-runtime-guards`, sem merge automático.

## Incrementos implementados

### N09 / T06 — Precisão e tempo

Commits `8046c87`, `6d3bea3`: literais decimais exatos, contexto privado, limites explícitos, recorrências
antigas localizadas na janela solicitada, offsets preservados, ambiguidade de horário não normalizada
silenciosamente. 44 testes direcionados. CI do commit `6d3bea3` (36162492468) e da base `462df21`
(36163454092) concluídos com sucesso. Não são provas de toda a V1.

### N20 e parte de N22 — Uso local guiado e voz revisável

Implementação `36bfc470704879d0034227aadc61ebeb814d5575`; correção de lint
`cb5bd41bc9ca6513d4fda2989f73bbc912c43eff`.

- Primeira utilização: identidade → inteligência/orçamento → privacidade → conclusão.
- Identidade editável por dono autenticado no app local, CAS e fuso IANA; conserva IDs, tarefas e memória.
- Perfil vigente utilizado pelo chat e pelas tarefas. Nome é dado citado, não autoridade.
- Painel dos consentimentos existentes por finalidade e pesquisa pública. Mudança de orçamento/modelos
  preserva configurações de privacidade, rede e segurança; conflito de revisão não sobrescreve dados.
- Ditado nativo somente quando o macOS oferece reconhecimento local, com permissão explícita,
  limite de gravação e rejeição de callbacks atrasados. Sem fallback remoto automático.
- Transcrição é rascunho editável e usa o compositor existente. Não envia nem autoriza ações sozinha.
- Síntese explícita de resposta; parar áudio é independente de parar o trabalho.
- Migração 0028, contratos IPC, 15 casos Python de setup e 11 casos Swift de configuração/controle.

Detalhes, comandos, limites e roteiro de uso: [LOCAL_PRODUCT_INCREMENT.md](LOCAL_PRODUCT_INCREMENT.md).
Decisão: [ADR-019](ADR/ADR-019-local-setup-and-native-voice.md).

## Evidências e identificação exata do ambiente

### Local

Linux x86_64, Python 3.13.5, dependências do ambiente — não o lock do CI.

| Execução | Resultado |
|---|---|
| Baseline antes de N20/N22 | 752 passed, 4 skipped, 1 failed |
| Depois de N20/N22 | 767 passed, 4 skipped, 1 failed |
| Setup + memória/contexto/privacidade selecionados | 33 passed |
| Setup após remoção do import redundante | 15 passed |

A única falha da suíte local completa, antes e depois, é o teste SBOM: versões instaladas no ambiente
não correspondem ao lock. O gate **não foi removido**. Ruff/mypy não instalados localmente: instalação
falhou por indisponibilidade de DNS; a validação dessas ferramentas ocorre no CI com o lock.
Verificação de sintaxe Swift local não equivale a compilação dos frameworks macOS.

### GitHub CI

Execução inicial do novo incremento: **36175140693**, head `36bfc47`.

- Linux: **768 passed, 4 skipped**; mypy e segredos passaram.
- macOS 15 ARM64: **771 passed, 1 skipped**; **48 testes Swift, 0 falhas**; mypy e segredos passaram.
- O gate global falhou por F811, import redundante de fixture no teste novo. Corrigido em `cb5bd41`,
  usando a fixture compartilhada já existente, sem mudar asserts nem relaxar configuração.
- O job independente de evidência compilou/abriu o app e capturou o primeiro uso. Isso não valida
  microfone, fala, uso humano ou a jornada completa.
- Nova execução no código corrigido: **36175748947**. Resultado final deve ser conferido no GitHub;
  não é presumido neste registro. A descrição do PR registra a última consulta.

## Capacidades ainda necessárias para cumprir a visão

Continuam pendentes, não apenas aguardando troca de rótulo:

1. VM Linux ARM64, fronteira real de rede e transferência de artefatos no Mac (N14).
2. Execution Box descartável sem acesso a host/segredos (N15).
3. Navegador empacotado, perfis próprios, pesquisa e takeover reais (N16).
4. Contas operacionais e e-mail dedicado com autorização/recibos (N17).
5. Skills com testes, promoção e rollback (N19).
6. Voz natural completa além de ditado revisável/TTS e homologação de áudio em hardware (N20).
7. Companion com pareamento, E2EE, fila offline e revogação (N21).
8. Cifra dos dados em uso, login item/ciclo de vida e acabamento do onboarding (restante N22).
9. Assinatura/notarização, instalação limpa, atualização/recuperação e handover (N23/N24).
10. Avaliações ponta a ponta com modelo realmente autorizado, orçamento e dados sintéticos.

A ausência de credencial ou Mac adequado bloqueia a validação que depende desse recurso, não autoriza
inventar sucesso e não elimina os módulos ainda implementáveis. Corrigir a Alpha e entregar a V1 são
marcos distintos. Não usar navegação pessoal ou shell irrestrito no host para simular autonomia.

## Próxima validação obrigatória

Conferir a nova execução CI; revisar o incremento; testar no bundle real o primeiro uso, reabertura,
privacidade após edição de orçamento, ditado permitido/negado/indisponível, correção da transcrição,
leitura de resposta, parada de fala e parada de tarefas. O produto permanece Alpha e o PR em rascunho
até revisão adequada. Integração à main e publicação de release não são automáticas.
