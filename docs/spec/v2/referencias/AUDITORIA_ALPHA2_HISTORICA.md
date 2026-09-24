# ATLAS — Auditoria da Alpha 2 e aderência à visão do produto

**Preparado para:** Vinícius Milanez  
**Data da revisão:** 24 de setembro de 2026  
**Versão revisada:** `v0.1.0-alpha.2`  
**Commit fixado:** `d81cece2713ccb5b12e58902e55b05a614467951`  
**Repositório:** https://github.com/ViniciusMilanez82/atlas  
**Natureza:** revisão técnica independente, sem alteração do repositório.

## 1. Parecer executivo

O projeto evoluiu e contém trabalho aproveitável. A Alpha 2 acrescentou conversa persistente, anexos e exportação, chamadas de interface assíncronas, reconexão, revisão correta de configurações e controles adicionais de inferência. **Ainda não corresponde ao funcionário digital generalista, independente e simples de usar definido pelo proprietário.** Há lacunas de escopo reconhecidas e defeitos nos percursos já implementados.

A recomendação é preservar o repositório e corrigir os fundamentos antes de ampliar privilégios, usar dados sensíveis ou declarar beta. Não confundir uma interface que compila com um funcionário autônomo homologado; também não confundir os defeitos abaixo com ausência total de trabalho útil.

Foram registrados **32 achados técnicos**: 14 P1, 16 P2 e 2 P3. Eles incluem defeitos identificáveis pelo código, riscos condicionais e oportunidades necessárias de correção. **Não são 32 explorações demonstradas nem uma garantia de localizar todos os bugs possíveis.** As funcionalidades ainda ausentes estão em seção própria, sem inflar a contagem de defeitos.

## 2. Método, evidência e limites

A revisão consultou a release, a tag, a branch principal, o patch do PR 4, o progresso, contratos relevantes e arquivos centrais do commit fixado. A tag e a branch principal apontavam para o commit acima na consulta. A especificação original foi consultada, inclusive requisitos de memória e ContextBuilder. A revisão anterior da Alpha 1 foi usada para conferir continuidade, não para presumir o estado atual.

### 2.1 O que foi realmente executado

Foram executados localmente **20 casos/observações isolados**, incluindo controles positivos, sobre expressões regulares, SQL/projeções, cortes de texto, seleção de contexto, tipos de resposta e construção de redirecionamento HTTP. Os scripts e resultados estão em `probes/`. Os fragmentos foram transcritos do código consultado e usam dados sintéticos. Esses casos não equivalem à suíte completa nem demonstram funcionamento do aplicativo.

**Não foi executado localmente:** Atlas.app, compilação Swift, VM, uso humano do Mac, cenários end-to-end completos, chamadas a um modelo real ou exploração de uma instância do usuário. Não houve gasto de API nem envio de credenciais reais. Nenhuma alteração, issue, commit ou PR foi publicado por esta auditoria.

Não foi possível clonar/baixar o projeto pelo ambiente de execução por indisponibilidade de acesso de rede desse ambiente; a leitura de código foi realizada pelo conector GitHub. Portanto, não se afirma uma execução local da suíte do repositório. O teste de redirect usa Python 3.13.5 do ambiente de auditoria, não o Python embutido do bundle; repetir a verificação nessa versão é obrigatório.

### 2.2 Evidência de CI consultada

Execução do GitHub Actions: https://github.com/ViniciusMilanez82/atlas/actions/runs/36011007155  
Job macOS: `107671400012`; commit do checkout: `d81cece2713ccb5b12e58902e55b05a614467951`.

O log consultado registra **24 testes Swift aprovados** e **452 testes Python aprovados, 1 ignorado**. O ignorado é a chamada opt-in ao provedor real. Ruff e mypy passaram; a varredura utilizada pelo projeto informou zero achados nos arquivos cobertos — isso não é garantia de ausência universal de segredos. Houve compilação e verificação de início do bundle com Python embutido. O job visual abriu a aplicação e capturou uma janela, mas isso não é um teste interativo dos fluxos completos; seu passo usa `continue-on-error`.

Os testes de conversa/inteligência documentados empregam provedores ou transportes controlados. Eles são úteis para os contratos que cobrem; não comprovam qualidade, autonomia ou custo com o modelo real. Os logs também contêm avisos de concorrência Swift em testes, relevantes para migração de modo de linguagem, sem terem impedido esse build.

### 2.3 Distribuição

Release: https://github.com/ViniciusMilanez82/atlas/releases/tag/v0.1.0-alpha.2  
Asset anunciado: `Atlas-0.1.0-alpha.2-dev-arm64.zip`, 36.910.348 bytes.  
SHA-256 **informado pelo GitHub, não recalculado nesta auditoria**: `9c4d6b47f8f389f8cd66324ff63ab24983b800565cd25978cc32a23b33631b1c`.

A release é de desenvolvimento, Apple Silicon, com homologação documentada apenas no runner macOS 15, assinatura ad-hoc e sem notarização. O protocolo de produto não deve prometer instalação final sem atrito a partir disso. Não se recomenda desabilitar proteções globais do Mac.

## 3. Comparação com o que foi solicitado

O proprietário quer uma única identidade conversacional em um computador dedicado ao empregado; contas, memória, arquivos e ambiente próprios; autonomia para escolher meios, com pedidos de autorização quando necessário. Não é um módulo de viagens, calendário familiar ou gestão empresarial específico.

| Requisito original | Situação observada na Alpha 2 | Critério para considerar atendido |
|---|---|---|
| Instalar e usar sem conhecimento técnico | Pacote existe; chave/API, modelo exato, preços de referência e validações ainda exigem entendimento | Onboarding testado com leigo, diagnóstico claro, build assinada/notarizada para distribuição |
| Conversar como com um funcionário | Histórico e respostas existem, mas há roteamento frágil, janela curta e pergunta pendente ambígua | Conversas livres, correções e múltiplas tarefas coerentes por sessões e reinícios |
| Memória duradoura comum a toda interação | Banco e FTS existem; chat livre não recupera a memória | Recuperação testada fora do histórico recente, com fonte e filtros |
| Computador e navegador próprios isolados | Workspace/VM/browser declarados indisponíveis | Guest funcional, isolamento e testes que neguem acesso ao host |
| Resolver objetivos gerais na internet | Só três ferramentas internas estão registradas na rota atual | Pesquisa e ferramentas reais, dentro do workspace e das permissões |
| Criar e usar contas operacionais próprias | Não há fluxo funcional documentado e validado | Contas sob responsabilidade autorizada, credenciais escopadas, ações rastreáveis |
| Entender documentos do usuário | Importa diversos formatos; execução só decodifica bytes como UTF-8 | Extração por formato, tabelas/páginas/células e cobertura comprovadas |
| Pedir autorização e continuar | Núcleo de políticas existe; muitas ações externas ainda não existem | Pedido exato, decisão autenticada e retomada sem repetir efeitos |
| Trabalhar durante conversa/fechamento de janela | Serviços e recuperação parcial existem; há falhas de parada, leases e worker | Testes de interrupção, longa duração, reconexão e saúde do executor |
| Falar por voz e receber pelo celular | Declarados pendentes | Voz natural e um canal remoto real, pareado e seguro |
| Aprender procedimentos e instalar novas ferramentas com segurança | Não demonstrado nesta release | Skills versionadas, sandbox/VM, validação, promoção e rollback |
| Ver o funcionário trabalhando | Sem workspace real não há tela de trabalho real | Visualização do guest com pausa e takeover, sem simulação de progresso |

Uma Alpha pode deliberadamente adiar parte da V1. O problema não é o rótulo Alpha, e sim apresentar essas lacunas como se a visão já tivesse sido entregue.

## 4. Avanços que devem ser preservados

