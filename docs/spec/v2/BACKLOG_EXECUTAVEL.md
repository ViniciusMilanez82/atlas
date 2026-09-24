# ATLAS — Backlog executável v2.0

56 itens: 32 correções e 24 pacotes de produto. O contrato principal define o comportamento; este arquivo é um índice, não uma especificação reduzida. Nenhum item está declarado concluído.

| ID | Gate | Prioridade | Item | Cenários |
|---|---|---|---|---|
| A3-01 | G2 | P1 | A conversa livre não recupera a memória duradoura | T04 |
| A3-02 | G1 | P1 | A classificação de dados sensíveis se perde antes da inferência | T08 |
| A3-03 | G1 | P1 | Correções em execução não entram no próximo passo | T19 |
| A3-04 | G1 | P1 | “Pare tudo” pode ser ignorado ou esperar atrás da conversa | T20 |
| A3-05 | G1 | P1 | Lease de 60 segundos pode expirar durante uma chamada válida | T21 |
| A3-06 | G1 | P1 | Resposta estruturada incompleta pode matar o worker sem mudar a saúde | T22 |
| A3-07 | G2 | P1 | “Entrega verificada” não comprova que o objetivo foi atendido | T23 |
| A3-08 | G2 | P2 | A palavra portuguesa “todo” é tratada como placeholder | T23 |
| A3-09 | G2 | P1 | Aceitar PDF/Office/imagem não significa extrair seu conteúdo | T12 |
| A3-10 | G2 | P1 | Documentos e observações longos são truncados silenciosamente | T13 |
| A3-11 | G1 | P1 | Deduplicação de mensagem não recupera processamento interrompido | T16 |
| A3-12 | G1 | P1 | Tarefa pode ser executada antes de todos os anexos serem vinculados | T17 |
| A3-13 | G2 | P2 | Roteamento por palavras-chave captura perguntas que não são status | T03, T10 |
| A3-14 | G2 | P2 | Pergunta pendente captura assuntos novos como se fossem respostas | T10 |
| A3-15 | G2 | P2 | Anexar um arquivo força delegação mesmo quando o usuário só compartilha | T11 |
| A3-16 | G2 | P2 | Corrigir uma memória remove sua validade temporal | T06 |
| A3-17 | G2 | P2 | Excluir memória não elimina cópias usadas no contexto | T07 |
| A3-18 | G1 | P1 | O contexto pode preservar instruções antigas e descartar a atual | T09 |
| A3-19 | G1 | P1 | Reduzir orçamento não atualiza clientes já em execução | T24 |
| A3-20 | G1 | P1 | Transporte HTTP precisa vincular credenciais ao destino final | T26 |
| A3-21 | G3 | P2 | Arrastar vários arquivos pode importar apenas o primeiro | T14 |
| A3-22 | G1 | P2 | Reenvio não conserva todo o payload original | T15 |
| A3-23 | G3 | P2 | Atualização do histórico não reconcilia mensagens existentes nem lacunas | T03, T15 |
| A3-24 | G1 | P2 | Uploads têm coordenação e limpeza incompletas | T14, T15 |
| A3-25 | G3 | P3 | Leitura em chunks relê e recalcula hash do arquivo inteiro | T32 |
| A3-26 | G1 | P2 | Algumas referências por ID não validam o proprietário completo | T27 |
| A3-27 | G1 | P2 | Notificação pode se perder depois de a tarefa mudar de estado | T18 |
| A3-28 | G1 | P2 | Inicialização não demonstra exclusão mútua entre instâncias | T28 |
| A3-29 | G1 | P2 | Validação da inteligência sobrevive indevidamente à troca de credencial | T29 |
| A3-30 | G3 | P2 | Os botões de controle não refletem os estados realmente aceitos | T30 |
| A3-31 | G3 | P2 | Encerrar serviços ainda pode bloquear a interface sem prazo | T31 |
| A3-32 | G3 | P3 | Salvar resultado não preserva o nome e a extensão do arquivo | T32 |
| N01 | G0 | OBRIGATORIO_V1 | Adotar contrato, baseline e rastreabilidade | Baseline e primeira regressão |
| N02 | G1 | OBRIGATORIO_V1 | Authority Core e transporte de controle | T08, T19, T20, T27 |
| N03 | G1 | OBRIGATORIO_V1 | Inbox, transações e outbox recuperáveis | T15, T16, T17, T18 |
| N04 | G1 | OBRIGATORIO_V1 | Supervisão, leases e agenda independente | T21, T22, T28, T31 |
| N05 | G1 | OBRIGATORIO_V1 | Cofre, egress e orçamento dinâmico | T08, T24, T25, T26, T29 |
| N06 | G2 | OBRIGATORIO_V1 | Contexto comum e conhecimento duradouro | T04, T05, T07, T09 |
| N07 | G2 | OBRIGATORIO_V1 | Intenções, perguntas e continuidade | T03, T10, T11, T19 |
| N08 | G2 | OBRIGATORIO_V1 | Documentos e extração por formato | T12, T13 |
| N09 | G2 | OBRIGATORIO_V1 | Datas, unidades e cálculos verificáveis | T06, T23 |
| N10 | G2 | OBRIGATORIO_V1 | Planner, contratos de ferramenta e critérios | T19, T22, T23 |
| N11 | G3 | OBRIGATORIO_V1 | Artefatos, uploads e exportação | T14, T15, T32 |
| N12 | G3 | OBRIGATORIO_V1 | Interface local completa e reconciliação | T03, T10, T30, T31 |
| N13 | G4 | OBRIGATORIO_V1 | Homologar inteligência e modos | T04, T19, T20, T23, T24, T29 |
| N14 | G5 | OBRIGATORIO_V1 | Workspace Linux ARM64 e mediação | T02, T33 |
| N15 | G5 | OBRIGATORIO_V1 | Execution Box e código gerado | T33, T37 |
| N16 | G5 | OBRIGATORIO_V1 | Browser, pesquisa e tela de trabalho | T34, T35 |
| N17 | G6 | OBRIGATORIO_V1 | Identidade operacional, contas e e-mail | T36 |
| N18 | G6 | OBRIGATORIO_V1 | Solicitações de recursos e ações materiais | T25, T36 |
| N19 | G6 | OBRIGATORIO_V1 | Aprendizado e ciclo de skills | T37 |
| N20 | G7 | OBRIGATORIO_V1 | Conversa por voz | T38 |
| N21 | G7 | OBRIGATORIO_V1 | Companion remoto e canal seguro | T18, T39 |
| N22 | G8 | OBRIGATORIO_V1 | Onboarding leigo, privacidade e recuperação | T01, T02, T07, T31, T40 |
| N23 | G9 | OBRIGATORIO_V1 | Build, atualização e distribuição | T01, T31, T40 |
| N24 | G10 | OBRIGATORIO_V1 | Aceite integrado e entrega V1 | T01–T40 |

## Regra de execução

Criar subtarefas quando necessário, preservando ID de origem e requisito. Fechar cada item somente com commit e evidência real. Mock, teste ignorado e inspeção estática devem permanecer diferenciados. Validar o arquivo JSON no pipeline; não convertê-lo automaticamente em issues remotas sem autorização de escrita.
