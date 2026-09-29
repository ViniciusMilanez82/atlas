# Tarefa 1 — uma base, uma fila de trabalho

## O que esta entrega faz

Estabelece `integration/atlas-base-unificada` como base única de continuação. Não refaz o aplicativo,
não altera código de produção e não instala nada no computador do dono. O produto permanece Alpha.
A identidade, os dados, o banco e a chave já cadastrada não são lidos nem modificados nesta tarefa.

O HEAD do PR14 já contém a sequência main/PR6 → PR7 → PR9 → PR13 → PR14. A consolidação conserva essa
ancestralidade real em vez de copiar arquivos por cima da main ou executar merges desnecessários.
O workflow verifica a cadeia e recusa alterações de runtime, testes existentes, dependências,
empacotamento ou contrato que não pertencem à tarefa 1. A main observada é fixada no manifesto;
se ela avançar durante a aceitação, a divergência exige revisão, não reset nem force-push.

## Origem e decisões

`lineage.json` é o manifesto da seleção: commits completos, árvore original, arquivo fonte conferido,
ancestrais incluídos e heads excluídos. Os PRs antigos e seus históricos permanecem abertos/intactos;
esta entrega não integra automaticamente a main nem fecha discussões anteriores.

- PR7, PR9, PR13 e PR14: mantidos por ancestralidade da revisão `720be87`.
- PR8: linha alternativa, não mesclada automaticamente. O comportamento de configuração/voz selecionado
  é o da cadeia PR7/PR14; não se afirma equivalência completa entre implementações.
- PR10: componente experimental sem integração Mac entregue; não entra nesta base.
- PR11: falhas de compilação/análise e bloqueios registrados; não entra nesta base.
- verified-procedures e o ZIP local anterior: não substituem a origem Git verificada. A organização
  desta entrega é a fonte operacional a usar; os arquivos anteriores continuam preservados fora dela.

Restrições anteriores de publicação não são resolvidas por consolidar, renomear, copiar ou empacotar.
As tarefas afetadas ficam bloqueadas até o tratamento autorizado. Não usar o desktop pessoal como
substituto da VM. Nenhum código dessas integrações é republicado aqui.

## Registro único

`state.json` atribui cada um dos 56 itens normativos (32 A3 e 24 N) a exatamente uma das 12 tarefas.
Os 40 cenários T01–T40 são relacionados sem perda de cobertura. Os estados são de implementação:
`implemented`, `partial`, `blocked`, `not_implemented`. Não significam homologação com provedor,
validação humana, segurança certificada ou V1 pronta. O aceite da tarefa 1 exige o CI desta revisão.

Responsáveis são papéis de trabalho, não processos em execução. Há um coordenador e oito especialidades.
Não foram iniciados subagentes nesta entrega. Nenhum registro de progresso inventado é aceito como teste.

Antes de um trabalho concorrente, o coordenador registra em `active_assignments` a tarefa, seu responsável
e cada arquivo de escrita. O validador recusa tarefas inexistentes, responsável incorreto, curingas,
caminhos fora do repositório e reservas sobrepostas. Uma reserva é coordenação de desenvolvimento,
não um sandbox nem autorização de acesso a dados pessoais. A reserva deve ser revisada e commitada
antes do despacho do agente. Remover somente ao concluir ou devolver a tarefa ao coordenador.

## Verificação e aceitação

1. `python scripts/check_consolidation.py`: registro, dependências, cobertura e reservas; offline.
2. `python -m pytest -q tests/regression/test_project_consolidation.py`: regressões do registro.
3. `python scripts/check_consolidation.py --foundation`: também prova ancestralidade, tree, exclusões,
   worktree limpo, main sem divergência e ausência de alterações de runtime. Exige clone com histórico;
   o arquivo ZIP sem `.git` não pode satisfazer essa prova nem deve simular o SHA original.
4. Workflow `ci` no mesmo commit: lint, tipos, segredos, testes Python Linux/macOS, compilação Swift,
   testes Swift, empacotamento do aplicativo e inicialização com runtime embutido.

O workflow `consolidation` usa clone com histórico completo e produz relatório da origem e arquivo
fonte único `Atlas_Base_Unificada.zip`. Seu PASS sozinho não substitui o workflow `ci`. A fonte é
candidata até ambos terminarem; não é um novo instalador nem a entrega da tarefa 12.

Os testes pagos continuam opt-in. Não tentar usar a chave do proprietário a partir do CI. As tarefas
2–12 preservam sua validação própria; não serão marcadas como concluídas por herdar testes da Alpha.

## Continuação

Abrir novas branches a partir desta base aprovada. Não misturar os PRs experimentais por conveniência.
No início de cada tarefa conferir HEAD, pendências e reservas; implementar e revisar o incremento;
executar os testes afetados e o CI; atualizar este registro sem reescrever o contrato nem apagar
histórico. `--foundation` verifica somente a base inicial congelada; não é um bloqueio permanente a
mudanças legítimas nas tarefas seguintes. Essas mudanças exigirão seus próprios testes de regressão.