- `settings.get` e revisão retornada ao app corrigem o erro básico de salvar configurações repetidamente.
- Conversa ganhou histórico, mensagens de tarefa e vínculos com perguntas/entregáveis, substituindo a antiga caixa sem respostas.
- `AtlasConnection` tira o socket da thread principal e reabre sessão após queda, com política explícita de reenvio.
- Anexos têm cópia explícita, limites, hash e exportação conferida; prévia HTML não executa o documento.
- Catálogo de ferramentas agora chega ao modelo com descrição e schema de entrada.
- A retomada restaura observações e respostas já persistidas, em vez de sempre iniciar um plano vazio.
- Testar inteligência passou a usar o ledger global e há aviso/consentimento para preços de referência não verificados.
- O cofre Keychain e os testes de Supervisor/IPC tiveram progresso real.

Esses itens têm limites expostos nos achados; preservar a correção existente e acrescentar os casos de falha, sem reescrever tudo do zero.

## 5. Convenções dos achados

**P1:** corrigir antes de considerar a Alpha confiável para os percursos afetados, especialmente dados sensíveis, controle de execução e gastos. Não é uma pontuação formal de vulnerabilidade. **P2:** erro funcional, robustez ou isolamento condicional que precisa entrar na próxima rodada. **P3:** eficiência/usabilidade, sem a mesma urgência dos controles anteriores.

**ESTÁTICA:** constatação pela leitura; efeitos condicionais precisam de teste integrado. **ISOLADO:** expressão/SQL/fragmento executado em ambiente sintético, não Atlas.app. A existência de um caminho vulnerável não significa que tenha sido explorado ou que dados tenham vazado.

## 6. Quadro de achados

| ID | Prioridade | Achado | Evidência |
|---|---|---|---|
| A3-01 | P1 | A conversa livre não recupera a memória duradoura | ESTÁTICA |
| A3-02 | P1 | A classificação de dados sensíveis se perde antes da inferência | ESTÁTICA + SQL ISOLADO |
| A3-03 | P1 | Correções em execução não entram no próximo passo | ESTÁTICA |
| A3-04 | P1 | “Pare tudo” pode ser ignorado ou esperar atrás da conversa | ESTÁTICA |
| A3-05 | P1 | Lease de 60 segundos pode expirar durante uma chamada válida | ESTÁTICA; REPRODUÇÃO INTEGRADA PENDENTE |
| A3-06 | P1 | Resposta estruturada incompleta pode matar o worker sem mudar a saúde | ESTÁTICA + FRAGMENTO ISOLADO |
| A3-07 | P1 | “Entrega verificada” não comprova que o objetivo foi atendido | ESTÁTICA + VERIFICAÇÕES DE CONTEÚDO ISOLADAS |
| A3-08 | P2 | A palavra portuguesa “todo” é tratada como placeholder | REGEX ISOLADA REPRODUZIDA |
| A3-09 | P1 | Aceitar PDF/Office/imagem não significa extrair seu conteúdo | ESTÁTICA |
| A3-10 | P1 | Documentos e observações longos são truncados silenciosamente | ESTÁTICA + CORTE DE TEXTO ISOLADO |
| A3-11 | P1 | Deduplicação de mensagem não recupera processamento interrompido | ESTÁTICA |
| A3-12 | P1 | Tarefa pode ser executada antes de todos os anexos serem vinculados | ESTÁTICA; CORRIDA A REPRODUZIR |
| A3-13 | P2 | Roteamento por palavras-chave captura perguntas que não são status | REGEX ISOLADA REPRODUZIDA |
| A3-14 | P2 | Pergunta pendente captura assuntos novos como se fossem respostas | ESTÁTICA |
| A3-15 | P2 | Anexar um arquivo força delegação mesmo quando o usuário só compartilha | ESTÁTICA |
| A3-16 | P2 | Corrigir uma memória remove sua validade temporal | SQL ISOLADO REPRODUZIDO |
| A3-17 | P2 | Excluir memória não elimina cópias usadas no contexto | ESTÁTICA |
| A3-18 | P1 | O contexto pode preservar instruções antigas e descartar a atual | FRAGMENTO ISOLADO + ESTÁTICA |
| A3-19 | P1 | Reduzir orçamento não atualiza clientes já em execução | ESTÁTICA; TESTE CONCORRENTE PENDENTE |
| A3-20 | P1 | Transporte HTTP precisa vincular credenciais ao destino final | ESTÁTICA + CONSTRUÇÃO DE REQUEST ISOLADA; CONDICIONAL |
| A3-21 | P2 | Arrastar vários arquivos pode importar apenas o primeiro | ESTÁTICA; REPRODUÇÃO VISUAL PENDENTE |
| A3-22 | P2 | Reenvio não conserva todo o payload original | ESTÁTICA |
| A3-23 | P2 | Atualização do histórico não reconcilia mensagens existentes nem lacunas | ESTÁTICA |
| A3-24 | P2 | Uploads têm coordenação e limpeza incompletas | ESTÁTICA; TESTE CONCORRENTE PENDENTE |
| A3-25 | P3 | Leitura em chunks relê e recalcula hash do arquivo inteiro | ESTÁTICA + CÁLCULO |
| A3-26 | P2 | Algumas referências por ID não validam o proprietário completo | ESTÁTICA; AMEAÇA CONDICIONAL A MÚLTIPLAS IDENTIDADES |
| A3-27 | P2 | Notificação pode se perder depois de a tarefa mudar de estado | ESTÁTICA |
| A3-28 | P2 | Inicialização não demonstra exclusão mútua entre instâncias | ESTÁTICA; TESTE DE DUAS INSTÂNCIAS PENDENTE |
| A3-29 | P2 | Validação da inteligência sobrevive indevidamente à troca de credencial | ESTÁTICA |
| A3-30 | P2 | Os botões de controle não refletem os estados realmente aceitos | ESTÁTICA |
| A3-31 | P2 | Encerrar serviços ainda pode bloquear a interface sem prazo | ESTÁTICA; REPRODUÇÃO MAC PENDENTE |
| A3-32 | P3 | Salvar resultado não preserva o nome e a extensão do arquivo | ESTÁTICA |
### A3-01 — A conversa livre não recupera a memória duradoura

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::_chat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`runtime/memory/manager.py::search`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/memory/manager.py)

**O que foi encontrado.** _chat consulta somente as últimas 20 mensagens. Não chama a busca de memórias nem oferece uma ferramenta de recuperação à conversa. A busca existente no AgentRunner não supre esse caminho. Uma confirmação de memória pode estar no histórico recente e dar a impressão de lembrança, mas isso não é recuperação duradoura.

**Impacto para o usuário.** Depois de o assunto sair dessa janela, perguntas sobre preferências ou informações guardadas podem receber resposta sem a memória relevante. É incompatível com a continuidade que o proprietário pediu.

**Correção esperada.** Criar um serviço de contexto comum a conversa e tarefas: recuperar memórias pertinentes, com classificação, fonte, validade e confirmação. Preservar identidade e preferências aplicáveis mesmo quando o vocabulário da pergunta muda. Não despejar o banco inteiro no modelo.

**Teste de aceitação obrigatório.** Guardar e confirmar fato sintético; inserir mais de 20 mensagens; reiniciar; perguntar com paráfrase. Verificar que a fonte correta chega ao contexto, que a resposta a utiliza e que uma memória não confirmada não vira autoridade.


### A3-02 — A classificação de dados sensíveis se perde antes da inferência

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA + SQL ISOLADO

