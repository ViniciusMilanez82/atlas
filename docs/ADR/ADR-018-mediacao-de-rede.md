# ADR-018 — Mediação de rede única para pesquisa e para o workspace

**Referência:** contrato v2, cap. 9.2, 15 e 16; pacotes N14 (mediação) e N16 (pesquisa); achado R5-08
**Status:** Aceita (parte de mediação e busca por API); VM e navegador pendentes (D-01)
**Data:** 2026-09-25

## Contexto
O contrato proíbe liberar a NIC da VM sem restrição e exige que a pesquisa entregue fontes realmente
recuperadas. A revisão do PR #5 (R5-08) mostrou que "fonte cadastrada" era aceita como "fonte obtida".
Não há Mac neste ambiente para subir a VM (Virtualization.framework), mas a política de saída é a mesma
para qualquer origem de tráfego.

## Alternativas consideradas
1. Deixar a VM e as ferramentas abrirem conexões diretas e filtrar só por lista de domínios — rejeitada:
   DNS rebinding, redirecionamento para rede interna e metadados de nuvem passariam.
2. Proxy HTTP genérico de terceiros dentro do app — rejeitada agora: mais superfície, sem recibos por tarefa.
3. **Mediador próprio no núcleo (`security/network/mediator.py`) usado por `web.fetch` hoje e pelo
   transporte da VM (vsock → proxy) depois** — escolhida.

## Decisão
- Só `http`/`https` nas portas 80/443, sem credenciais na URL; o host é resolvido uma vez e **todos** os
  endereços devem ser públicos (sem loopback, privado, link-local/metadados, CGNAT, multicast, reservado);
  a conexão é fixada nesse IP (TLS continua validando o nome).
- Redirecionamentos nunca são seguidos automaticamente: cada salto passa por todas as checagens (máx. 5).
- A própria URL é dado de saída: formatos de credencial e segredos registrados bloqueiam; o Egress Guard
  classifica a URL para a finalidade `web` (dado sensível não vai para sites).
- Limites: 5 MiB, 20 s por salto, só conteúdo textual.
- Chave do proprietário: `research.web_enabled` (ausente = desligado) e listas `allowed_domains` /
  `blocked_domains` na configuração validada por schema.
- Recibo de toda tentativa em `network_requests` (URL redigida, IP fixado, decisão, motivo, bytes, hash).
- `web.fetch` (N16, "APIs antes de cliques livres") grava a captura como artefato da tarefa e como
  `source_retrievals` (validade padrão 24 h para dados que mudam); só isso torna uma URL citável.

## Consequências
- A VM (N14) e o navegador com perfis/takeover (N16) continuam **não implementados**; quando existirem,
  o tráfego deles deve sair pelo mesmo mediador (transporte a definir no Mac real).
- Teste com servidor local só em modo de teste (`ATLAS_ALLOW_TEST_ENDPOINTS=1`, apenas o endereço literal
  de loopback). Nenhuma chamada real à Internet foi feita nesta etapa.
- Regressões: `tests/integration/test_network_mediation.py`.
