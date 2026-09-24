# ATLAS — Matriz de capacidades (contrato v2, cap. 27.4)

O que funciona de verdade, separado em **implementado**, **configurado**, **autorizado**, **validado** e
**indisponível**. Atualizado em 2026-09-24 no commit final da sessão (`impl/contract-v2`). Nada aqui foi
validado por uma pessoa usando o app num Mac (D-01) nem com modelo real (D-03).

Legenda da coluna "Validado": INT = testes de integração com classes reais e IPC real; MAC-CI = Swift
compilado/testado no runner macOS 15; E2E-CI = processos reais (daemon/Supervisor) no runner; — = não.

| Capacidade (contrato) | Implementado | Configurado/Autorizado | Validado | Pendência real |
| --- | --- | --- | --- | --- |
| Conversa com intenções (cap. 7) | Sim: controle, resposta com alvo, memória, status, correção, anexar, guardar, delegar, chat | Chat livre só com inteligência configurada | INT, MAC-CI (VM) | Modelo real (D-03); UI por pessoa (D-01) |
| Recibo durável e reenvio idempotente (cap. 5) | Sim (`request_receipts`, envelope imutável no app) | — | INT, MAC-CI (VM) | — |
| Parada prioritária (cap. 6.2) | Sim (`control.stop`, conexão própria no app, botão e ⌘.) | — | INT, MAC-CI (VM) | Latência no Mac de referência (D-01) |
| Correção durante o trabalho (cap. 6.3) | Sim (revisões de instrução, broker recusa proposta obsoleta) | — | INT | — |
| Heartbeat, watchdog, agenda independentes (cap. 6.4) | Sim | — | INT, E2E-CI | — |
| Outbox de notificações (cap. 5.3) | Sim (canal conversa) | E-mail/companion não existem | INT | Canais externos (N17, N21) |
| Memória comum a chat e tarefas (cap. 8.2) | Sim (FTS + radicais + equivalências pt-BR) | — | INT | Índice semântico local (embeddings) ainda não existe |
| Vigência, correção e esquecimento (cap. 8.3-8.4) | Sim (tombstones reaplicados no restore) | — | INT | Tela Memória no app (N06/N12) |
| Classificação e Egress Guard (cap. 9) | Sim (consentimento escopado por provedor/finalidade) | Consentimento sensível: nenhum por padrão | INT | Tela de privacidade no app (N22) |
| Documentos: TXT/MD/CSV/JSON/PDF/DOCX/XLSX/PPTX (cap. 10) | Sim, com localizador e cobertura | — | INT; bundle com libs gerado no CI | OCR/visão (PDF digitalizado, imagens): indisponível |
| Verificação por critério (cap. 13.3) | Sim (integridade, pedido, cálculos, fontes, leitura completa) | — | INT | Revisão de qualidade subjetiva; pesquisa web para fontes URL |
| Geração de entregáveis | TXT/MD/JSON/CSV/HTML | — | INT | PDF/DOCX/XLSX/PPTX como saída (N11) |
| Orçamento vigente e ledger global (cap. 12) | Sim | Tetos: definidos pelo proprietário | INT | Preços verificados com o provedor (D-03) |
| Credencial presa ao destino (cap. 12.4) | Sim (sem redirect, allowlist, loopback só em teste) | Chave: nenhuma registrada | INT | — |
| Validação da inteligência (cap. 11) | Sim, vinculada a chave/endpoint/modelo/capacidade | Nenhuma validação real | INT | Modos Automático/Econômico/Máxima com modelos reais (N13, D-03) |
| Uploads e importação (cap. 14.1) | Sim (sessões compartilhadas, cota, TTL, recibo) | — | INT, MAC-CI (VM) | Arrastar real (D-01) |
| Leitura/exportação de artefatos (cap. 14.2) | Sim (custo linear, nome/extensão reais) | — | INT, MAC-CI (VM) | Painel real (D-01) |
| Instância única e encerramento com prazo (cap. 22.2) | Sim (daemon e Supervisor) | — | INT, E2E-CI, MAC-CI | Saída do app por pessoa (D-01) |
| Workspace VM Linux + mediação de rede (cap. 15) | **Não** | — | — | N14; exige Mac com virtualização (D-01) |
| Execution Box para código novo (cap. 15.2, 17) | **Não** | — | — | N15 |
| Navegador, pesquisa com fontes, takeover (cap. 16) | **Não** | — | — | N16 (depende de N14) |
| Contas e e-mail operacional (cap. 18) | **Não** | — | — | N17 (conta/domínio do proprietário) |
| Pedido de recurso pago / aprovações materiais (cap. 16.5, 12.3) | Aprovações exatas existem no broker | — | INT (broker) | Fluxo CapabilityRequest (N18) |
| Skills com teste/promoção/rollback (cap. 17) | Tabelas existem; ciclo **não** | — | — | N19 |
| Voz (cap. 20) | **Não** | — | — | N20 (modelo de voz e custo a validar) |
| Companion remoto com E2EE (cap. 19) | **Não** | — | — | N21 (relay/domínio) |
| Onboarding leigo, cifra em repouso, login item (cap. 21-23) | Backup cifrado existe; resto **não** | — | INT (backup) | N22 |
| Distribuição assinada/notarizada (cap. 23.3, 28) | Bundle de desenvolvimento ad-hoc | — | E2E-CI (bundle inicia sem Python do sistema) | N23 (D-07) |

**Estado do produto:** Alpha local em correção (G1 e a parte de G2/G3 sem interface foram fechados com
regressões). Não é Beta nem V1.