**Arquivos e símbolos no commit revisado:**
- [`runtime/memory/manager.py::MemoryHit/search`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/memory/manager.py)
- [`runtime/agent/loop.py::_context/_decide`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)
- [`core/conversation.py::_remember/_chat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`runtime/models/context.py::ContextItem`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/context.py)
- [`runtime/models/router.py::candidates`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/router.py)
- [`runtime/tools/builtin.py::search_memory`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tools/builtin.py)

**O que foi encontrado.** MemoryHit e a projeção SQL não carregam sensitivity. O AgentRunner transforma o conteúdo recuperado em ContextItem com classificação padrão INTERNAL. O requisito de consentimento do roteador olha data_classification, normalmente INTERNAL na tarefa. A conversa também incorpora o texto de confirmações sensíveis no histórico sem preservar essa classificação. Importações iniciam como INTERNAL sem um percurso de classificação no app.

**Impacto para o usuário.** Conteúdo marcado SENSITIVE pode alcançar uma requisição à nuvem como dado comum, sem acionar a barreira de consentimento específica. A prova isolada confirmou a perda do atributo; nenhuma transmissão de dados reais foi feita nesta auditoria.

**Correção esperada.** Propagar classificação e proveniência em mensagens, memórias, anexos, observações, resumos e entregáveis. Calcular a classificação agregada do contexto efetivamente enviado e aplicar um controle de saída independente do LLM imediatamente antes do transporte. Confirmar uma memória não deve equivaler a autorizar sua divulgação à nuvem.

**Teste de aceitação obrigatório.** Usar sentinela sintética SENSITIVE em memória e anexo: sem consentimento, nenhuma chamada ao provedor deve conter a sentinela. Com consentimento escopado, transmitir somente o necessário. Repetir após resumo, correção, retomada, mensagem de confirmação e troca de provedor.


### A3-03 — Correções em execução não entram no próximo passo

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::handle (correction)`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`runtime/agent/loop.py::_owner_messages/_resume_state/_context/run`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)

**O que foi encontrado.** A correção é persistida como mensagem vinculada à tarefa e recebe confirmação de que será considerada. Entretanto, as respostas e correções são carregadas em _resume_state; o laço em andamento usa observations já montadas e não consulta novas mensagens a cada passo. A seleção automática da tarefa mais recente ainda pode associar a correção ao trabalho errado.

**Impacto para o usuário.** O usuário pode mudar uma condição e o funcionário continuar trabalhando com o pedido antigo. No futuro, isso é especialmente perigoso antes de efeitos externos.

**Correção esperada.** Versionar instruções por tarefa, vincular explicitamente a tarefa alvo e detectar alteração antes de cada inferência e despacho. Uma correção material deve invalidar propostas antigas e exigir replanejamento/reaquisição da autorização pertinente; preservar o que já aconteceu.

**Teste de aceitação obrigatório.** Pausar um provedor falso entre decisão e execução, enviar correção por outra conexão e liberar. A ação antiga não pode ocorrer. O próximo contexto deve conter a correção, sem novo task_id e sem repetição de efeitos já confirmados.


### A3-04 — “Pare tudo” pode ser ignorado ou esperar atrás da conversa

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::stopAll/send/deliver`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasConnection.swift::call/callSync`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasConnection.swift)

**O que foi encontrado.** stopAll chama send("pare tudo"). send retorna sem fazer nada quando isSending é true. Além disso, o transporte usa uma única fila serial: comandos de controle compartilham a fila com inferências, leituras e reconexões demoradas.

**Impacto para o usuário.** O botão ou atalho de emergência pode não interromper justamente quando o sistema está ocupado. Tirar I/O da thread principal resolveu congelamento de janela, mas não garantiu preempção de controle.

**Correção esperada.** Implementar canal de controle prioritário e independente, que não dependa de isSending, do modelo ou da fila de conversas. Registrar a ordem de parada, revogar leases, interromper ferramentas/chamadas canceláveis e informar efeitos já ocorridos ou incertos.

**Teste de aceitação obrigatório.** Com envio pendente, provedor sem resposta, upload em andamento e reconexão, acionar o mesmo botão/atalho do app. Medir recebimento da parada e ausência de novos despachos; não aceitar apenas uma mudança visual ou resposta textual.


### A3-05 — Lease de 60 segundos pode expirar durante uma chamada válida

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA; REPRODUÇÃO INTEGRADA PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`runtime/tasks/engine.py::DEFAULT_LEASE_TTL/check_lease_in_txn/heartbeat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tasks/engine.py)
- [`runtime/models/types.py::ModelRequest`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/types.py)
- [`runtime/agent/loop.py::run/_run_tool`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)
- [`core/daemon.py::worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)

**O que foi encontrado.** O lease padrão é de 60 segundos e o heartbeat ocorre antes da chamada ao modelo. O timeout padrão da requisição também é de 60 segundos, não um prazo total garantido do turno. Depois da expiração, até release/heartbeat são recusados. O worker seleciona apenas CREATED/READY e não reconcilia RUNNING vencido continuamente.

**Impacto para o usuário.** Uma tarefa pode ficar eternamente marcada RUNNING, sem executor elegível, após latência, timeout ou perda de lease. O resultado depende da duração efetiva da chamada; não foi reproduzido no Mac.

**Correção esperada.** Renovar o lease por supervisor independente do trabalho bloqueante, com fencing e limite total; adicionar watchdog de leases expirados que reconcilie efeitos e retome com segurança. Não resolver somente aumentando o TTL.

**Teste de aceitação obrigatório.** Com relógio injetável, fazer a inferência ultrapassar o TTL; cobrir resposta tardia, cancelamento, queda e trabalhador obsoleto. A tarefa deve terminar em estado explícito e recuperável, sem ação duplicada nem RUNNING sem heartbeat.


### A3-06 — Resposta estruturada incompleta pode matar o worker sem mudar a saúde

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA + FRAGMENTO ISOLADO

**Arquivos e símbolos no commit revisado:**
- [`runtime/agent/loop.py::_decide/run/_validate`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)
- [`core/conversation.py::_chat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`core/daemon.py::worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)
- [`core/service.py::_health`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/service.py)

**O que foi encontrado.** O contrato completo DECISION_SCHEMA não é validado localmente antes do uso. _decide valida apenas objeto e enum; summary nulo ou numérico passa por esse filtro e falha em [:300] antes de _validate. _chat também usa decision.get após json.loads sem validar o objeto inteiro. O worker captura apenas AtlasError e a saúde não verifica a thread.

**Impacto para o usuário.** Uma falha do adaptador ou resposta inválida pode encerrar a thread de execução enquanto o processo continua vivo e a saúde mostra ok. Strict JSON solicitado ao provedor reduz a chance, mas não substitui a validação do consumidor.

**Correção esperada.** Validar o schema completo, tipos e limites na fronteira antes de qualquer acesso. Acrescentar supervisão da thread/processo, estado de erro recuperável, diagnóstico seguro e reconciliação; não esconder a exceção com sucesso fictício.

**Teste de aceitação obrigatório.** Testar JSON como lista, campos ausentes, summary null/int/list, question numérica, decisão inválida e erro interno de ferramenta. Nenhum caso pode matar silenciosamente o worker ou deixar saúde positiva sem executor.


### A3-07 — “Entrega verificada” não comprova que o objetivo foi atendido

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA + VERIFICAÇÕES DE CONTEÚDO ISOLADAS

