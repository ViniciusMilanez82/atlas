# ATLAS — Operações

Este documento cresce com o produto. Hoje cobre só o que o núcleo Python já faz.

## 1. Três operações distintas (spec 3.4)

| Operação | Efeito | Implementação |
| --- | --- | --- |
| Fechar a janela | Serviços autorizados continuam | Depende do app e do Supervisor (M4, requer Mac) |
| Pausar o funcionário | Nenhum novo passo é despachado | `TaskEngine.pause_all` / `stop_all` (runtime/tasks) |
| Encerrar todos os serviços | Runtime e workspace param após checkpoints | Supervisor (M4, requer Mac) |

## 2. Parada de emergência ("pare tudo")

`TaskEngine.stop_all(actor)` revoga todos os leases (o fencing token avança), move tarefas
ativas para PAUSED e registra evento. A partir desse commit, o broker recusa qualquer despacho
com token antigo. Efeitos já aceitos por provedores externos **não** são desfeitos.

## 3. Recuperação após falha

`recover_after_restart()` executa, nesta ordem: expira leases vencidos; marca ações em
DISPATCHING como UNKNOWN (não se sabe se o efeito ocorreu); bloqueia as tarefas afetadas com
`EXTERNAL_EFFECT_UNKNOWN`; e só então devolve a READY as tarefas sem pendência. Nenhuma ação é
repetida automaticamente.

## 4. Backup e restauração

`storage.backup.create_backup` gera cópia consistente (API de backup do SQLite) e manifesto com
SHA-256, versão de schema e contagem de linhas. `restore_backup` confere hash e versão antes de
restaurar e, depois, **revoga** aprovações APPROVED/RESERVED e mandatos ativos, porque um backup
antigo poderia repetir efeitos (spec 12.4). Com chave, o backup é cifrado (AES-256-GCM) e a cópia em claro é removida. **Sem a chave não há restauração**: a chave deve ficar no Keychain e ter cópia de recuperação sob controle do proprietário.

## 5. Retenção (propostas da spec 16.2, ainda não automatizadas)

Logs operacionais detalhados: 30 dias. Screenshots: só os necessários à evidência. Áudio bruto:
não retido após processamento. A automação dessas regras é tarefa do backlog (AT-013/AT-019).

## 6. Memória

Excluir uma memória apaga o conteúdo de todas as suas versões e as entradas do índice derivado.
O registro da exclusão continua no journal, sem o conteúdo. Backups feitos antes da exclusão
ainda contêm o texto; a interface precisa avisar isso (spec 16.3). O índice FTS5 pode ser
reconstruído a qualquer momento com `MemoryManager.rebuild_index()`.

## 7. Tarefas recorrentes

Com o computador desligado, ocorrências vencidas não são repetidas uma a uma. A política padrão
consolida tudo numa única tarefa e, se ela tiver efeito externo, aguarda confirmação do
proprietário (estado WAITING_USER).

## 8. App de desenvolvimento (Atlas.app)

O CI macOS publica `Atlas-dev.zip` (artefato **Atlas-dev-app** de cada execução). É um pacote Apple
Silicon, com assinatura apenas ad-hoc e **sem notarização**: o macOS pede confirmação na primeira
abertura (clique com o botão direito em Atlas.app e escolha Abrir).

| Ação | Efeito |
| --- | --- |
| Fechar a janela | Os serviços continuam |
| Pare tudo (menu Funcionário, Cmd+.) | Pausa as tarefas e pede a parada das ações em andamento |
| Encerrar serviços, ou sair do app | Encerra o núcleo e o serviço de Keychain |

Dados ficam em `~/Library/Application Support/Atlas`. Para usar um modelo real:
1. Em Configurações, guarde a chave no Keychain.
2. Salve os tetos de orçamento.
3. Rode "Testar inteligência".

Sem esses três passos, as tarefas ficam na fila e o Diagnóstico mostra o motivo.
