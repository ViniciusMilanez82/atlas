# ADR-017 — Época de controle: "pare tudo" também invalida interpretações pendentes

**Referência:** contrato v2, cap. 5 e 6.2; achados A3-04 e R5-03 (revisão do PR #5)
**Status:** Aceita
**Data:** 2026-09-25

## Contexto
O `stop_all` pausava as tarefas existentes e incrementava `employees.control_epoch`, mas um pedido que
ainda estava sendo interpretado pelo modelo publicava a tarefa depois da parada, e o worker a executava.
A confirmação "parei" não cobria efeitos originados antes dela.

## Alternativas consideradas
1. Bloquear toda publicação por um tempo após STOP — rejeitada: arbitrária e perde pedidos novos.
2. Descartar o resultado tardio — rejeitada: o pedido do proprietário sumiria sem explicação.
3. Vincular cada pedido e cada tarefa à época de controle e comparar na publicação, no lease e no
   despacho — escolhida.

## Decisão
- `request_receipts.control_epoch`: a época em vigor quando o pedido foi **recebido** (gravada na mesma
  transação do recibo e da mensagem). Um pedido retomado (reenvio após falha/reinício) mantém a época
  original; recibos pendentes de antes da migração ficam com época 0 (conservador).
- `tasks.control_epoch`: a época sob a qual o proprietário autorizou a tarefa. Na publicação
  (`TaskEngine.create`), época do pedido < época atual ⇒ a tarefa é gravada **PAUSED** (`paused_from =
  CREATED`), com registro no diário e resposta explicando que nada foi iniciado. Subtarefas herdam a
  época da tarefa-mãe.
- Lease: tarefa READY com época antiga nunca recebe lease; é movida para PAUSED. Despacho: o broker
  confere a época dentro da transação de despacho (`check_lease_in_txn`), além do fencing token.
- Retomada: qualquer transição feita pelo **proprietário** para um estado não pausado (retomar,
  reavaliar bloqueio, responder, decidir pedido de recurso) autoriza a tarefa na época atual.
  Transições do sistema (watchdog, recuperação após reinício) nunca atualizam a época.

## Semântica
| Situação | Resultado |
|---|---|
| Pedido recebido depois do STOP | Trabalho novo, autorizado normalmente |
| Resultado tardio de interpretação iniciada antes do STOP | Tarefa publicada PAUSADA, visível e retomável |
| Saudação ou conversa após STOP | Não libera nada da fila |
| Retomada explícita da tarefa | Executável na época atual |
| Reinício do serviço | Tarefas pausadas continuam pausadas |

A parada não é irreversível e não apaga pedidos; apenas impede que efeitos antigos comecem depois dela.

## Consequências
- Rotinas agendadas e subtarefas passam pelo mesmo lease/despacho e ficam cobertas pela checagem.
- Ações já em voo no momento do STOP continuam relatadas como "já enviadas" (A3-04), sem desfazer.
- Regressões: `tests/regression/test_r5_03.py` (quatro pontos de intercalação, duas conexões IPC reais,
  subtarefa e reinício). Validação do botão/atalho no Mac segue pendente (D-01).