**Arquivos e símbolos no commit revisado:**
- [`runtime/verification/verifier.py::verify_text_artifact/_sources`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/verification/verifier.py)
- [`core/daemon.py::worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)
- [`runtime/agent/loop.py::_complete`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)

**O que foi encontrado.** O worker usa mínimo de 200 caracteres e uma contagem de fontes baseada no número de anexos. O verificador confere arquivo, hash, leitura, placeholders e presença textual de referências. Não resolve nem relaciona essas fontes ao material real. _complete usa essa única evidência para satisfazer todos os critérios requeridos.

**Impacto para o usuário.** Um arquivo íntegro e legível, porém irrelevante ou com fontes inventadas, pode satisfazer os controles atuais. No teste isolado, texto sobre paisagem com dois endereços .invalid passou pelos controles de conteúdo; hash e vínculo de arquivo eram pré-condições assumidas, não uma execução completa.

**Correção esperada.** Separar integridade do arquivo, cobertura do pedido, exatidão de cálculos, existência/proveniência das fontes e revisão de conteúdo. Critérios devem derivar do pedido integral, com evidência por critério. Revisão por outro LLM pode ajudar, mas não é prova factual isoladamente.

**Teste de aceitação obrigatório.** Entregar propositalmente assunto errado, cálculos errados, fonte inexistente e cláusula omitida. Cada falha deve impedir conclusão ou produzir entrega parcial claramente rotulada. Um arquivo válido não pode satisfazer automaticamente critérios de negócio distintos.


### A3-08 — A palavra portuguesa “todo” é tratada como placeholder

**Prioridade:** P2 · **Base da evidência:** REGEX ISOLADA REPRODUZIDA

**Arquivos e símbolos no commit revisado:**
- [`runtime/verification/verifier.py::PLACEHOLDERS`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/verification/verifier.py)

**O que foi encontrado.** A expressão usa (?i) e \bTODO\b. Assim, “Todo o trabalho foi concluído” e “Verifique todo o orçamento” são classificados como texto inacabado.

**Impacto para o usuário.** Relatórios legítimos em português podem ser rejeitados, provocar replanejamentos e gastar mais inferência sem necessidade.

**Correção esperada.** Detectar marcadores explícitos contextualizados, como TODO: em estrutura de desenvolvimento, sem confundir palavras comuns. A política de placeholders precisa considerar idioma e tipo de artefato.

**Teste de aceitação obrigatório.** Aceitar “todo”, “todos” e frases normais; rejeitar TODO: completar, [inserir valor] e marcadores claros nos contextos apropriados. Incluir a lista como regressão em português.


### A3-09 — Aceitar PDF/Office/imagem não significa extrair seu conteúdo

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift::pickFiles`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift)
- [`runtime/artifacts/manager.py::EXTENSIONS/import_file`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/artifacts/manager.py)
- [`runtime/tools/builtin.py::read_text`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tools/builtin.py)

**O que foi encontrado.** O seletor e o importador aceitam PDF, DOCX, XLSX, PPTX, PNG e JPEG. A ferramenta oferecida ao agente faz decode UTF-8 com errors="replace" sobre os bytes brutos. Não há nessa rota extração de páginas, XML Office, células/tabelas ou interpretação visual.

**Impacto para o usuário.** O anexo entra no sistema, mas o modelo pode receber lixo binário, texto incompleto ou estrutura sem sentido. Isso afeta diretamente contratos, propostas, planilhas e materiais do cotidiano.

**Correção esperada.** Implementar extratores por formato com proveniência (página, célula, seção), limites e falha explícita; usar visão/OCR apenas quando necessário e autorizado. Até então, explicar no app quais formatos são apenas armazenados e quais são compreendidos.

**Teste de aceitação obrigatório.** Comparar documentos sintéticos em TXT, PDF com texto, PDF digitalizado e Office; conferir valores em tabelas e cláusulas finais. Arquivo ilegível deve gerar diagnóstico, nunca análise fabricada.


### A3-10 — Documentos e observações longos são truncados silenciosamente

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA + CORTE DE TEXTO ISOLADO

**Arquivos e símbolos no commit revisado:**
- [`runtime/tools/builtin.py::read_text`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tools/builtin.py)
- [`runtime/agent/loop.py::_run_tool/_observe`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)

**O que foi encontrado.** A leitura limita text a 200.000 caracteres e o AgentRunner corta json.dumps(output) em 20.000. O segundo corte pode interromper até o JSON e remove o restante do documento. A ferramenta não oferece offset/paginação para recuperar os trechos perdidos.

**Impacto para o usuário.** Uma cláusula ou preço no final deixa de chegar ao modelo sem aviso de cobertura incompleta. Repetir a mesma leitura pode devolver sempre o mesmo prefixo.

**Correção esperada.** Guardar o conteúdo completo como artefato e retornar referências com paginação/ranges, tamanho total e has_more. Persistir observações estruturadas válidas; o contexto pode resumir, mas a fonte precisa continuar acessível. Exigir cobertura dos trechos relevantes antes de concluir.

**Teste de aceitação obrigatório.** Colocar a informação decisiva depois dos caracteres 20.000 e 200.000. O agente deve recuperá-la por outra chamada, registrar o intervalo e não concluir que leu o documento completo só porque leu o prefixo.


### A3-11 — Deduplicação de mensagem não recupera processamento interrompido

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::handle`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift::send`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasConnection.swift::callSync`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasConnection.swift)

**O que foi encontrado.** A mensagem do proprietário é gravada antes de a intenção ser processada. Se houver queda nesse intervalo, o reenvio encontra a mensagem e devolve duplicate, possivelmente com reply=null, sem concluir o processamento. A consulta de duplicidade e a inserção também não formam uma única operação serializada.

**Impacto para o usuário.** É possível evitar uma tarefa duplicada e, mesmo assim, perder a tarefa que deveria ter sido criada. Uma reconexão bem-sucedida não prova recebimento e execução do pedido.

**Correção esperada.** Criar registro durável de requisição com hash do payload e estados RECEIVED/PROCESSING/COMPLETED/UNKNOWN. O reenvio deve devolver o resultado definitivo ou retomar a requisição incompleta com reconciliação. Mesmo ID com payload diferente deve ser conflito explícito.

**Teste de aceitação obrigatório.** Injetar queda depois da mensagem, depois da inferência, antes/depois da criação da tarefa e antes da resposta. O mesmo client_message_id deve levar a um único resultado recuperável, não a um reconhecimento vazio permanente.


### A3-12 — Tarefa pode ser executada antes de todos os anexos serem vinculados

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA; CORRIDA A REPRODUZIR

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::_delegate`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`core/service.py::_task_create`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/service.py)
- [`runtime/tasks/engine.py::create`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tasks/engine.py)
- [`core/daemon.py::worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)

**O que foi encontrado.** TaskEngine.create confirma a tarefa CREATED em uma transação. O vínculo dos anexos e da mensagem é feito depois, em outra transação. O worker já pode selecionar CREATED entre os dois commits.

**Impacto para o usuário.** A execução pode começar com anexos vazios ou incompletos, inclusive calculando um min_sources incorreto. Uma queda nessa janela também deixa trabalho parcialmente preparado.

**Correção esperada.** Preparar objetivo, mensagem, anexos e critérios atomicamente, publicando a tarefa executável somente no último commit; ou usar um estado de preparação não elegível ao worker. Validar a operação inteira antes de expor o trabalho.

**Teste de aceitação obrigatório.** Usar duas conexões e barreiras de sincronização para forçar a seleção entre commits. O worker não pode adquirir a tarefa antes de seu pacote de entrada estar completo.


### A3-13 — Roteamento por palavras-chave captura perguntas que não são status

**Prioridade:** P2 · **Base da evidência:** REGEX ISOLADA REPRODUZIDA

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::_STATUS/_MEMORY/handle`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)

**O que foi encontrado.** A regex de status aceita “Como está o tempo no Rio?”, “Qual o andamento da economia?” e “Como vai funcionar esse software?” como consulta de tarefas. A de memória também aceita prefixos parciais: “Lembrete:” vira conteúdo “te: ...”, e formas acentuadas podem manter o prefixo no texto guardado.

**Impacto para o usuário.** O usuário recebe um inventário de trabalhos quando esperava conversa natural ou pesquisa. A experiência passa a depender de adivinhar comandos.

**Correção esperada.** Manter comandos exatos para parada e ações de autoridade; para intenções gerais usar contexto, limites lexicais e desambiguação. Preservar o texto original e normalizar apenas para reconhecimento, sem perder a extensão correta do trecho capturado.

**Teste de aceitação obrigatório.** Criar testes de paráfrases em português: estado de tarefa versus tempo/economia/explicação do software; memória versus lembrete. Perguntas semelhantes com intenções diferentes devem seguir rotas diferentes.


### A3-14 — Pergunta pendente captura assuntos novos como se fossem respostas

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::_pending_question/handle/_answer`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::send`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)

**O que foi encontrado.** Quando há exatamente uma pergunta pendente, mensagens seguintes são tratadas como resposta antes da rota de status/memória/correção. Com mais de uma pergunta, não há seleção automática confiável. A interface não oferece uma associação explícita por pergunta no envio comum.

**Impacto para o usuário.** “Qual o andamento?” ou uma informação nova pode retomar a tarefa com uma resposta inadequada. Com duas tarefas aguardando, a resposta pode virar conversa avulsa.

**Correção esperada.** Oferecer responder à pergunta/tarefa por ID na interface e no contrato. Inferir continuidade somente quando inequívoca; assunto novo, status e comandos explícitos não devem ser consumidos como resposta.

**Teste de aceitação obrigatório.** Testar uma e duas perguntas simultâneas, resposta fora de ordem, pedido novo, pergunta de status e resposta a pergunta já resolvida. Só a tarefa correta pode ser retomada.


### A3-15 — Anexar um arquivo força delegação mesmo quando o usuário só compartilha

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::deliver`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)
- [`core/conversation.py::handle/_delegate`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)

**O que foi encontrado.** A UI envia delegate || !ids.isEmpty. Portanto, a presença de anexo decide que haverá tarefa, independentemente do significado da mensagem. O modo explícito pode anteceder o tratamento de memória ou de uma resposta a pergunta.

**Impacto para o usuário.** “Guarde este documento para depois” não é necessariamente trabalho a executar agora. “Esse é o arquivo que faltava” deveria atualizar a tarefa existente, não criar outra.

**Correção esperada.** Separar importação/armazenamento, referência em conversa, gravação de memória e delegação. Não converter anexo em autorização tácita para criar tarefa. Vincular anexos a respostas/correções na tarefa alvo.

**Teste de aceitação obrigatório.** Enviar arquivo para guardar, arquivo como complemento de tarefa e arquivo para análise nova. Os três cenários precisam produzir estados e vínculos diferentes, sem tarefas extras.


### A3-16 — Corrigir uma memória remove sua validade temporal

**Prioridade:** P2 · **Base da evidência:** SQL ISOLADO REPRODUZIDO

**Arquivos e símbolos no commit revisado:**
- [`runtime/memory/manager.py::correct/search`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/memory/manager.py)

**O que foi encontrado.** correct cria uma nova versão sem valid_from e valid_until. A busca passa a usar a versão atual, cujos limites ficam nulos, em vez da janela anterior.

**Impacto para o usuário.** Uma informação válida somente em certo período pode voltar a aparecer como válida indefinidamente depois de uma simples correção de conteúdo.

**Correção esperada.** Preservar a janela anterior por padrão e permitir uma alteração temporal explícita, versionada e validada. Correção de texto não deve mudar silenciosamente a vigência.

**Teste de aceitação obrigatório.** Corrigir memória expirada e memória futura. As duas devem continuar respeitando a janela original. Incluir um teste separado para alteração de vigência autorizada.


### A3-17 — Excluir memória não elimina cópias usadas no contexto

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`runtime/memory/manager.py::delete`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/memory/manager.py)
- [`core/conversation.py::_remember/_chat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`runtime/agent/loop.py::_observe/_resume_state`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)

**O que foi encontrado.** delete limpa memory_versions e o índice, mas o conteúdo pode continuar nas mensagens de pedido/confirmação e em observações persistidas. A conversa lê essas mensagens novamente. A interface também não oferece o percurso completo de gerenciar e excluir memória.

**Impacto para o usuário.** Após “esquecer”, o sistema pode voltar a usar uma cópia do mesmo dado. Exclusão no índice e esquecimento operacional não são a mesma operação.

**Correção esperada.** Definir escopos explícitos de exclusão e tombstones por origem; impedir reintrodução por histórico/resumo/observação. Oferecer revisão e exclusão na interface, explicando limites de backups. Não prometer apagar cópias externas fora do controle do produto.

**Teste de aceitação obrigatório.** Guardar, confirmar, usar, excluir e perguntar novamente em seguida e após reiniciar. Inspecionar todo contexto enviado. Testar exclusão parcial versus exclusão completa autorizada e política para backups.


### A3-18 — O contexto pode preservar instruções antigas e descartar a atual

**Prioridade:** P1 · **Base da evidência:** FRAGMENTO ISOLADO + ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`runtime/models/context.py::ContextBuilder.build`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/context.py)
- [`core/conversation.py::_chat`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`runtime/agent/loop.py::_context`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)

**O que foi encontrado.** A seleção de contexto é gulosa por autoridade e ordem de inserção. Na conversa, instruções anteriores têm a mesma autoridade da última e vêm primeiro. Em histórico longo, a mensagem atual pode cair em dropped. Respostas anteriores do modelo ainda são marcadas VERIFIED_FACT, sem verificação própria.

**Impacto para o usuário.** O modelo pode responder ao contexto antigo sem receber a pergunta atual. Texto gerado antes também pode adquirir um grau de confiança que não possui.

**Correção esperada.** Reservar espaço para a mensagem vigente e restrições ativas; selecionar por relevância e recência dentro de cada autoridade. Resumir histórico sem transformar saídas do modelo em evidência verificada. Bloquear a inferência ou avisar se o contexto obrigatório não couber.

**Teste de aceitação obrigatório.** Saturar o histórico com mensagens longas e inserir uma correção curta no fim. A última instrução precisa estar presente em todas as chamadas. Sentinelas de texto antigo não confirmado não podem surgir como fato verificado.


### A3-19 — Reduzir orçamento não atualiza clientes já em execução

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA; TESTE CONCORRENTE PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`core/intelligence.py::_client/build_client`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/intelligence.py)
- [`core/daemon.py::_components/worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)
- [`security/budget/budget.py::BudgetLimits/BudgetManager.reserve_in_txn`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/security/budget/budget.py)
- [`runtime/models/router.py::call`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/router.py)

**O que foi encontrado.** BudgetLimits é um snapshot mantido no BudgetManager. O cliente do modelo é criado antes de rodar a tarefa; o broker também guarda seus próprios limites desde _components. Salvar uma revisão de settings não atualiza esses objetos nem os obriga a revalidar a política antes da próxima reserva.

**Impacto para o usuário.** Uma redução de teto pode não valer para chamadas posteriores da tarefa já em andamento. O orçamento exibido e o usado pelo executor podem divergir até reconstruir os componentes.

**Correção esperada.** Ler a revisão de política/orçamento vigente dentro da transação de cada reserva e despacho. Definir como reduções afetam reservas existentes e cancelar novos gastos incompatíveis; não apagar consumo já realizado.

**Teste de aceitação obrigatório.** Executar tarefa em múltiplos passos, reduzir teto por outra conexão entre dois passos e verificar que a chamada seguinte é barrada pelo novo limite. Testar aumento, revogação de consentimento e concorrência com Testar inteligência.


### A3-20 — Transporte HTTP precisa vincular credenciais ao destino final

**Prioridade:** P1 · **Base da evidência:** ESTÁTICA + CONSTRUÇÃO DE REQUEST ISOLADA; CONDICIONAL

**Arquivos e símbolos no commit revisado:**
- [`runtime/models/openai_responses.py::__init__/_request`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/models/openai_responses.py)

**O que foi encontrado.** O cliente usa urlopen com Authorization e sem política própria de redirecionamento. A construção isolada de redirect da biblioteca Python local manteve o header ao mudar de origem. A exceção HTTP para testes usa startswith("http://127.0.0.1"), aceitando também hostname com esse prefixo que não é loopback.

**Impacto para o usuário.** Na presença de endpoint ou redirecionamento não confiável, a credencial pode ser encaminhada a destino indevido. Não foi observado redirecionamento malicioso no provedor, nem existe prova de vazamento; a versão Python do bundle deve ser testada separadamente.

**Correção esperada.** Analisar scheme/host/porta com parser; permitir loopback exato apenas em modo de testes. Recusar redirects ou revalidar origem sem repassar Authorization entre origens; vincular uso da credencial ao destino efetivo e rejeitar endpoint arbitrário na distribuição normal.

**Teste de aceitação obrigatório.** Usar servidores locais de teste para 301/302/303/307/308: o destino de outra origem não pode receber Authorization. Testar prefixos enganosos, downgrade HTTPS/HTTP, URL com usuário e porta. Nunca usar segredo real nesses testes.


### A3-21 — Arrastar vários arquivos pode importar apenas o primeiro

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA; REPRODUÇÃO VISUAL PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift::ConversationView.onDrop`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::attach`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)

**O que foi encontrado.** onDrop inicia uma Task independente para cada arquivo. attach retorna silenciosamente se isAttaching já é true. Como a importação suspende em awaits, chamadas seguintes podem chegar enquanto a primeira ainda está ativa. O seletor de arquivos usa um laço sequencial e não sofre a mesma corrida.

**Impacto para o usuário.** O usuário solta várias propostas ou documentos e pode achar que todos foram importados, quando alguns foram simplesmente ignorados.

**Correção esperada.** Usar fila de importação com resultado por arquivo, cancelamento e resumo de erros. Nunca descartar arquivos silenciosamente por estar ocupado.

**Teste de aceitação obrigatório.** Arrastar dez arquivos com transporte artificialmente lento: todos devem aparecer como importados ou falhar explicitamente. Repetir pelo seletor e misturar arquivos inválidos.


### A3-22 — Reenvio não conserva todo o payload original

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::failedDraft/retryFailedSend/deliver`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift::importFile`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift)

**O que foi encontrado.** failedDraft conserva texto, clientId e delegate, mas não uma lista imutável de anexos/replyTo. O reenvio recalcula os IDs a partir dos anexos atualmente na tela. Uma importação com resposta perdida também não possui uma consulta de recibo que recupere o artifact_id já criado.

**Impacto para o usuário.** O mesmo ID pode ser reenviado com conteúdo diferente, ou um arquivo importado ficar sem vínculo visível depois de falha de conexão.

**Correção esperada.** Persistir um envelope imutável de envio com texto, anexos, tarefa/resposta alvo, intenção, hash e idempotency key. Implementar recibo consultável da importação. Alterar anexos deve gerar novo envelope, não reutilizar o ID anterior.

**Teste de aceitação obrigatório.** Derrubar conexão após gravar mensagem/importar arquivo, alterar anexos na UI e tentar novamente. Recuperar o pedido original ou apresentar conflito claro; não criar cópias órfãs ou reinterpretar o payload.


### A3-23 — Atualização do histórico não reconcilia mensagens existentes nem lacunas

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::merge/refresh/loadOlder`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)
- [`core/conversation.py::_set_kind/history`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)

**O que foi encontrado.** merge apenas acrescenta IDs novos. Alterações posteriores de kind/task_id em uma mensagem já carregada não chegam à tela. refresh lê somente a página mais recente (50 por padrão), enquanto o cursor de eventos é avançado; um intervalo maior de mensagens pode ficar ausente no meio do histórico local.

**Impacto para o usuário.** A interface pode manter ações “Delegar” sobre mensagem já vinculada ou perder a continuidade visual após uma desconexão longa. O dado no banco pode estar correto e a janela, desatualizada.

**Correção esperada.** Fazer upsert por ID com versão/sequence e ordenar por sequência estável. Preencher explicitamente intervalos perdidos desde o último cursor, em vez de apenas anexar a última página.

**Teste de aceitação obrigatório.** Mudar kind/task_id de mensagem visível, reconectar depois de mais de 50 mensagens e paginar para trás. Verificar ausência de duplicação, lacunas e ordem incorreta.


### A3-24 — Uploads têm coordenação e limpeza incompletas

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA; TESTE CONCORRENTE PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`core/service.py::__init__/_upload/_import/_upload_path`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/service.py)
- [`core/daemon.py::service`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)

**O que foi encontrado.** Cada CoreService tem seu próprio _uploads_lock, embora diferentes conexões possam operar no mesmo arquivo de staging. A checagem de tamanho/offset e a escrita não estão coordenadas entre serviços. O staging tem limite por arquivo, mas não expiração/limite agregado demonstrados nesse percurso.

**Impacto para o usuário.** Reenvios concorrentes podem disputar offsets e uploads abandonados podem acumular arquivos. Não foi provada corrupção concreta em execução integrada.

**Correção esperada.** Coordenar uploads por ID entre conexões, com metadados transacionais, estado final e recibo. Definir quota agregada, prazo de expiração e limpeza recuperável; usar escrita segura e não tratar staging como arquivo já aprovado.

**Teste de aceitação obrigatório.** Enviar o mesmo chunk simultaneamente por duas conexões, fechar a conexão antes de importar, reiniciar e reenviar. Conferir hash final, uma única importação e remoção dos temporários expirados.


### A3-25 — Leitura em chunks relê e recalcula hash do arquivo inteiro

**Prioridade:** P3 · **Base da evidência:** ESTÁTICA + CÁLCULO

**Arquivos e símbolos no commit revisado:**
- [`core/service.py::_read`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/service.py)
- [`runtime/artifacts/manager.py::read_bytes`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/artifacts/manager.py)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift::readArtifact`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasAPI.swift)

**O que foi encontrado.** Para cada chunk de 512 KiB, _read chama read_bytes, que lê e verifica novamente o arquivo completo. Um arquivo de 50 MiB exige cerca de 100 chunks: aproximadamente 5.000 MiB de leitura/hash cumulativos, além da transferência. Não significa 5 GiB simultaneamente na RAM.

**Impacto para o usuário.** Arquivos grandes tornam exportação/prévia muito mais caras em CPU e I/O e pressionam a fila serial do app.

**Correção esperada.** Abrir uma sessão de leitura de artefato imutável com verificação inicial, tamanho/hash fixos e leitura por intervalo. Preservar a verificação final e detectar adulteração sem repetir trabalho integral a cada chunk.

**Teste de aceitação obrigatório.** Instrumentar bytes lidos/hasheados para 1, 10 e 50 MiB. O custo deve crescer aproximadamente com o tamanho do arquivo, não com tamanho multiplicado pelo número de chunks.


### A3-26 — Algumas referências por ID não validam o proprietário completo

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA; AMEAÇA CONDICIONAL A MÚLTIPLAS IDENTIDADES

**Arquivos e símbolos no commit revisado:**
- [`core/conversation.py::handle (delegate existing message)`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)
- [`core/service.py::_mem_correct`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/service.py)
- [`runtime/memory/manager.py::correct`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/memory/manager.py)

**O que foi encontrado.** A delegação de mensagem anterior usa get_message e confere role, mas não prova que a mensagem pertence à conversa/empregado da sessão. Em correct, o teste de proprietário de memória é mais fraco que em confirm/delete; o caminho de serviço também não liga explicitamente memory_id à sessão.

**Impacto para o usuário.** Com sessões de empregados/proprietários distintos e IDs conhecidos, pode haver cópia ou alteração entre escopos. A distribuição atual normalmente cria um empregado: não é uma exploração remota demonstrada, mas a API não deve depender dessa circunstância.

**Correção esperada.** Aplicar verificação central por objeto: session -> owner -> employee -> conversation/task/memory/source. Conferir IDs relacionados em todas as operações, não só nos métodos mais visíveis.

**Teste de aceitação obrigatório.** Criar dois proprietários e dois empregados com sessões distintas e tentar delegar mensagem/corrigir memória cruzadas. Tudo deve falhar sem revelar conteúdo, inclusive quando a fonte também é fornecida por ID.


### A3-27 — Notificação pode se perder depois de a tarefa mudar de estado

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`runtime/agent/loop.py::_tell_owner/run/_complete`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/agent/loop.py)
- [`core/conversation.py::notify`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/conversation.py)

**O que foi encontrado.** A tarefa muda para WAITING_USER ou COMPLETED antes de sua mensagem ser entregue. _tell_owner captura toda exceção e ignora. Não há outbox durável ligada à transação de estado nesse caminho.

**Impacto para o usuário.** Uma tarefa pode aguardar uma resposta que o usuário nunca viu, ou terminar sem publicar seu arquivo na conversa. Persistência da tarefa sozinha não garante entrega da comunicação.

**Correção esperada.** Persistir evento de notificação na mesma transação da mudança de estado, com chave idempotente e dispatcher recuperável. Uma falha de notificação não deve desfazer um efeito externo, mas precisa ficar pendente e visível para nova entrega.

**Teste de aceitação obrigatório.** Falhar antes/depois do commit e durante notify; reiniciar. A pergunta/entrega deve aparecer exatamente uma vez, vinculada à tarefa, e nunca desaparecer silenciosamente.


### A3-28 — Inicialização não demonstra exclusão mútua entre instâncias

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA; TESTE DE DUAS INSTÂNCIAS PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasKit/Supervisor.swift::start/launchCore`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/Supervisor.swift)
- [`core/daemon.py::bootstrap/main`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)

**O que foi encontrado.** O Supervisor protege seu próprio objeto com NSLock, mas recria token e remove sockets em caminhos compartilhados ao iniciar. Não há nesses percursos uma trava interprocesso de instância/diretório. Iniciar duas cópias ou um daemon duplicado precisa ser tratado explicitamente.

**Impacto para o usuário.** Uma segunda instância pode invalidar sessões da primeira e disparar recuperação de tarefas enquanto ainda existe execução. A quantidade exata de processos e efeitos precisa ser reproduzida em Mac.

**Correção esperada.** Adquirir trava interprocesso exclusiva sobre o diretório de dados antes de alterar tokens, sockets ou recuperar tarefas; distinguir instância viva de arquivos órfãos. A segunda janela deve conectar-se à instância existente ou recusar com diagnóstico.

**Teste de aceitação obrigatório.** Abrir duas cópias e iniciar dois Supervisores/daemons simultaneamente. Deve haver um único responsável pela recuperação/execução e nenhuma remoção do socket de processo saudável.


### A3-29 — Validação da inteligência sobrevive indevidamente à troca de credencial

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`core/intelligence.py::status/register_key/_run_check`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/intelligence.py)

**O que foi encontrado.** status encontra uma validação aprovada por provider/model_id. Não a associa à referência/versão da credencial atual nem à base URL utilizada. Trocar a chave pode manter o indicador Pronta baseado em um teste de outra conta.

**Impacto para o usuário.** A aplicação afirma que a inteligência está configurada sem comprovar o acesso da nova credencial. O erro só aparece quando há uma chamada posterior.

**Correção esperada.** Vincular validação a credencial, endpoint, modelo, capacidades e versão relevante de configuração. Invalidar ou exigir nova validação ao mudar esse vínculo, sem confundir acesso ao modelo com verificação de preço.

**Teste de aceitação obrigatório.** Validar uma credencial sintética A em servidor controlado, substituí-la por B sem acesso e conferir que Pronta é retirada imediatamente; repetir mudando endpoint/modelo.


### A3-30 — Os botões de controle não refletem os estados realmente aceitos

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift::TaskRow`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift)
- [`runtime/tasks/engine.py::resume/_resume_target`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/runtime/tasks/engine.py)
- [`core/daemon.py::worker`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/core/daemon.py)

**O que foi encontrado.** A UI oferece Pausar/Retomar/Cancelar em todos os estados. resume aceita somente PAUSED. Uma tarefa BLOCKED, por exemplo após orçamento esgotado, não é retomada pelo botão sem percurso adicional. Alguns estados de origem podem ser restaurados sem pertencer ao conjunto que o worker seleciona.

**Impacto para o usuário.** O usuário segue a ação aparente e recebe erro técnico ou mantém uma tarefa parada. Corrigir a configuração não oferece necessariamente uma recuperação compreensível.

**Correção esperada.** Derivar ações disponíveis da máquina de estados; criar percurso explícito de desbloqueio que revalide causa, orçamento e efeitos incertos. Não liberar compras ou redespachar UNKNOWN só para fazer o botão funcionar.

**Teste de aceitação obrigatório.** Testar os controles em cada estado, incluindo bloqueio de orçamento, aprovação pendente, lease vencido e resultado incerto. Só mostrar ações válidas e documentar o resultado de cada uma.


### A3-31 — Encerrar serviços ainda pode bloquear a interface sem prazo

**Prioridade:** P2 · **Base da evidência:** ESTÁTICA; REPRODUÇÃO MAC PENDENTE

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift::AppController.shutdown`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/Supervisor.swift::stop`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/Supervisor.swift)

**O que foi encontrado.** A melhoria assíncrona do IPC não cobre shutdown: AppController no MainActor chama Supervisor.stop, que usa waitUntilExit sem prazo para os processos. Um serviço que não encerre pode prender o menu de encerramento ou a saída do app.

**Impacto para o usuário.** A saída de emergência e a experiência de fechamento podem ficar bloqueadas em condições de falha.

**Correção esperada.** Executar shutdown fora do MainActor, com etapas limitadas: parada cooperativa, checkpoint/reconciliação, diagnóstico e término forçado controlado quando indispensável. Não ocultar que o resultado de uma ação externa pode ser desconhecido.

**Teste de aceitação obrigatório.** Substituir serviço por processo de teste que ignora a primeira solicitação de término. O app deve continuar responsivo e concluir ou explicar a saída dentro de um limite mensurável.


### A3-32 — Salvar resultado não preserva o nome e a extensão do arquivo

**Prioridade:** P3 · **Base da evidência:** ESTÁTICA

**Arquivos e símbolos no commit revisado:**
- [`platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift::Bubble.saveAs`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasApp/AtlasApp.swift)
- [`platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift::export`](https://github.com/ViniciusMilanez82/atlas/blob/d81cece2713ccb5b12e58902e55b05a614467951/platform/macos/AtlasKit/Sources/AtlasKit/AtlasViewModel.swift)

**O que foi encontrado.** O painel Salvar como inicia sempre com nameFieldStringValue="entrega", sem carregar nome/extensão do artefato. A exportação grava no caminho escolhido, mesmo quando a extensão original era .md, .csv ou .json.

**Impacto para o usuário.** Um usuário comum pode salvar um arquivo sem extensão e ter dificuldade para abri-lo no aplicativo apropriado.

**Correção esperada.** Carregar metadados do artefato para sugerir o nome completo, extensão e tipo; preservar liberdade de renomear sem trocar silenciosamente o formato.

**Teste de aceitação obrigatório.** Exportar TXT, Markdown, CSV e JSON sem editar o nome sugerido. Conferir extensão, conteúdo, hash e abertura no aplicativo indicado.

## 7. Funções ausentes e limitações que não devem ser disfarçadas como bugs menores

### 7.1 Computador próprio e autoridade isolada

A release ainda não tem o workspace virtualizado que concretiza o “escritório do empregado”. As ferramentas atuais são confiáveis e restritas ao armazenamento do Atlas; isso é positivo, mas não é permissão para executar código arbitrário no host. Não habilitar navegador pessoal, shell do proprietário, instalação irrestrita ou credenciais amplas para simular a autonomia ausente.

Também é preciso demonstrar a separação de autoridade em produção: um processo, thread ou objeto chamado “runtime” não é, por si só, uma barreira de segurança. Conteúdo externo e código novo não podem alcançar o banco de políticas, tokens de sessão ou o Vault.

### 7.2 Capacidades de ação

Na rota do daemon, o catálogo de ferramentas internas contém `artifact.read_text`, `artifact.write_text` e `memory.search`. Isso não pesquisa a internet, abre aplicativos, instala ferramentas, cria contas ou envia resultados por e-mail/WhatsApp. Uma assinatura externa futura não garante que todos os sites sejam acessíveis; bloqueios legítimos precisam de alternativas autorizadas ou intervenção humana.

### 7.3 Voz, contato remoto e disponibilidade

Voz, canal pelo celular, login item e VM não foram comprovados como percursos de produto nesta versão. Fechar apenas a janela é diferente de sair do app; desligar/suspender o Mac é diferente de deixar um serviço ativo. A disponibilidade deve ser apresentada com essas distinções, sem prometer trabalho enquanto a máquina está indisponível.

### 7.4 Configuração para pessoas sem conhecimento técnico

O app precisa conduzir identidade, consentimentos, modelos disponíveis, orçamento e contato com linguagem comum. A exigência de informar um ID exato de API e aceitar uma tabela não verificada é uma escolha admissível de desenvolvimento, não a instalação final pretendida. Memória deve ter tela de consulta/correção/exclusão; saúde precisa explicar o que está faltando sem traduzir uma fila parada como execução.

### 7.5 Inteligência efetivamente homologada

Não foi verificada nesta auditoria a disponibilidade comercial de nenhum ID, preço ou capacidade de modelo. Os nomes presentes no código não provam acesso na conta do usuário. O caminho ativo cria um único provedor/modelo manual; o roteador genérico possuir outros modos não prova que eles estejam expostos e funcionando. A validação precisa ser feita com credencial e teto autorizados, e incluir o trabalho completo, não só um JSON minúsculo de saúde.

### 7.6 Segurança e distribuição

Backups cifrados não equivalem a banco em uso cifrado, e Keychain não cifra automaticamente conversas, observações e arquivos. A distribuição de desenvolvimento ad-hoc não equivale a assinatura/notarização de release. O modo de aprendizado de skills precisa ter isolamento, testes, origem, aprovação de promoção e rollback, sem alterar regras fundamentais de segurança.

## 8. Ordem de implementação recomendada

### Rodada 1 — Autoridade, controle e consistência

Corrigir A3-02, 03, 04, 05, 06, 11, 12, 18, 19 e 20. Incluir desde já testes dos riscos de sessão/instância e notificações. Nenhuma chamada sensível ou ampliação de ferramentas antes das barreiras pertinentes. Não baixar o rigor das aprovações para “fazer a demo funcionar”.

### Rodada 2 — Entendimento e memória

Corrigir A3-01, 07, 08, 09, 10, 13, 14, 15, 16 e 17. Entregar conversa que recupera conhecimento, anexos compreendidos e conclusão verificável. Informação temporal deve ser calculada por estruturas e código apropriados, não por palpite do modelo.

### Rodada 3 — Interface e recuperação de ponta a ponta

Concluir A3-21 a 32 e estabilizar inicialização, encerramento, upload, download, histórico e botões. Medir desempenho e erros com uso interativo real. Não limitar os testes à ViewModel com transporte falso.

### Rodada 4 — Primeira tarefa real com modelo autorizado

Usar dados sintéticos, uma credencial de teste dedicada e um orçamento explicitamente autorizado. Registrar modelo, request IDs, consumo, estados, fontes e entregáveis; não registrar segredos ou raciocínio privado. Incluir condições adversas: resposta lenta, resposta inválida, correção, interrupção e retomada.

### Rodada 5 — Expandir até a visão original

Implementar o workspace real e navegador no guest, ferramentas de pesquisa e contas próprias, observabilidade do trabalho, skills controladas, voz e pelo menos um canal remoto seguro. Homologar assinatura, notarização e atualização. Não anunciar o conjunto completo antes de testá-lo.

## 9. Cenários de aceitação do produto

| Cenário | Prova necessária |
|---|---|
| Lembrança fora do chat recente | Fato e preferência recuperados após mais de 20 mensagens, paráfrase e reinício |
| Esquecimento | Conteúdo excluído não reaparece via mensagem, observação ou resumo |
| Correção ao vivo | Condição nova entra antes do próximo passo, sem executar proposta obsoleta |
| Duas tarefas e duas perguntas | Respostas vinculadas ao trabalho certo, sem novos trabalhos acidentais |
| Compartilhar sem delegar | Arquivo guardado sem criar uma tarefa; posterior referência recuperável |
| Documento longo e binário | Fonte decisiva no fim e em tabela/página/célula corretamente extraída |
| Entrega falsa | Relatório íntegro porém irrelevante ou com fonte inexistente não conclui |
| Parada sob carga | Mesmo atalho real interrompe novos despachos durante envio/reconexão |
| Orçamento reduzido | Próxima reserva respeita limite salvo durante execução |
| Falha de provedor | Timeout/JSON inválido não mata worker sem diagnóstico |
| Crash de processamento | Reenvio recupera o resultado, não duplica nem perde a intenção |
| Crash de comunicação | Pergunta/entrega volta pela outbox exatamente uma vez |
| Duas instâncias | Uma autoridade efetiva por diretório de dados; sessão saudável preservada |
| Rede/segredos | Contexto sensível e credenciais não saem para destinos não autorizados |
| Instalação com leigo | Instalar, criar identidade, conversar e receber resultado sem terminal |

Em todos os cenários, comprovar pela mesma interface e pelo mesmo bundle que serão entregues, além de testes internos. Uma captura de tela da janela inicial não cobre esses percursos. A chamada real ao modelo não substitui testes determinísticos; ambos são necessários.

## 10. Riscos adicionais para a próxima revisão

A estimativa de tokens por caracteres/2 no adaptador não é um limite matemático universal: deve ser calibrada e conservadora, sem prometer teto financeiro absoluto com preço não verificado. O agendador é acionado entre tarefas no único worker; medir o atraso de execução de horários enquanto um trabalho longo ocupa esse worker. Reavaliar o schema de upload e a verificação real de formatos Office, não só a existência de `[Content_Types].xml`. O armazenamento endereçado por hash usa um temporário de nome previsível por objeto; testar escritas concorrentes do mesmo conteúdo. Esses tópicos não são apresentados como explorações reproduzidas nesta auditoria.

Não há cobertura completa de dependências, sistema operacional, binário distribuído, assinatura, canais remotos futuros ou todas as rotas do repositório. Antes de produção, é necessária nova revisão após correções e testes de sistema com os limites documentados.

## 11. Instrução de entrega à IA programadora

Entregue este documento junto com `Atlas_Prompt_Correcoes_Alpha3.txt` e a pasta `probes`. Os probes são reprodutores isolados para orientar os testes do repositório, não substitutos deles. O próximo agente deve conferir o HEAD, reproduzir os achados pertinentes e mostrar evidência por item, sem reiniciar o projeto e sem tratar a aprovação de testes falsos como homologação com IA real.

**Parecer final:** continuar o desenvolvimento sobre esta base, mas não considerar a Alpha 2 pronta como funcionário autônomo generalista, não entregar autonomia financeira ampla e não usar dados sensíveis enquanto persistirem as barreiras de privacidade e controle identificadas.
