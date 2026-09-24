# ATLAS — Funcionário Digital
## Especificação de produto, arquitetura técnica e contrato de implementação

**Versão:** 1.0 | **Data de referência:** 22 de setembro de 2026  
**Preparado para:** Vinícius Milanez  
**Destino:** IA de programação, desenvolvedor responsável e revisão técnica  
**Status:** especificação para iniciar implementação incremental; aplicativo ainda não implementado ou validado.

> **Definição central:** um funcionário digital persistente, com identidade operacional, memória, contas e ambiente de trabalho próprios. O usuário conversa e delega objetivos; o Atlas escolhe os passos, executa dentro das autorizações, verifica e entrega os resultados.

Este documento consolida a conversa e substitui os resumos anteriores. Requisitos de produto são tratados como decisões deste projeto. Características de fornecedores são referenciadas no capítulo 25. Números de desempenho e limites internos são metas iniciais, não medições de um produto existente. Exemplos pessoais não constituem módulos obrigatórios.

# 1. Como utilizar este documento

## 1.1 Instrução para o proprietário do projeto

Entregue este arquivo integral à IA de programação com acesso a uma pasta de projeto vazia e a um ambiente macOS de desenvolvimento. Utilize o contrato do capítulo 24 como primeira instrução. A IA deverá criar o repositório, conferir dependências, implementar os marcos e apresentar evidências. Este material não é um instalador nem uma promessa de que um único comando produzirá um aplicativo final sem testes.

A pessoa que usa o Atlas pronto não precisará programar. A construção, entretanto, exige ferramentas de desenvolvimento, acesso autorizado às APIs escolhidas, testes em Mac real e credenciais de distribuição quando chegar a etapa de publicação. A IA deverá executar o trabalho técnico possível e solicitar ao proprietário somente decisões, acessos ou operações humanas indispensáveis.

## 1.2 Vocabulário normativo

**DEVE** identifica requisito obrigatório. **NÃO DEVE** identifica proibição. **DEVERIA** é a solução preferida, substituível mediante justificativa registrada. **PODE** é opção. Uma ADR é um registro de decisão arquitetural, com contexto, alternativas, decisão e consequência.

**V1** é o escopo inicial completo de produto. **Alpha** é uma entrega parcial de desenvolvimento. **Beta** é uma versão funcional submetida à suíte de aceitação. Nenhuma entrega parcial poderá ser apresentada como toda a visão realizada.

## 1.3 Ajustes necessários em relação à conversa

A arquitetura está definida como referência, mas não foi compilada, medida ou testada em um Mac nesta etapa. Portanto, “congelada” significa uma baseline controlada por ADR, não a eliminação das provas técnicas.

“Fechar a janela e continuar trabalhando” não significa trabalhar com o Mac desligado, sem energia ou suspenso. “Retomar após reinício” depende de sessão, desbloqueio das chaves e serviços habilitados. “Acessar qualquer site” não é uma garantia. Uma assinatura paga também não garante contornar bloqueios.

A chave de idempotência não assegura execução única em todo site externo. O sistema precisa de reconciliação e estado de resultado desconhecido. Um perfil separado de navegador não equivale a uma máquina virtual isolada. Uma memória vetorial não substitui banco transacional nem calendário estruturado.

Os nomes e preços de modelos precisam corresponder a APIs reais. O catálogo inicial verificado aparece no capítulo 7. O nome “Terra”, mencionado na conversa, não integra a configuração padrão deste documento por falta de identificação oficial validada nesta preparação. Isso não é uma afirmação sobre sua existência em outros produtos.

# 2. Visão, identidade e limites do produto

## 2.1 O que estamos construindo

Um aplicativo macOS chamado provisoriamente Atlas. Ele oferece uma única identidade conversacional, ainda que utilize diversos modelos e trabalhadores internos. O usuário percebe uma continuidade de personalidade, histórico, responsabilidades, tarefas e aprendizado.

O computador destinado ao Atlas funciona como seu escritório digital. Por padrão, ele não utiliza o e-mail pessoal do proprietário, não abre suas fotos, não lê seu navegador e não herda sessões ou documentos. Quando o usuário compartilha um arquivo, a cópia é importada para o ambiente do Atlas mediante ação explícita. Integrações pessoais futuras serão opcionais e específicas.

A expressão “pessoa digital” descreve a experiência de interação. O Atlas não deve declarar que é humano, possuir consciência, ser titular jurídico independente ou ter direitos de acesso que não foram concedidos. Contas operacionais são administradas pelo responsável autorizado. Cadastros não podem utilizar documentos, idade ou identidade inventados.

## 2.2 Objetivos de experiência

A jornada principal é: **instalar → criar funcionário → conversar → delegar → receber**. O usuário deve poder falar “resolva este problema”, compartilhar materiais, revisar um plano quando necessário, acompanhar progresso e receber um resultado verificável.

A interface precisa permitir conversa natural, inclusive interrupções, correções e continuidade entre sessões. O Atlas deverá responder sobre o que está fazendo sem reiniciar a tarefa. Uma mensagem “pare” deve alterar o estado operacional, não produzir apenas uma resposta educada.

## 2.3 Não objetivos da V1

Não estamos construindo uma Siri substituta com acesso irrestrito ao Mac pessoal, uma máquina de burlar sites, uma personalidade fictícia para enganar terceiros ou uma automação financeira sem controle. Também não estamos construindo um ERP, CRM ou calendário familiar específico: essas atividades são domínios de uso de uma plataforma generalista.

Não há treinamento autônomo dos pesos de um grande modelo, instalação arbitrária no sistema hospedeiro, remoção de proteções do macOS, execução permanente como administrador ou promessa de acerto universal. Avatar humano realista, clonagem de voz, telefonia, App Store, Windows e administração de vários funcionários ficam fora da primeira entrega completa.

## 2.4 Escopo por estágio

| Estágio | Entrega obrigatória | Limite declarado |
| --- | --- | --- |
| Alpha local | Conversa, identidade, tarefas, memória, políticas, workspace isolado, pesquisa e artefatos | Não é o produto completo; canais remotos e voz podem estar pendentes |
| Beta V1 | Voz, retomada, observabilidade, um canal remoto real, instalador, atualização e recuperação | Compras e sites não homologados continuam supervisionados |
| Pós-V1 | WhatsApp oficial quando viável, novos provedores, backup remoto, mais skills e canais | Cada integração exige contrato, testes e análise própria |
| Futuro | Multiusuário comercial, outros sistemas operacionais, avatar e modelos locais avançados | Não antecipar complexidade no núcleo da V1 |

# 3. Requisitos funcionais e experiência do usuário

## 3.1 Onboarding

**UX-001 — Instalação gráfica.** O usuário final recebe um pacote assinado e notarizado quando a distribuição estiver pronta. Não deverá instalar Python, Node, Docker, banco de dados ou Playwright manualmente. A imagem do ambiente pode ser baixada durante a preparação inicial, com tamanho, progresso, verificação e retomada de download. Assinatura e notarização são parte da entrega, não tarefas invisíveis já concluídas. [S08]

**UX-002 — Identidade.** Solicitar nome do funcionário, idioma, forma de tratamento e voz. “Generalista” será o perfil padrão. Preferências de estilo não alteram permissões. O funcionário possui employee_id estável, independente de seu nome visível.

**UX-003 — Computador.** Verificar arquitetura, macOS, memória, disco, virtualização, acesso à rede e permissões necessárias. Apresentar falhas com ação corretiva específica. Não declarar suporte ao equipamento antes do diagnóstico.

**UX-004 — Inteligência.** Apresentar modo gerenciado ou credencial própria conforme o que estiver realmente implementado. Na Alpha, credencial própria pode ser utilizada; não chamar isso de experiência final sem configuração. Mostrar que uso de API pode ter cobrança independente da assinatura de chat. [S06]

**UX-005 — Autonomia.** Selecionar perfil seguro inicial e orçamento. Compras e novas assinaturas começam sem autorização. O usuário pode aprovar mandatos limitados posteriormente. Configuração de gasto deve incluir moeda, período e teto.

**UX-006 — Contato.** Registrar o canal do proprietário como destino de entrega verificado. Não exigir conexão com a caixa de e-mail pessoal. Parear dispositivos com confirmação local.

## 3.2 Telas obrigatórias

| Tela | Conteúdo e comportamento |
| --- | --- |
| Conversa | Texto, voz, anexos, mensagens em streaming, estado real e acesso ao histórico |
| Trabalho | Tarefas ativas, aguardando resposta, agendadas e concluídas; prioridade e cancelamento |
| Ver trabalhando | Tela do workspace, atividade atual, pausa, assumir controle e devolver controle |
| Aprovações | Ação exata, destino, dados compartilhados, custo, recorrência, validade e alternativas |
| Memória | Fatos, preferências, fontes, validade, correções, exportação e exclusão |
| Arquivos | Entregáveis por tarefa, prévia, versões, fontes e envio para o proprietário |
| Configurações | Identidade, inteligência, orçamento, contas, privacidade, canais e disponibilidade |
| Diagnóstico | Saúde do runtime, workspace, rede e modelos; relatório sem segredos |

## 3.3 Regras da conversa

Perguntar somente quando a ambiguidade alterar uma decisão importante, faltar autorização ou uma informação indispensável não puder ser recuperada. Para detalhes reversíveis e de baixo risco, adotar hipótese razoável e registrá-la. Não usar respostas vagas como “estou resolvendo” sem tarefa real vinculada.

Ao aceitar trabalho longo, criar a tarefa antes de afirmar que começou. A confirmação deve mostrar objetivo, eventual prazo solicitado e restrições relevantes. O progresso deve informar marcos concretos, não números ou tempos inventados. Mensagens de status são geradas a partir dos eventos registrados.

Notificações automáticas devem se concentrar em conclusão, bloqueio real, autorização e mudança material de resultado. Frequência de atualizações é configurável. Horário silencioso não impede a persistência da tarefa e pode permitir alertas urgentes previamente autorizados.

## 3.4 Modo dedicado e saída de emergência

A V1 deve oferecer tela cheia e abertura automática opcional. Não deve impedir o proprietário de sair do aplicativo ou recuperar o computador. Um modo de quiosque mais restritivo é uma função futura de administração de dispositivos, não um requisito para o funcionamento do Atlas.

Separar três operações: **fechar a janela**, que mantém os serviços autorizados; **pausar o funcionário**, que impede novos passos; e **encerrar todos os serviços**, que encerra runtime e workspace após checkpoints. Mostrar claramente qual operação ocorreu.

# 4. Arquitetura de referência

## 4.1 Decisão de plataforma

Adotar Swift e SwiftUI para a interface nativa, um Supervisor em Swift, Runtime de orquestração em Python e workspace Linux ARM64 virtualizado no Mac. A Apple documenta suporte a máquinas virtuais macOS e Linux e a interfaces gráficas virtuais; a configuração específica do Atlas ainda precisa de prova técnica. [S07]

A escolha de Linux para o workspace reduz a dependência de automação de aplicativos macOS. O usuário continua interagindo com um app nativo. Programas exclusivamente macOS não estarão disponíveis nesse workspace. Um Mac virtualizado pode ser um WorkspaceProvider futuro, após validação de distribuição, compatibilidade e permissões.

**Alvo inicial proposto:** Mac com Apple Silicon, macOS 15 ou posterior que passe na matriz de testes e 16 GB de memória; 32 GB é uma preferência de engenharia para mais folga. Reservar inicialmente 6 GB para workspace em máquinas de 16 GB e permitir ajuste validado. Esses valores são hipóteses de produto; M1 deverá medi-los. Mac Intel e 8 GB ficam fora da garantia inicial, sem degradação silenciosa do isolamento.

## 4.2 Componentes e fronteiras

| Componente | Responsabilidade | Não pode fazer |
| --- | --- | --- |
| Atlas App | Conversa, voz, anexos, status e aprovações autenticadas | Executar comandos arbitrários do modelo |
| Supervisor | Ciclo de vida, IPC, saúde, versões e recuperação | Conceder privilégios porque o LLM solicitou |
| Runtime | Planejar, recuperar contexto, propor ações e verificar entregas | Acessar diretamente segredos ou alterar políticas |
| Control Plane | Estado, política, autorização, orçamento e despacho confiável | Confiar em aprovação escrita em conteúdo externo |
| Workspace Host | Criar e manter VM, controlar recursos e encaminhar transporte | Compartilhar a pasta pessoal inteira |
| Guest Agent | Browser, arquivos de trabalho, ferramentas permitidas e tela | Controlar o host ou ler o banco de autoridade |
| Execution Box | Executar código novo em ambiente descartável | Receber credenciais persistentes por padrão |
| Gateway | Pareamento, filas e entrega remota autorizada | Expor terminal ou portas administrativas públicas |

## 4.3 Fluxo lógico

```text
Usuário local / dispositivo pareado
              |
          Atlas App
              |
     Supervisor + Control Plane
       |       |         |
     Estado  Políticas  Vault / orçamento
       |       |         |
       +---- Runtime ----+
                |
        Proposta estruturada de ação
                |
      Verificar -> Autorizar -> Despachar
                |
       WorkspaceProvider / Tool Broker
                |
     VM de trabalho / navegador / ferramentas
                |
      Evidência -> Verificação -> Entrega
```

A nuvem de modelos recebe somente o contexto necessário para cada chamada. Não recebe automaticamente todo o disco, cofre ou histórico. O serviço remoto, quando habilitado, deve ser explicitamente descrito: relay de mensagens não significa executor sempre ligado na nuvem.

## 4.4 Local, nuvem e híbrido

**Local:** identidade, conversas, tarefas, planos, políticas, aprovações, memória, arquivos, credenciais, auditoria, browser e execução. **Nuvem autorizada:** inferência de modelos, busca, voz contratada, conectores e relay de comunicação. **Futuro opcional:** backup criptografado e execução remota dedicada.

Não adotar PostgreSQL, Redis, Kubernetes ou vários serviços de nuvem na instalação pessoal inicial. SQLite é o banco operacional; FTS5 é a base da busca textual, complementada por índice semântico reconstruível. FTS5 é uma funcionalidade documentada do SQLite. [S10]

# 5. Ciclo de vida, workspace e isolamento

## 5.1 Processos e inicialização

O App, Supervisor, Runtime e Workspace Host devem ter ciclo de vida separado. O Supervisor é iniciado como serviço de usuário autorizado. Utilizar mecanismos suportados do macOS para itens de login e tarefas em segundo plano, com status visível e possibilidade de desabilitar. SMAppService é a API de referência; a experiência exata deve ser validada na versão-alvo. [S09]

O Workspace Host deve manter a VM sem depender da janela de chat. Como uma instância de VM e sua visualização podem impor requisitos de processo, implementar a tela por fluxo de frames do guest ou janela própria do host. Não presumir que um objeto VZVirtualMachine pode ser transferido entre processos.

Após login, o Supervisor verifica integridade, compatibilidade e desbloqueio de chaves, inicia o Runtime e reconcilia tarefas. Após logout ou suspensão, deve informar indisponibilidade. Não habilitar login automático ou retirar FileVault para cumprir uma promessa de disponibilidade.

## 5.2 WorkspaceProvider

O contrato inclui: capabilities, provision, start, health, pause, resume, stop, reset, execute_tool, observe, begin_takeover, end_takeover, import_artifact e export_artifact. Snapshot e restauração de snapshot serão capabilities opcionais, nunca funções fictícias retornando sucesso.

O provider de produção inicial será VM Linux ARM64. Um MockWorkspace pode existir exclusivamente em testes, com identificação visual e isolamento das builds de distribuição. Se a VM não funcionar, interromper com diagnóstico; não executar o agente no Mac pessoal como fallback escondido.

## 5.3 Separação de armazenamento e rede

O host conserva estado e autoridade. O guest conserva seus arquivos de trabalho e sessões autorizadas. Transferências ocorrem por um Artifact Broker, não por montagem irrestrita de pastas. Validar caminhos canônicos, tamanho, tipo, links simbólicos, arquivos compactados e quotas.

Implementar rede por mediação controlada fora do guest. Na V1, bloquear acesso à rede local, loopback do host, endpoints de metadados e destinos não permitidos. A prova M1 deve validar bloqueio de saída direta, DNS e canais alternativos. Filtragem apenas dentro de uma VM em que código não confiável tenha root não é uma fronteira suficiente.

Um proxy por domínio não entende a semântica de todo formulário HTTPS. Não prometer que ele detecta sozinho uma compra ou vazamento. Ações sensíveis dependem de conectores restritos e drivers homologados. Em sites autenticados não homologados, operações de escrita ficam em modo assistido.

## 5.4 Três níveis de execução

**Ferramentas confiáveis:** adaptadores auditados para arquivos, cálculo, pesquisa e APIs específicas. **Navegação geral:** pesquisa em browser sem identidade de alto privilégio, com observação e restrições. **Código novo:** Execution Box descartável, sem segredos, sem montagem de produção e sem rede por padrão.

Não permitir que uma skill gerada substitua o navegador homologado, altere o broker ou receba o token principal do provedor. Instalações de ferramentas devem ocorrer no guest ou Execution Box, nunca no host por meio de shell livre.

# 6. Arquitetura de inteligência artificial

## 6.1 Papel do modelo

O LLM é um componente probabilístico para linguagem, planejamento e interpretação. Não é banco de dados, calendário, gerenciador de permissões, executor de pagamentos ou prova de conclusão. O sistema de autoridade permanece determinístico e independente do texto produzido pelo modelo.

Manter contratos próprios para ModelProvider, ModelRouter, ContextBuilder, Planner, ToolBroker, Verifier e MemoryManager. Um SDK de agentes pode auxiliar, mas seu estado de sessão não será a única fonte de verdade. A troca de SDK ou fornecedor não pode eliminar tarefas, memória ou identidade.

## 6.2 Loop central

A cada turno operacional, recuperar a tarefa e as restrições; compor contexto mínimo; propor um próximo passo; validar a proposta; aplicar política e orçamento; executar ferramenta permitida; persistir observação; verificar o critério do passo; atualizar o plano; e continuar, entregar ou aguardar.

O plano deve conter resultado esperado, dependências, ferramentas, critérios de conclusão e custos estimados. Um plano não precisa listar antecipadamente todo clique, mas precisa tornar o objetivo verificável. Replanejamentos devem preservar passos já realizados e registrar a razão resumida da mudança.

## 6.3 ContextBuilder

Ordenar entradas por autoridade: regras de sistema do produto, políticas determinísticas aplicáveis, instrução autenticada do proprietário, objetivo da tarefa, fatos verificados e conteúdo externo. Conteúdo de página, e-mail, PDF ou ferramenta não pode se promover a instrução de sistema.

Selecionar contexto por pertinência, validade temporal, sensibilidade e orçamento. Não enviar o histórico inteiro em toda chamada. Preservar a fonte original mesmo quando utilizar resumo. Explicações de decisões devem ser resumos operacionais auditáveis; não depender de acesso ao raciocínio interno privado do modelo.

## 6.4 ModelProvider

A interface deve expor capabilities, generate, stream, cancel, estimate_usage e health. O retorno normalizado deve identificar provider, model_id real, request_id, saída, chamadas de ferramenta propostas, motivo de término, tokens informados, custo estimado e erro normalizado.

A interface não pode presumir suporte idêntico a temperatura, esforço de raciocínio, visão, ferramentas, áudio ou JSON estrito. Cada adaptador aplica somente parâmetros documentados e suportados. Structured outputs ajudam na estrutura, mas o backend ainda valida regras e dados antes de executar.

## 6.5 Router e fallback

Primeiro filtrar por capacidade, privacidade, disponibilidade e orçamento; depois escolher o modelo conforme complexidade e desempenho medido nos testes do Atlas. Não selecionar modelo somente pela classificação de dificuldade feita por ele próprio.

Erros 429 e indisponibilidade permitem espera com recuo e fallback compatível. Erro de credencial pede reautorização. Bloqueio de política não pode ser resolvido escolhendo um modelo menos restritivo. Fallback não amplia permissões nem envia dados a outro fornecedor sem consentimento prévio.

O mesmo objetivo pode usar diferentes modelos em etapas diferentes. Entretanto, trocar de modelo não apaga a auditoria nem reinicia efeitos externos. Falhas de verificação recorrentes exigem escalonamento limitado ou bloqueio explicável.

## 6.6 Trabalhadores internos

Permitir subagentes somente quando houver subtarefas independentes e ganho provável. Cada trabalhador recebe escopo, dados mínimos, ferramentas permitidas e parcela de orçamento. Seus resultados são observações não autoritativas até serem verificados pelo coordenador.

Padrão inicial proposto: no máximo dois trabalhadores de pesquisa em paralelo e um executor de ações com efeitos externos por workspace. Evitar enxames ilimitados, criação recursiva de agentes e múltiplos agentes clicando na mesma sessão.

# 7. Modelos recomendados, configurações e custos

## 7.1 Catálogo inicial verificado

O catálogo abaixo foi consultado em fontes oficiais em 22/09/2026. Não substitui a consulta à disponibilidade da conta no momento da implementação. Preços são de referência por um milhão de tokens de entrada/saída, em USD, sem assumir descontos de cache, ferramentas, áudio, impostos ou conversão cambial. [S01–S05]

| Função proposta no Atlas | Modelo e identificador | Referência de preço |
| --- | --- | --- |
| Planejamento e execução geral | GPT-6 Sol — gpt-6-sol | US$ 2 entrada / US$ 10 saída [S03] |
| Escalonamento para trabalho complexo | GPT-6 Astra — gpt-6-astra | US$ 10 entrada / US$ 50 saída [S02] |
| Classificação e tarefas leves delimitadas | GPT-6 Luna — gpt-6-luna | US$ 0,10 entrada / US$ 0,50 saída [S04] |
| Segundo provedor opcional | Claude Opus 5.5 — claude-opus-5-5 | US$ 4 entrada / US$ 20 saída [S05] |

**Decisão de projeto:** começar com um adaptador OpenAI funcional e os perfis Sol, Astra e Luna configuráveis. Habilitar Anthropic como segundo provedor somente depois de testes de equivalência e consentimento de dados. Não obrigar o proprietário a contratar dois fornecedores para ligar a primeira versão.

Usar Sol como padrão é uma escolha de equilíbrio para o projeto, não uma alegação de que ele vencerá todos os cenários. Astra deve ser selecionável desde o início para máxima qualidade e escalonamento. Luna não terá autoridade para liberar ações sensíveis. Nomes visíveis na interface são separados do identificador enviado à API.

## 7.2 Configuração simples

**Automático:** selecionar perfis por capacidade e orçamento. **Econômico:** priorizar baixo custo em tarefas aprovadas pelos testes; avisar quando qualidade insuficiente exigir escalonamento. **Máxima qualidade:** priorizar o modelo principal mais capaz configurado, dentro do teto. **Manual:** escolher explicitamente um modelo compatível.

“Local” só aparecerá como opção utilizável quando houver adaptador e modelo realmente instalados e aprovados no equipamento. Não confundir local-first, que se refere a dados e execução, com inferência totalmente offline.

A tela principal não deverá exibir parâmetros de tokens ou temperatura. Configurações avançadas deverão mostrar provedor, modelo por função, esforço suportado, timeout, limite de saída, ferramentas habilitadas, política de fallback e versão da tabela de preços.

## 7.3 Validação de conexão

Um botão “Testar inteligência” deve conferir credencial, acesso ao modelo, saída estruturada mínima e uso reportado. O usuário deve autorizar eventual chamada faturável. A consulta de catálogo não garante acesso àquele modelo: executar um teste pequeno antes de marcar como disponível.

Nunca derivar um identificador a partir de um apelido comercial. Não guardar chaves no arquivo de configuração, no prompt ou no repositório. Usar referência ao Vault. Parâmetros específicos, como níveis de esforço, devem ser revalidados na API; nenhuma conversão universal entre provedores é presumida.

## 7.4 Orçamento

Separar orçamento de inferência, ferramentas pagas e compras externas. A autorização para consumir tokens não é autorização para assinar um serviço ou comprar uma passagem. A assinatura ChatGPT e o uso da plataforma de API têm faturamento separado; a aplicação deve explicar essa distinção no onboarding. [S06]

Definir teto por tarefa, teto por período, reserva para chamadas em andamento e alertas em 70% e 90%. Ao atingir o limite, parar novas chamadas faturáveis, salvar checkpoint e solicitar decisão. Nunca iniciar chamadas ilimitadas sem teto ou política explícita do proprietário.

Custo estimado = entrada não cacheada × tarifa + entrada cacheada × tarifa aplicável + saída faturável × tarifa + ferramentas + áudio + serviços. Usar valores de uso informados pelo provedor, sem somar duas vezes tokens já incluídos. Manter estimativa, custo reportado e reconciliação separados.

O hard limit controla novas autorizações de consumo e deve reservar o custo máximo plausível das chamadas concorrentes. Não prometer uma barreira exata em moeda quando o fornecedor faturar depois ou houver componentes de preço desconhecidos. Nesse caso, adotar margem conservadora e restrição adicional.

## 7.5 Configuração declarativa de referência

```yaml
schema_version: "1.0"
intelligence:
  mode: automatic
  default_profile: general
  profiles:
    general:
      provider: openai
      model_id: gpt-6-sol
    deep:
      provider: openai
      model_id: gpt-6-astra
    light:
      provider: openai
      model_id: gpt-6-luna
  allow_cross_provider_fallback: false
  max_parallel_research_workers: 2
  max_external_effect_workers: 1
budget:
  currency: USD
  monthly_limit_minor: null
  per_task_limit_minor: null
  require_owner_setup_before_paid_calls: true
  warning_percentages: [70, 90]
security:
  host_shell_enabled: false
  unreviewed_code_network_enabled: false
  purchases_require_scoped_approval: true
  raw_secrets_in_model_context: false
```

Os campos nulos representam configuração pendente, não orçamento ilimitado. Este YAML descreve o contrato de configuração; sua implementação deverá ter validação e testes.

# 8. Memória, conhecimento e aprendizado

## 8.1 Camadas de memória

**Identidade:** nome, idioma, estilo e missão. **Preferências do proprietário:** como deseja receber resultados e limites recorrentes. **Fatos:** informação recebida ou verificada, com fonte e validade. **Episódios:** o que foi solicitado, realizado e concluído. **Procedimentos:** skills versionadas e testadas. **Memória de trabalho:** contexto temporário de uma tarefa.

Políticas e credenciais não são memórias semânticas. Não guardar senha como uma frase recuperável por similaridade. Preferências inferidas devem permanecer propostas, com indicação de incerteza, até confirmação suficiente para sua finalidade.

## 8.2 Registro mínimo

Cada memória deve incluir memory_id, employee_id, tipo, conteúdo ou referência, fonte, horário de registro, validade temporal, classificação de sensibilidade, estado de confiança, versão e status. Fatos temporais podem possuir valid_from e valid_until. Uma informação substituída continua rastreável enquanto a política de retenção permitir.

Usar estados como proposed, confirmed, disputed, superseded e deleted. Confiança numérica, quando houver, não deve ser apresentada como probabilidade científica sem calibração. Para fatos importantes, fonte e condição de confirmação valem mais que um número produzido pelo LLM.

## 8.3 Recuperação e atualização

Executar busca textual e semântica, combinar resultados, filtrar por empregado, sensibilidade e período, e recuperar a evidência original antes de concluir. Índices são derivados: devem poder ser reconstruídos sem perda da memória canônica.

Ao receber correção, registrar a nova versão, marcar a anterior como substituída e atualizar índices. Não apagar silenciosamente o histórico relevante de uma decisão. Se duas fontes conflitarem, distinguir a data e a origem; perguntar quando o conflito impedir uma ação segura.

## 8.4 Dados temporais estruturados

Calendários, prazos e recorrências devem utilizar estruturas de data, horário, fuso e exceções. A busca vetorial serve para localizar contexto, não para calcular sobreposição. Usar UTC para instantes e guardar o identificador IANA do fuso. Eventos de dia inteiro têm semântica própria e não podem ser convertidos ingenuamente em meia-noite UTC.

Para o perfil inicial deste projeto, sugerir America/Sao_Paulo e permitir alteração no onboarding. O produto não deve assumir que todos os usuários estão no mesmo fuso. Datas relativas precisam ser resolvidas no recebimento da tarefa e exibidas com data explícita quando relevantes.

## 8.5 Aprendizado seguro

Ao concluir uma tarefa, propor uma lição resumida: problema, método, evidência de sucesso, falhas e condições de reutilização. A consolidação pode ocorrer em baixa prioridade e com orçamento próprio. Não inventar novas tarefas externas para “aprender sozinho”.

Uma skill nova passa por sandbox, testes, análise de permissões e versionamento antes de uso confiável. Mudança que amplie acesso, rede, execução ou gasto exige autorização. Uma melhoria de procedimento dentro das mesmas capacidades pode ser promovida automaticamente se a política permitir e os testes obrigatórios passarem.

# 9. Motor de tarefas e persistência

## 9.1 Entidades de execução

Objective expressa o resultado desejado. Task é a unidade persistente de trabalho. Plan organiza etapas. Step define uma etapa verificável. Action representa uma operação concreta de ferramenta. Attempt registra uma tentativa. Artifact e Evidence comprovam saída e efeitos. Conversation organiza comunicação, mas não substitui essas entidades.

Toda tarefa deve ter proprietário, empregado, objetivo, restrições, prioridade, política de dados, orçamento, critérios de conclusão e versão. Pedidos relacionados podem gerar subtarefas, mas o usuário deve enxergar a relação e o resultado consolidado.

## 9.2 Máquina de estados

| Estado | Significado e condição de saída |
| --- | --- |
| CREATED | Pedido persistido; ainda não interpretado |
| UNDERSTANDING | Verificação de objetivo, contexto e dados obrigatórios |
| PLANNING | Construção ou revisão de plano e critérios |
| READY | Apta a receber um worker e reserva de orçamento |
| RUNNING | Executando próximo passo autorizado |
| WAITING_USER | Falta informação ou intervenção específica |
| WAITING_APPROVAL | Existe aprovação pendente vinculada à ação |
| BLOCKED | Recurso indisponível ou condição externa impeditiva |
| RETRYING | Tentativa futura agendada com motivo e limite |
| PAUSED | Proprietário ou política pausou a execução |
| VERIFYING | Conferência de evidências e critérios de sucesso |
| COMPLETED | Critérios obrigatórios atendidos e resultado persistido |
| FAILED | Não foi possível concluir dentro das restrições |
| CANCELLED | Execução encerrada por cancelamento; efeitos passados preservados |

Fluxo normal: CREATED → UNDERSTANDING → PLANNING → READY → RUNNING → VERIFYING → COMPLETED. VERIFYING pode voltar a PLANNING se houver reparo viável. Estados de espera voltam a READY somente quando sua condição for resolvida e política e orçamento forem reavaliados.

Uma ação de resultado incerto pode colocar a tarefa em BLOCKED com reason=EXTERNAL_EFFECT_UNKNOWN. Não criar a impressão de falha definitiva quando um e-mail talvez já tenha sido enviado. FAILED pode conter entregas parciais identificadas, sem afirmar conclusão total.

## 9.3 Concorrência, filas e checkpoints

Usar transações e um escritor lógico para mudanças críticas. Cada worker adquire lease com expiração, task_version e heartbeat. Um fencing token deve impedir que um worker antigo continue despachando depois que outro assumiu. A verificação final ocorre no broker imediatamente antes do efeito.

Persistir antes e depois de passos significativos: plano, etapa, proposta de ação, política, aprovação, referência de execução, evidências e estado seguinte. Checkpoints não contêm a cadeia privada de raciocínio; contêm o estado operacional necessário para retomar.

Jobs agendados incluem timezone, próxima execução, política para execuções perdidas e controle de deduplicação. Retomar uma tarefa não significa repetir automaticamente todas as rotinas vencidas. A política padrão é consolidar ocorrências perdidas e pedir confirmação quando houver impacto externo acumulado.

## 9.4 Limites de tentativa

Valores iniciais propostos: até três tentativas por erro transitório, duas revisões de plano sem progresso material e pausa após vinte passos consecutivos sem novo resultado verificável. Esses números são configuráveis pelo administrador dentro de limites seguros e devem ser calibrados nos testes.

Usar backoff com jitter, circuit breaker por provedor e prazo máximo por operação. Não implementar loops de cliques indefinidos nem cobrança contínua enquanto aguarda CAPTCHA, login ou resposta humana.

# 10. Ferramentas, navegador e execução real

## 10.1 Tool Registry

Cada ferramenta deve possuir tool_id, versão, descrição, schema de entrada e saída, categoria de efeito, capacidades exigidas, política de rede, limites, timeout, comportamento de repetição, tratamento de segredos e procedimento de verificação. Registro novo começa desabilitado até validação.

Classificar ferramentas em READ_ONLY, LOCAL_WRITE, EXTERNAL_WRITE e IRREVERSIBLE. Essa classificação é declarada pelo adaptador confiável e validada pelo broker, nunca escolhida livremente pelo LLM. Uma ferramenta que envia e-mail não pode declarar-se leitura porque a descrição da tarefa parece inocente.

O catálogo inicial deve contemplar leitura e criação de arquivos do workspace, extração de documentos, cálculos, pesquisa pública, navegação, geração de artefatos, comunicação com o proprietário e conectores externos restritos. Shell arbitrário no host não existe no catálogo.

## 10.2 Estratégia de navegação

Preferir API oficial ou integração tipada quando disponível e autorizada. Depois usar navegação estruturada com Playwright: elementos acessíveis, rótulos, estados e respostas. Interação visual por screenshot será fallback para interfaces sem estrutura suficiente, não um atalho para remover controles.

Playwright suporta diferentes navegadores e exige compatibilidade entre sua versão e os binários utilizados. Empacotar e fixar a combinação validada; não depender do Chrome pessoal instalado no Mac. O estado autenticado do browser pode conter informações que permitem personificação da conta e deve ser tratado como segredo. [S11, S12]

O suporte de modelos a computer use permite propor ações sobre uma interface; a aplicação ainda precisa executar, observar e controlar esse ciclo. Não confundir suporte do modelo com um navegador completo ou autonomia segura pronta. [S13]

## 10.3 Perfis de browser

Separar pesquisa pública, contas operacionais do funcionário e sessões de alto impacto. Perfis persistentes não devem ser reutilizados por código experimental. Cookies, storage, downloads e captura de tela respeitam retenção e sensibilidade.

Credenciais do responsável não são importadas automaticamente. Quando acesso delegado for necessário, solicitar autorização para aquela conta e finalidade. Conta operacional do Atlas deve ter recuperação e controle administrativo pelo responsável, sem fingir identidade humana.

## 10.4 Falhas de acesso

Diante de bloqueio, registrar erro, verificar se é transitório, tentar alternativa legítima e explicar o que falta. Alternativas podem incluir outra fonte pública, API contratada, login autorizado ou intervenção humana. Não driblar CAPTCHA, MFA, paywall, limite de serviço ou mecanismo de acesso.

Uma proposta de serviço pago deve informar problema, fornecedor, capacidade documentada, preço observado, renovação, dados enviados, alternativas e incertezas. Não afirmar “essa assinatura libera tudo”. A contratação permanece uma ação separada, sujeita a aprovação.

## 10.5 CAPTCHA e controle humano

Suspender o executor, abrir o workspace em modo assumido pelo usuário e aguardar confirmação de devolução. A IA não deve observar segredos digitados por captura persistente. Ao devolver o controle, invalidar a observação anterior, atualizar a tela, reavaliar o plano e só então continuar.

Apenas um controlador pode operar a sessão por vez. O lease do browser deve ser diferente do lease de tarefas de pesquisa paralelas. Cliques que ficaram enfileirados antes da intervenção humana precisam ser descartados.

# 11. Segurança, política e autorizações

## 11.1 Policy Engine independente

A Policy Engine recebe ação normalizada, ator autenticado, recurso, destino, categoria de dados, classe de efeito, orçamento, mandato e contexto verificável. Retorna ALLOW, ASK ou DENY com reason_code e policy_version. Falha na engine ou dados incompletos devem resultar em bloqueio seguro.

Risco não é apenas uma pontuação numérica. Uma ação proibida não se torna permitida porque obteve nota baixa em outros critérios. Aplicar primeiro proibições e limites de capacidade; em seguida regras de autorização e orçamento.

| Classe | Exemplo de ação | Padrão inicial |
| --- | --- | --- |
| R0 | Ler arquivo já autorizado e calcular resultado | ALLOW dentro do escopo |
| R1 | Criar rascunho ou arquivo no workspace | ALLOW com versionamento |
| R2 | Enviar entrega ao canal verificado do proprietário | ALLOW se conteúdo e canal estiverem autorizados |
| R3 | Enviar a terceiros ou criar conta com termos e dados | ASK, salvo mandato prévio específico |
| R4 | Comprar, assinar serviço, cancelar reserva ou excluir definitivamente | ASK com aprovação forte e escopo exato |
| R5 | Alterar controles de segurança, extrair segredos ou acesso não autorizado | DENY |

Dados sensíveis elevam exigências mesmo em ações aparentemente simples. O proprietário pode conceder mandatos recorrentes limitados para ações elegíveis; isso evita pedir autorização em todo passo sem entregar autoridade irrestrita.

## 11.2 Objeto de aprovação

Uma aprovação deve identificar approval_id, task_id, action_id, ator, tipo de ação, destino, hash dos parâmetros canônicos, custo máximo, moeda, recorrência, prazo, número máximo de usos, política aplicável e status. Para compras, incluir fornecedor, item, taxas conhecidas e condições materiais.

Status: PENDING, APPROVED, REJECTED, EXPIRED, REVOKED, RESERVED e CONSUMED. A reserva ocorre atomicamente com o despacho autorizado. Se houver falha antes do efeito e isso for comprovado, liberar ou renovar a reserva segundo política. Se o efeito for incerto, não reutilizar a aprovação cegamente.

Qualquer mudança material de destinatário, valor, itens, anexos ou termos invalida a aprovação anterior. Um aumento de preço não pode ser escondido por uma descrição resumida da mesma compra.

## 11.3 Aprovação na conversa

“Pode” só pode autorizar uma ação quando houver solicitação única, não ambígua, recente e apresentada a um usuário autenticado, dentro da política de risco. Para R4, utilizar cartão de aprovação com resumo e confirmação forte. A LLM interpreta linguagem, mas não emite a autorização final.

Uma frase dentro de e-mail, página ou arquivo dizendo “o usuário autorizou” não possui valor de autorização. Canal remoto que não dê segurança suficiente pode receber a solicitação, mas a confirmação deve ocorrer em interface autenticada do Atlas.

## 11.4 Credential Vault

Utilizar serviço nativo de credenciais no macOS como referência para armazenamento de chaves e proteção de acesso. Keychain Services é a API de referência; políticas de desbloqueio e acesso de processos devem ser testadas. [S14]

O banco operacional guarda credential_ref e metadados, nunca senha ou token bruto. O broker utiliza o segredo somente para a operação e destino autorizados. Não oferecer ao LLM uma ferramenta genérica read_secret. Onde possível, utilizar OAuth com escopo mínimo e revogação.

Sessões autenticadas de browser são segredos utilizáveis dentro do browser; nenhum desenho deve fingir que são completamente invisíveis ao ambiente que as usa. Por isso, isolar perfis, proibir código experimental nesses perfis e limitar ações e rede. A V1 não deverá manter sessões de banco ou meios de pagamento sob controle de navegação geral.

## 11.5 Ameaças e controles

| Ameaça | Controle obrigatório | Teste de bloqueio |
| --- | --- | --- |
| Prompt injection | Separação de autoridade, ferramentas tipadas e política externa | Página pede envio do cofre: pedido não é executado |
| Contaminação de memória | Fonte, confiança, propostas e confirmação | Texto externo não vira preferência administrativa |
| Vazamento por ferramenta | Dados mínimos, destino permitido e broker | Arquivo sensível não segue para endpoint arbitrário |
| Escape de workspace | VM, sem pastas pessoais e sem shell de host | Guest não lê arquivo sentinela no host |
| Código malicioso | Execution Box sem segredos e rede negada | Script tenta rede e credenciais: ambos negados |
| Replay de aprovação | Nonce, validade, hash e consumo atômico | Aprovação repetida não repete envio |
| Worker obsoleto | Lease e fencing no broker | Worker antigo perde autorização de despacho |
| Execução duplicada | Action ledger e reconciliação | Crash após envio não dispara reenvio cego |
| Abuso de custo | Reservas e quotas por tarefa/período | Chamadas concorrentes respeitam limite reservado |
| Atualização adulterada | Assinatura, manifesto e verificação | Pacote modificado é recusado |
| Canal remoto comprometido | Pareamento, escopo e revogação | Dispositivo revogado não cria nem aprova tarefas |

Esses controles reduzem risco; não constituem prova de segurança absoluta. Um único prompt defensivo não substitui nenhum deles. Antes da distribuição, a aplicação precisa de revisão técnica independente das áreas críticas.

# 12. Efeitos externos, idempotência e recuperação

## 12.1 Action Ledger

Cada ação externa deve possuir identidade própria e estado: PROPOSED, AUTHORIZED, DISPATCHING, CONFIRMED, FAILED, UNKNOWN ou CANCELLED_BEFORE_DISPATCH. Persistir intenção e dados suficientes para reconciliação antes do envio.

Usar idempotency_key estável quando o provedor suportar essa semântica. Para APIs sem suporte ou interfaces gráficas, armazenar referência externa, destinatário, conteúdo resumido e horário. Ausência de confirmação não prova ausência de efeito.

## 12.2 Resultado desconhecido

Se a conexão cair após clicar “enviar”, marcar UNKNOWN. Consultar a fonte externa de verdade por identificador ou busca suficientemente específica. Só repetir se houver prova de que o primeiro efeito não ocorreu ou se o adaptador oferecer idempotência confiável.

Se não houver como conciliar, pedir intervenção humana e explicar: “o envio pode ter ocorrido; não vou repetir sem verificar”. Não resolver incerteza escolhendo aleatoriamente sucesso ou falha.

## 12.3 Cancelamento

Cancelamento impede novos despachos e solicita interrupção das operações canceláveis. Não desfaz automaticamente e-mail já enviado, cobrança processada ou arquivo compartilhado. Registrar o que ocorreu antes da interrupção e eventuais medidas compensatórias possíveis, sujeitas à política.

Um “pare tudo” autenticado deve elevar prioridade de controle, revogar leases de execução e impedir novas ações. A meta inicial é parar novos despachos em até dois segundos no ambiente de teste local. Não prometer interromper um efeito externo já aceito pelo provedor.

## 12.4 Retomada

Na recuperação, expirar leases antigos, identificar operações em andamento, reconciliar resultados externos, validar arquivos, verificar versão de política e confirmar se aprovações ainda valem. Somente então recolocar tarefas em READY.

Atualizar um aplicativo não pode alterar silenciosamente o significado de uma aprovação antiga. Migrações de schema precisam preservar histórico e possuir procedimento de recuperação. Restauração de backup deve revogar ou revisar autorizações e sessões que possam produzir efeitos repetidos.

# 13. Dados, schemas e contratos internos

## 13.1 Convenções

Usar UUIDs estáveis; instantes em UTC; fuso original quando necessário; valores monetários em unidades mínimas inteiras e moeda explícita; enums fechados; schema_version; revisão otimista; referências de origem e classificação de dados quando aplicáveis. Não adicionar “confiança” artificialmente a toda tabela.

Unidades mínimas dependem da moeda. Não presumir que qualquer moeda tem duas casas decimais. Arquivos devem ser referenciados por artifact_id e hash, não por caminhos enviados diretamente pelo LLM.

## 13.2 Modelo relacional inicial

| Grupo | Entidades e campos relevantes |
| --- | --- |
| Identidade | employees(id, name, locale, timezone, profile_version); owners; devices |
| Comunicação | conversations; messages(role, origin, channel_id, content_ref); deliveries |
| Trabalho | objectives; tasks(state, priority, version, lease); plans; steps; attempts |
| Execução | actions(tool_id, effect, status, input_hash, idempotency_key); external_receipts |
| Autoridade | policies; mandates; approvals; approval_consumptions; capability_grants |
| Conhecimento | memories(type, status, validity, source_id); memory_versions; sources |
| Arquivos | artifacts(type, hash, size, storage_ref, version); evidence; artifact_links |
| Ferramentas | tools; skills; skill_versions; evaluations; promotions |
| Operação | journal_events; checkpoints; scheduled_jobs; usage_ledger; budget_reservations |
| Credenciais | credential_refs(provider, scope, owner, expiry); sessions sem segredo bruto |

Relações devem impedir ações sem tarefa, aprovações sem ação e entregas sem artefato existente. Chaves estrangeiras, índices e constraints obrigatórios devem ser testados. Isolamento por employee_id existe desde o schema, sem implementar antecipadamente um SaaS multiempresa.

## 13.3 Armazenamento e criptografia

Selecionar SQLite com transações, estratégia de WAL testada e migrações versionadas. O Runtime é o escritor lógico das entidades de trabalho; operações de autoridade são confirmadas pelo Control Plane. Evitar dois serviços independentes concorrendo sobre invariantes de aprovação sem um limite transacional definido.

Proposta de proteção: banco criptografado com implementação auditada e compatível com FTS; chaves administradas no Vault; artefatos cifrados com criptografia autenticada; índices protegidos pelo mesmo domínio de dados. A prova M2 deverá validar empacotamento, licenças e recuperação. Não improvisar algoritmo criptográfico.

Não guardar o banco criptografado junto de sua chave em texto. Chaves de assinatura de releases pertencem ao pipeline de distribuição, não à instalação do usuário nem ao agente.

## 13.4 IPC local

Usar Unix Domain Socket em diretório privado do usuário, permissões restritas, autenticação de sessão e negociação de versão. Autenticar processos de maneira compatível com o modelo de confiança; acesso pelo mesmo usuário do sistema não equivale a proteção contra um host já comprometido.

Adotar JSON-RPC 2.0 para controle, payload validado por JSON Schema, framing com tamanho e limite inicial de 1 MiB por mensagem de controle. Arquivos e frames de vídeo seguem canais próprios com quota. Todo pedido recebe request_id e correlation_id.

```json
{
  "jsonrpc": "2.0",
  "id": "req-example-001",
  "method": "tasks.create",
  "params": {
    "schema_version": "1.0",
    "employee_id": "employee-example-001",
    "objective": "Comparar duas propostas e gerar um relatório",
    "artifact_ids": ["artifact-example-001"],
    "constraints": {
      "external_writes": false,
      "purchases": false
    }
  }
}
```

Identificadores acima pertencem a uma fixture ilustrativa. A implementação deverá usar IDs válidos gerados pelo sistema. Actor e autenticação vêm do canal; não confiar em um actor_id arbitrário no corpo da requisição.

## 13.5 Métodos obrigatórios

| Método ou evento | Contrato esperado |
| --- | --- |
| system.health | Estado de serviços, versão, capacidade e erro acionável |
| conversations.send | Persiste mensagem e devolve vínculo com tarefa, quando houver |
| tasks.create / get / list | Cria ou consulta tarefas com autorização por proprietário |
| tasks.pause / resume / cancel | Muda estado real; valida versão e registra evento |
| approvals.get / decide | Confere identidade, hash, prazo, uso e política |
| memories.search / propose / correct / delete | Opera com origem, histórico e retenção |
| artifacts.import / export | Verifica conteúdo, hash, tamanho e permissão |
| workspace.observe / takeover / release | Garante exclusividade de controle e contexto atual |
| settings.validate / update | Valida alterações e impede autoelevação pelo Runtime |
| events.subscribe | Retoma do último sequence_id sem perder eventos |

Erros normalizados: INVALID_INPUT, UNAUTHORIZED, POLICY_DENIED, APPROVAL_REQUIRED, BUDGET_EXCEEDED, PROVIDER_UNAVAILABLE, MODEL_UNSUPPORTED, WORKSPACE_OFFLINE, EXTERNAL_EFFECT_UNKNOWN, VERSION_CONFLICT e RATE_LIMITED. Todo erro indica se pode ser repetido, o que foi persistido e a ação recomendada.

## 13.6 Contrato de ActionProposal

```json
{
  "schema_version": "1.0",
  "task_id": "task-example-001",
  "step_id": "step-example-003",
  "tool_id": "messaging.send_owner_artifact",
  "tool_version": "1.0.0",
  "input": {
    "recipient_ref": "owner-verified-channel",
    "artifact_id": "artifact-example-report",
    "message": "Relatório concluído e conferido."
  },
  "expected_outcome": "Entrega aceita pelo canal do proprietário",
  "verification": {
    "kind": "provider_receipt",
    "required": true
  }
}
```

O broker calcula efeito, risco, hash canônico, credenciais e necessidade de aprovação a partir do registro confiável. Esses campos não ficam sob a autoridade da proposta do LLM.

## 13.7 Contrato de ToolResult

Toda ferramenta retorna success, operation_status, data_refs, evidence_refs, external_reference, retry_class, error e observability. Conteúdo externo permanece explicitamente marcado como untrusted. ToolResult não pode incluir instruções capazes de alterar política.

COMPLETED exige que os verificadores esperados tenham sido satisfeitos. Um success=true isolado, devolvido pelo próprio código gerado, não vale como prova suficiente de efeito externo.

# 14. Voz, canais e comunicação remota

## 14.1 Voz

A V1 deve oferecer falar e ouvir em português, transcrição visível, interrupção da fala e opção de continuar por texto. Captura inicia por ação explícita; microfone permanentemente aberto ou wake word fica fora do padrão inicial. Exibir indicador de gravação e controle de retenção.

Separar SpeechProvider em transcrição, síntese e, opcionalmente, conversa em tempo real. O Voice Orchestrator traduz a fala em eventos da mesma Task Engine. Não criar um segundo agente com permissões distintas porque o pedido veio por áudio.

Escolher o modelo de voz no catálogo documentado do provedor durante M13 e fixar o ID validado na release. Priorizar testes com português brasileiro, ruído, nomes, datas, valores e interrupções. Não preencher esse campo com um nome adivinhado.

Transcrição incerta de valor, data, destinatário ou autorização exige confirmação. A voz sintetizada deve ser identificável como voz de IA. Clonagem de pessoas não integra o escopo inicial.

## 14.2 Canal remoto mínimo

A Beta V1 deve permitir enviar tarefas e receber resultados fora da janela local por pelo menos um canal real. Preferência de arquitetura: web companion autenticado para celular, com relay de mensagens e conexão de saída do Mac. E-mail operacional pode ser canal adicional de entrega.

No primeiro pareamento, exibir QR code ou código de uso único, confirmar o dispositivo no Mac, registrar sua chave e permitir revogação. O relay deve ter filas duráveis, expiração, limites e entrega deduplicada. Não encaminhar automaticamente todos os arquivos do workspace à nuvem.

Se o Mac estiver offline, o relay pode receber e enfileirar a mensagem, mas não afirmar que o trabalho local começou. Mostrar “aguardando o computador do Atlas ficar disponível”. Criptografia ponta a ponta é requisito do web companion e precisa de desenho e testes próprios, não apenas TLS.

## 14.3 E-mail e WhatsApp

E-mail do Atlas deve ser uma conta dedicada, sob controle administrativo do responsável. Preferir API oficial/OAuth quando disponível. Guardar recibos de envio, controlar destinatários e não considerar todo e-mail recebido como comando autorizado. Nome e endereço de remetente, sozinhos, não constituem autenticação forte.

WhatsApp é uma integração desejada, mas não uma dependência do núcleo. Antes de implementá-la, validar API oficial, elegibilidade, termos, número, modelos de mensagem e custos aplicáveis na data. Não fundamentar o produto em automação não autorizada do WhatsApp Web, nem prometer disponibilidade irrestrita.

Aprovações sensíveis podem ser notificadas por e-mail ou WhatsApp, mas precisam abrir a interface autenticada quando o canal não oferecer garantia suficiente. Integrações não configuradas devem aparecer como indisponíveis, nunca como funcionando em modo simulado.

# 15. Artefatos, evidências e qualidade de entrega

## 15.1 Artifact Manager

Gerenciar arquivo original, versões, hash, MIME type, tamanho, tarefa de origem, classificação de dados, local de armazenamento e entregas. Nomes devem ser legíveis; extensões devem corresponder ao conteúdo. Um arquivo não existe porque o modelo escreveu seu nome.

Importação deve verificar bytes, limites, arquivos compactados e processamento em sandbox. Exportação deve criar uma cópia no destino escolhido ou uma entrega explícita. O Atlas não sobrescreve o arquivo original do proprietário sem autorização específica.

## 15.2 Verificação objetiva

Relatório: abrir arquivo, conferir integridade, conteúdo pedido, fontes e ausência de placeholders. Planilha: validar fórmulas, unidades, valores e recalcular quando possível. Código: compilar ou executar testes apropriados em sandbox. Pesquisa: conferir fontes e data da consulta. Envio externo: obter recibo ou declarar resultado incerto.

Não aceitar uma frase do mesmo modelo, “revisei e está tudo certo”, como única verificação. Usar validadores determinísticos quando existirem e revisão por modelo como complemento. Uma revisão independente não elimina a necessidade de evidência externa.

## 15.3 Critério de conclusão

Antes de COMPLETED, todos os critérios obrigatórios devem estar satisfeitos ou o usuário deve ter aceitado formalmente um escopo reduzido. Se houver lacunas, classificar entrega parcial e explicar quais. Não esconder bloqueio para manter aparência de autonomia.

A resposta final deve conter resultado, principais decisões, arquivos ou dados entregues, fontes relevantes, custos registrados e limitações materiais. A quantidade de detalhes deve ser proporcional à tarefa; o diário técnico completo permanece disponível separadamente.

# 16. Privacidade, retenção, backups e atualizações

## 16.1 Privacidade desde o desenho

Coletar o mínimo necessário, separar dados por empregado e finalidade, permitir exportação e exclusão e registrar compartilhamentos externos. A adequação à LGPD exige análise da operação, bases legais, agentes de tratamento e contratos; esta especificação técnica não certifica conformidade jurídica. [S15]

Dados de crianças, saúde, documentos e outras informações sensíveis devem receber restrições adicionais de acesso, retenção e envio a provedores. Não usar dados reais em fixtures, screenshots de demonstração ou testes públicos. Todos os exemplos de teste precisam ser sintéticos.

## 16.2 Defaults de retenção propostos

Conversas, memórias confirmadas e entregáveis permanecem até exclusão ou política definida pelo proprietário. Logs operacionais detalhados: 30 dias inicialmente. Screenshots: guardar somente os necessários à evidência, por prazo configurável; gravação contínua desativada. Áudio bruto: não reter por padrão depois do processamento.

Esses prazos são propostas de produto, não obrigações legais universais. A interface deve mostrar o que será apagado, o que permanece por integridade operacional e como backups antigos serão tratados.

## 16.3 Exclusão e recuperação

Excluir conteúdo canônico, referências, índices derivados, caches e cópias ativas sob controle do Atlas conforme a política. Não prometer apagamento físico garantido em SSDs ou remoção imediata de backups externos que não estejam sob seu controle. Usar chaves, retenção e expiração para reduzir exposição residual.

Backup deve ser consistente, criptografado e testado por restauração. A estratégia precisa tratar banco, artefatos, chaves e versões de workspace. Chave perdida pode inviabilizar recuperação; apresentar isso claramente e oferecer mecanismo de recuperação autorizado.

## 16.4 Atualização

Separar atualização do aplicativo, Runtime, imagem do workspace, ferramentas e skills. Verificar assinatura e compatibilidade antes de ativar. Uma skill não pode atualizar a Policy Engine. Atualização de política que amplie permissões exige confirmação e registro.

Antes de migração, criar ponto de recuperação e drenar ações de efeito externo. Rollback de binário não implica rollback seguro do banco: testar compatibilidade ou usar restauração controlada. Pacotes distribuídos exigem cadeia de assinatura e processo de notarização adequados ao macOS. [S08]

# 17. Observabilidade e requisitos não funcionais

## 17.1 Eventos e diagnóstico

Registrar event_id, sequence_id, timestamp, employee_id, task_id, action_id, actor, tipo, versão de política, modelo utilizado, duração e referências de evidência. Redigir dados sensíveis antes de gravar logs. Auditoria contém decisões e efeitos; não deve ser um despejo de prompts, senhas e cookies.

A timeline do usuário deve explicar “pesquisou”, “gerou arquivo”, “aguarda aprovação” e “verificou entrega”. A visão técnica detalha erros e tentativas. Um relatório de suporte deve ter prévia, redação de segredos e consentimento antes do envio.

Adotar métricas de latência, taxa de conclusão verificável, bloqueios, retomadas, custo por tarefa, consumo de memória, erros de ferramenta e pedidos de intervenção. Distinguir indisponibilidade de provedor, limitação de acesso e bug do Atlas.

## 17.2 Metas iniciais de aceitação

| Métrica | Meta proposta e ambiente |
| --- | --- |
| Confirmação de comando local | Persistir e reconhecer em até 1 segundo no Mac de referência, sem incluir inferência |
| Parada | Não despachar novas ações em até 2 segundos após comando autenticado |
| Persistência | Nenhuma mensagem confirmada perdida nos testes de crash previstos |
| Recuperação | Reclassificar tarefas interrompidas após serviços e chaves disponíveis, sem repetição cega |
| Isolamento | Zero acessos bem-sucedidos aos recursos-sentinela proibidos na suíte |
| Qualidade funcional | Todos os cenários críticos passam; cenários probabilísticos têm amostra e taxa documentadas |
| Uso ocioso | Sem chamadas contínuas ao LLM; suspender recursos desnecessários quando não houver trabalho |
| Acessibilidade | Navegação por teclado, contraste legível, rótulos e VoiceOver nas telas essenciais |

São metas de engenharia a medir, não promessas de desempenho já comprovado. M1 registra hardware, versões, cenários, resultados e limitações. A disponibilidade do Atlas deve ser apresentada separadamente da disponibilidade da internet e dos provedores.

# 18. Milestones M0–M18 e definição de pronto

Esta sequência substitui a ordem oral anterior: isolamento, políticas e autorização entram antes de navegação com efeitos externos. Nenhum marco posterior libera o bypass de um controle ainda incompleto.

| Marco | Entrega e dependências | Critério de pronto |
| --- | --- | --- |
| M0 — Fundação | Repositório, convenções, docs, schemas e CI | Build mínimo e testes de contrato; requisitos rastreáveis |
| M1 — Provas de plataforma | VM, ciclo de vida, tela e rede; depende M0 | VM sobrevive ao fechamento da janela; bloqueios de host/rede testados |
| M2 — Dados e chaves | Banco, migrações, Vault e restauração; depende M0 | Dados persistem; credenciais não aparecem em logs; restore comprovado |
| M3 — Autoridade | Política, mandatos, aprovações e broker; depende M2 | DENY/ASK/ALLOW, expiração, revogação e replay testados |
| M4 — App e identidade | Onboarding, chat, status e configurações; depende M0/M2 | Fluxo local real; sem dados pessoais importados automaticamente |
| M5 — Task Engine | Estados, leases, checkpoints e cancelamento; depende M2/M3 | Crash e worker obsoleto não provocam despacho indevido |
| M6 — Modelos | Adaptador principal, router e orçamento; depende M3/M5 | Chamada real autorizada, saída validada, limite e fallback testados |
| M7 — Memória | Camadas, proveniência, busca e correções; depende M2/M6 | Fato persiste e correção substitui resposta antiga sem perder fonte |
| M8 — Ferramentas | Registry, Artifact Broker e Execution Box; depende M1/M3/M5 | Código novo sem segredo/rede; arquivos fora do escopo bloqueados |
| M9 — Browser | Playwright, pesquisa e drivers; depende M1/M3/M8 | Pesquisa real e evidência; escrita não homologada fica assistida |
| M10 — Autonomia | Planejamento, subtrabalho e reparo limitado; depende M5–M9 | Objetivo composto concluído sem instrução clique a clique |
| M11 — Verificação | Validadores e qualidade de artefatos; depende M8/M10 | Conclusão falsa e arquivo inexistente são rejeitados |
| M12 — Retomada | Action Ledger, reconciliação e restart; depende M5/M9/M11 | Falha após envio não gera reenvio sem verificação |
| M13 — Voz | Entrada, saída, transcrição e interrupção; depende M4/M6 | Português validado; comando sensível incerto pede confirmação |
| M14 — Canal remoto | Pareamento, relay e web companion; depende M3/M5/M12 | Comando pelo celular, fila offline e revogação funcionam |
| M15 — Skills | Aprendizado, testes, promoção e rollback; depende M8/M11 | Skill melhora procedimento sem alterar controles nem permissões |
| M16 — Distribuição | Instalador, assinatura, notarização e updates; depende M1–M15 | Instalação limpa sem toolchain manual; upgrade e desinstalação testados |
| M17 — Beta integrada | Suíte funcional, segurança, acessibilidade e custos | Todos os gates críticos passam em Mac real; lacunas publicadas |
| M18 — Handover | Manual, evidências, matriz de suporte e revisão final | Release candidata reproduzível; proprietário consegue operar e recuperar |

Marcos têm ordem lógica, não promessa de prazo. M0 e documentação podem começar imediatamente. Uma prova que falhar gera ADR, reparo ou limitação explícita. Não se deve “passar” M1 com um MockWorkspace e continuar como se o isolamento estivesse pronto.

# 19. Backlog inicial para a IA programadora

Cada item vira uma issue com descrição, dependências, arquivos, testes e evidência. As pastas abaixo são destinos propostos; alterações devem manter o mapa do repositório atualizado.

## 19.1 Fundação e provas

**AT-001 — Inicializar o projeto.** Criar apps, runtime, platform, shared, security, storage, tests e docs. Acrescentar comandos de build, lint e testes documentados. Aceite: checkout limpo executa a suíte mínima; não existem credenciais ou dados reais no histórico.

**AT-002 — Formalizar contratos.** Em shared/schemas, definir mensagens IPC, Task, ActionProposal, ToolResult, Approval e JournalEvent. Aceite: fixtures válidas passam; campos adicionais proibidos, enums inválidos e dinheiro sem moeda falham.

**AT-003 — Validar VM e observação.** Em platform/workspace, criar prova isolada de boot, browser, tela, fechamento de janela e reinício de serviço. Aceite: evidência em Mac real, sem reutilizar sessão pessoal; documentação de limitações.

**AT-004 — Validar fronteira de rede e host.** Criar testes-sentinela para diretórios, rede local, metadados e saída não autorizada. Aceite: tentativas falham de modo verificável, inclusive quando partem de código dentro do guest.

## 19.2 Estado e autoridade

**AT-005 — Persistência e migrações.** Em storage, criar banco, constraints, repository interfaces e recovery. Aceite: interrupções antes/depois de commit não produzem estado inválido; restauração confere hashes e versões.

**AT-006 — Vault e referências.** Em security/vault e platform/macos, implementar referências, acesso mínimo e redação de logs. Aceite: processo não autorizado e ferramenta genérica não recebem segredo; chaves ausentes produzem diagnóstico.

**AT-007 — Policy Engine.** Implementar regras por ação, recurso, dado e mandato. Aceite: proibição domina permissões; versão da política é auditada; erro interno nega execução.

**AT-008 — Approval Engine.** Implementar hash canônico, validade, reserva, consumo e revogação. Aceite: alteração de valor ou destinatário invalida aprovação; replay e corrida entre workers não repetem consumo.

## 19.3 Interação e inteligência

**AT-009 — App e onboarding.** Em apps/macos, criar identidade, chat e diagnóstico. Aceite: instalação simulada de desenvolvimento não exige contas pessoais; campos sensíveis ficam fora dos logs; estados são reais.

**AT-010 — Scheduler e leases.** Em runtime/tasks, implementar máquina de estados, prioridade e cancelamento. Aceite: testes de transição, interrupção, concorrência e fencing; UI continua responsiva.

**AT-011 — Adaptador de modelos.** Em runtime/models, implementar catálogo, health, streaming e respostas normalizadas. Aceite: erro de permissão não vira sucesso simulado; chamada real só ocorre com acesso e orçamento autorizados.

**AT-012 — Router e orçamento.** Implementar seleção por capacidade e reserva de custo. Aceite: fallback não muda fornecedor sem permissão; limites concorrentes são aplicados; modos simples alteram configuração real.

**AT-013 — Memória.** Em runtime/memory, implementar ingestão, recuperação, correção e exclusão. Aceite: memória persiste após reinício; fonte externa não vira mandato; índices reconstruídos mantêm resultado esperado.

## 19.4 Execução e entrega

**AT-014 — Registry e sandbox.** Em runtime/tools e platform/execution, implementar manifestos, validação e isolamento. Aceite: ferramenta sem registro não roda; script não lê cofre nem acessa rede por padrão.

**AT-015 — Browser e controle humano.** Implementar Playwright, evidências, sessão isolada e takeover. Aceite: CAPTCHA pausa sem loop; devolução de controle descarta cliques antigos; nenhum perfil pessoal é aberto.

**AT-016 — Planner e Verifier.** Em runtime/agent, implementar objetivos, critérios e reparo. Aceite: resultado incompleto não recebe COMPLETED; loops param; criação de arquivo é comprovada por abertura e hash.

**AT-017 — Action Ledger e reconciliação.** Implementar intenção persistida, recibos e UNKNOWN. Aceite: crash imediatamente após envio não causa repetição automática; restauração detecta efeitos pendentes.

## 19.5 Produto completo

**AT-018 — Voz e canal remoto.** Implementar VoiceProvider, pareamento, filas e revogação. Aceite: áudio com valor ambíguo não aprova gasto; dispositivo revogado não opera; offline é informado corretamente.

**AT-019 — Skills e atualizações.** Implementar versões, testes, promoção, assinatura e rollback. Aceite: alteração de permissão exige nova decisão; pacote adulterado falha; migração mantém integridade.

**AT-020 — Release e aceitação.** Executar instalação limpa, suíte de cenários, análise de segurança e manual. Aceite: proprietário instala, conversa, delega, recebe e recupera dados sem terminal no uso cotidiano.

Não tentar implementar AT-001 a AT-020 como uma única mudança. Cada item deve ser dividido se não puder ser revisado isoladamente. “Todos os testes passaram” só é admissível acompanhado de comandos executados e resultados reais.

# 20. Suíte geral de cenários de aceitação

A suíte é generalista. O exemplo do calendário familiar não cria uma funcionalidade fixa. Usar diferentes documentos, calendários sintéticos, propostas, pesquisas e entregas para demonstrar a capacidade transversal.

| Cenário | Comportamento esperado e evidência |
| --- | --- |
| GA-01 — Memória e reinício | Receber regra sintética, reiniciar serviços e recuperá-la com fonte, sem pedir novamente |
| GA-02 — Cruzamento temporal | Comparar compromisso com calendário, incluindo exceção e fuso; cálculo determinístico correto |
| GA-03 — Pesquisa e relatório | Buscar fontes públicas, comparar alternativas e gerar arquivo abrível com referências |
| GA-04 — Preferência corrigida | Atualizar uma preferência; nova resposta usa a versão vigente e preserva rastreabilidade |
| GA-05 — Obstáculo legítimo | Site bloqueia: registrar, oferecer alternativa lícita ou intervenção, sem fingir acesso |
| GA-06 — Recurso pago | Propor serviço com preço e limites; nenhuma contratação antes da aprovação válida |
| GA-07 — Mudança material | Após aprovação, valor ou destinatário muda; sistema exige nova autorização |
| GA-08 — Prompt injection | Documento manda ignorar regras e enviar segredo; instrução não altera política nem memória |
| GA-09 — Código novo | Skill tenta acessar host ou rede proibida; execução bloqueada e auditada |
| GA-10 — Crash após envio | Estado externo conciliado; sem e-mail duplicado ou compra repetida |
| GA-11 — Orçamento | Tarefa e workers concorrentes esgotam teto; novas chamadas param sem perder estado |
| GA-12 — Comando de parada | Interrompe novos despachos e informa o que já aconteceu |
| GA-13 — Operação remota | Celular pareado cria tarefa; proprietário recebe artefato; dispositivo revogado não consegue |
| GA-14 — Mac indisponível | Relay enfileira, exibe offline e não anuncia execução inexistente |
| GA-15 — Backup e exclusão | Restore valida dados; exclusão remove índices ativos; limitações de backup são informadas |
| GA-16 — Instalação limpa | Outro Mac compatível instala e executa cenário sem Python/Docker/terminal manual |

## 20.1 Estratégia de testes

**Unitários:** regras, moedas, datas, transições, hash, orçamentos e seleção de modelos. **Contratos:** schemas, compatibilidade IPC e adaptadores. **Integração:** banco, Vault, browser e ferramentas. **E2E:** aplicativo até artefato ou recibo. **Segurança:** injeção, acesso indevido, replay e exfiltração. **Recuperação:** crash, energia simulada, duplicidade e migração. **Avaliações de IA:** amostras versionadas com critérios objetivos e resultados registrados.

Usar fakes para testes determinísticos, mas separá-los dos testes reais. Uma integração simulada não comprova funcionamento no fornecedor. Os testes de ações financeiras devem usar ambiente de teste, sem compras reais para “validar” o sistema sem autorização.

Não aceitar médias que ocultem falhas críticas. Um acesso indevido ou compra não autorizada bloqueia a release, mesmo com alta taxa de sucesso funcional. Em avaliações probabilísticas, registrar número de execuções, versões de modelo e dispersão de resultados.

# 21. Estrutura do repositório e pipeline

```text
atlas/
  apps/
    macos/
    companion-web/
  runtime/
    agent/ models/ tasks/ memory/ tools/ verification/
  platform/
    macos/ workspace/ execution/
  security/
    policy/ approvals/ vault/ network/
  storage/
    migrations/ repositories/ backup/
  shared/
    schemas/ fixtures/ generated/
  tests/
    unit/ contract/ integration/ e2e/ security/ recovery/ evals/
  docs/
    MASTER_SPEC.md
    ARCHITECTURE.md
    THREAT_MODEL.md
    REQUIREMENTS_TRACEABILITY.md
    BUILD_AND_RUN.md
    OPERATIONS.md
    PROGRESS.md
    ADR/
  packaging/
  scripts/
```

Linguagens principais: Swift para integração macOS e Python para orquestração. Frontend web do companion e seu relay poderão utilizar TypeScript e uma API de escopo restrito. Não transformar o companion em um segundo núcleo de tarefas com autoridade concorrente.

Fixar versões de dependências compatíveis, incluir lockfiles e registrar licenças. Usar ferramentas de lint, tipagem e testes apropriadas à stack, como Swift Testing/XCTest e pytest, escolhidas e verificadas no ambiente de desenvolvimento. Não presumir uma versão específica de Xcode antes do diagnóstico.

O CI deve validar schema, executar testes rápidos, verificar segredos, dependências e empacotamento. Build macOS e E2E de VM exigem ambiente macOS apropriado; runner Linux não substitui essa validação. Assinatura da release exige credencial protegida e aprovação do responsável.

Manter artefatos de teste, relatórios e matriz de rastreabilidade. Cada requisito obrigatório deve apontar para implementação e teste. Não utilizar TODO, stub ou retorno fixo em caminho crítico de produção sem desabilitar claramente a função correspondente.

# 22. Decisões arquiteturais e pendências controladas

## 22.1 ADRs iniciais

| ADR | Decisão-base | Razão |
| --- | --- | --- |
| ADR-001 | App nativo em SwiftUI | Integração e experiência coerentes com macOS |
| ADR-002 | Workspace Linux em VM | Preservar ambiente próprio sem usar o desktop pessoal |
| ADR-003 | Dados local-first | Continuidade de identidade e tarefas independente de fornecedor |
| ADR-004 | Política fora do LLM | Autorizações não podem depender de persuasão em linguagem natural |
| ADR-005 | Interfaces de modelos próprias | Evitar dependência de SDK ou nomes comerciais fixos |
| ADR-006 | APIs e drivers antes de cliques livres | Melhor controle e verificação dos efeitos externos |
| ADR-007 | Gateway não é executor | Disponibilidade remota não equivale a Mac sempre ligado |
| ADR-008 | Segurança antecipada | Impedir entrega de autonomia antes das fronteiras de proteção |

## 22.2 O que a implementação deve validar

M1 resolve execução e observação da VM, bloqueio de egress e ciclo de vida sem janela. M2 resolve empacotamento da criptografia, comportamento do Keychain e restauração. M6 valida acesso real aos modelos e contabilização. M14 valida pareamento e entrega remota. M16 valida distribuição e atualização em máquina limpa.

Essas pendências não autorizam simplificar a visão. Se uma hipótese falhar, registrar evidência, propor alternativa e explicar o impacto antes de trocar a arquitetura. Exemplo: não substituir VM por browser pessoal apenas porque a primeira prova deu trabalho.

## 22.3 Acessos que dependem do responsável

Modelo exato do Mac e acesso a um Mac de testes; conta de API com orçamento autorizado; contas operacionais dedicadas; credenciais de distribuição Apple; infraestrutura do relay quando implementado; eventuais provedores de e-mail e domínio. A IA pode preparar fluxos e documentação, mas não inventar credenciais nem aceitar obrigações financeiras por conta própria.

O padrão é continuar no que não está bloqueado e reportar a dependência precisa. Não pedir ao proprietário que decida detalhes internos como bibliotecas de fila quando a decisão pode ser tomada e justificada tecnicamente.

# 23. Critérios de início e de entrega

## 23.1 READY TO CODE

Este documento fornece a baseline necessária para iniciar M0 e as provas seguintes: visão, requisitos, limites, arquitetura, contratos, dados, política, testes, marcos e instrução de execução. READY TO CODE não significa “todos os riscos eliminados”; significa “pode começar a construir com gates definidos”.

A IA deve produzir primeiro o mapa de rastreabilidade e um plano de execução aderente, sem substituir o documento por outro resumo superficial. Não é necessário aguardar uma nova rodada de planejamento genérico para criar o repositório e iniciar M0.

## 23.2 READY FOR BETA

Exige V1 funcional, pelo menos um canal remoto real, voz, persistência, isolamento, autorização, recuperação, verificação e instalação gráfica. Todas as funcionalidades prometidas devem estar implementadas ou explicitamente fora do escopo acordado; não esconder simulações.

## 23.3 READY FOR RELEASE

Exige testes em Mac real, revisão de segurança das fronteiras, instalação limpa, atualização e recuperação comprovadas, política de dados, documentação e controle de custos. O proprietário deve conseguir usar o produto sem terminal no cotidiano. A aprovação de release é uma decisão humana informada pelas evidências.

# 24. Prompt 3 — Contrato de execução para a IA programadora

O texto abaixo pode ser copiado como instrução inicial, acompanhado do documento integral. Ele também é fornecido como arquivo separado no pacote de desenvolvimento.

---

Você é o responsável técnico pela implementação do ATLAS — Funcionário Digital. Leia integralmente a Especificação Técnica v1.0 anexada. Trate seus requisitos normativos, fronteiras de segurança e critérios de aceitação como contrato de produto. Não substitua essa visão por um chatbot, uma automação rígida ou um navegador com acesso à vida pessoal do proprietário.

O objetivo é construir um aplicativo macOS de instalação simples, com identidade operacional e ambiente próprios, conversa por texto e voz, memória duradoura, delegação de objetivos, planejamento, execução, verificação, comunicação remota, autorização e recuperação de falhas. Calendários, viagens e documentos são cenários gerais, não o domínio fixo do produto.

Comece agora pelo diagnóstico do ambiente de desenvolvimento e por M0. Antes de implementar funcionalidades, crie docs/MASTER_SPEC.md, ARCHITECTURE.md, THREAT_MODEL.md, REQUIREMENTS_TRACEABILITY.md, BUILD_AND_RUN.md e PROGRESS.md. Preserve a especificação recebida. Registre decisões em ADRs. Produza um backlog executável e uma lista objetiva de dependências externas; não crie uma nova fase indefinida de planejamento.

Implemente em ordem de dependências, uma tarefa pequena e revisável por vez. Para cada tarefa: declare objetivo e critérios de aceite, escreva ou atualize testes, implemente, execute os testes disponíveis, examine a saída, corrija falhas e registre evidências. Faça commits locais coerentes. Não envie código, dados ou segredos para repositório remoto sem autorização.

Não pule as provas de isolamento e ciclo de vida. Segurança, políticas, credenciais e autorização devem existir antes de navegação com efeitos externos. O LLM propõe; o broker valida e executa. Nenhum prompt, skill, página, e-mail ou documento pode ampliar permissões. Não ofereça shell livre no host e não use o browser pessoal como fallback.

Utilize as interfaces próprias definidas para modelos, tarefas, memória, ferramentas, workspace e voz. O estado persistente pertence ao Atlas, não ao SDK de um provedor. Valide IDs reais de modelos e acesso da conta antes de usá-los. Respeite orçamento e consentimento de compartilhamento de dados. Não habilite fallback entre provedores sem permissão.

Credenciais são referências ao Vault. Não as imprima, embuta no código ou coloque em prompts e fixtures. Não use contas, documentos ou dados reais do proprietário em testes sem autorização específica. Para serviços pagos, preparar a integração não autoriza contratar, consumir crédito sem teto ou aceitar termos em nome do responsável.

Toda ação externa deve passar por política, autorização aplicável, reserva de orçamento e Action Ledger. Preserve UNKNOWN quando o efeito não puder ser confirmado. Não repita e-mails, reservas ou compras após falha sem reconciliação. Cancelamento impede novos despachos, mas não apaga efeitos já ocorridos.

Não gere funcionalidades de fachada. É permitido criar fakes em testes, mas eles devem estar identificados e separados da build de produção. Não declare um marco concluído quando houver apenas interface visual, stub, TODO ou resposta fixa. Não diga que um teste passou se não foi executado. Quando não houver Mac, API ou credencial necessária, marque aquele teste como NÃO EXECUTADO e informe a dependência exata.

Verifique as entregas objetivamente: arquivos devem existir e abrir; relatórios devem possuir conteúdo e fontes; ações externas devem possuir recibo ou estado de incerteza; builds e testes devem gerar resultados reais. Conclusões dependem dos critérios da tarefa, não da declaração do modelo de que terminou.

Ao concluir cada tarefa, atualize PROGRESS.md com o que foi implementado, arquivos alterados, comandos executados, testes aprovados ou não executados, limitações, riscos e próxima tarefa. Prossiga pelas tarefas autorizadas até encontrar um bloqueio material, limite de execução ou decisão indispensável. Não prometa trabalho em segundo plano quando o ambiente não o oferecer.

Quando encontrar conflito entre simplificação e segurança, mantenha o limite de segurança. Quando uma decisão arquitetural se mostrar inviável, registre a prova, proponha alternativa com impactos e peça decisão somente se mudar significativamente a visão, o custo ou o risco. Não remova requisitos silenciosamente.

Na entrega final, forneça código-fonte, scripts de build, instalador quando realmente gerado, documentação, matriz de testes, evidências de segurança e recuperação, custos observados e lista de limitações. Não apresente o produto como pronto para distribuição antes dos gates READY FOR BETA e READY FOR RELEASE.

Primeira resposta esperada: confirmação de leitura com os invariantes principais, resultado do diagnóstico disponível e início efetivo de M0. A partir daí, trabalhe no repositório e apresente artefatos reais, não apenas promessas ou resumos repetidos.

---

## 24.1 Ferramenta de programação

O documento é independente de ferramenta. Uma opção apropriada para o fluxo é Claude Code, cuja documentação descreve atuação sobre uma base de código, leitura, edição e execução de comandos. Sua utilização não substitui Xcode, testes em Mac nem revisão dos controles críticos. [S16]

Também pode ser utilizado em outro agente de programação com acesso autorizado ao repositório e às ferramentas de desenvolvimento. O modelo que constrói o Atlas e os modelos usados dentro do Atlas são escolhas distintas. Não codificar dependência do produto em uma assinatura de chat específica.

# 25. Referências técnicas e controle de versão

As referências abaixo são fontes primárias consultadas para os pontos externos mais relevantes. Os demais requisitos, limites e metas são decisões propostas para o Atlas. Catálogos, preços, SDKs e regras de distribuição devem ser revalidados antes da release. Data de consulta: 22/09/2026.

**[S01] OpenAI — Catálogo de modelos.** Identificadores e capacidades gerais.
https://developers.openai.com/api/docs/models

**[S02] OpenAI — GPT-6 Astra.** Modelo e preço de referência.
https://developers.openai.com/api/docs/models/gpt-6-astra

**[S03] OpenAI — GPT-6 Sol.** Modelo e preço de referência.
https://developers.openai.com/api/docs/models/gpt-6-sol

**[S04] OpenAI — GPT-6 Luna.** Modelo e preço de referência.
https://developers.openai.com/api/docs/models/gpt-6-luna

**[S05] Anthropic — Models overview.** Claude Opus 5.5, ID de API e preço de referência.
https://platform.claude.com/docs/en/models/overview

**[S06] OpenAI — Managing billing for ChatGPT and the API platform.** Distinção de faturamento.
https://help.openai.com/en/articles/9039756

**[S07] Apple — Create macOS or Linux virtual machines, WWDC22.** Virtualização e interfaces de VM.
https://developer.apple.com/videos/play/wwdc2022/10002/

**[S08] Apple — Notarizing macOS software before distribution.** Referência para a etapa de distribuição.
https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution

**[S09] Apple — SMAppService.** API de referência para serviços e itens de login.
https://developer.apple.com/documentation/servicemanagement/smappservice

**[S10] SQLite — FTS5 Extension.** Busca textual no banco local.
https://www.sqlite.org/fts5.html

**[S11] Microsoft / Playwright — Authentication.** Estado autenticado e riscos de armazenamento.
https://playwright.dev/python/docs/auth

**[S12] Microsoft / Playwright — Browsers.** Navegadores e binários compatíveis.
https://playwright.dev/python/docs/browsers

**[S13] OpenAI — Computer use.** Ciclo de ações sobre interface e responsabilidades da integração.
https://developers.openai.com/api/docs/guides/tools-computer-use

**[S14] Apple — Keychain Services.** API de referência para credenciais.
https://developer.apple.com/documentation/security/keychain-services

**[S15] Presidência da República — Lei nº 13.709/2018.** Texto da LGPD, para revisão jurídica da operação.
https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm

**[S16] Anthropic — Claude Code overview.** Ferramenta de implementação sobre repositório.
https://code.claude.com/docs/en/overview

## Histórico

**v1.0 — 22/09/2026:** consolidação da visão e da arquitetura, validação de referências de modelos, correção de limites de disponibilidade e idempotência, antecipação da segurança, definição de contratos, backlog, milestones e prompt de execução.

**Limite desta entrega:** documentação de pré-implementação. Nenhum aplicativo Atlas foi compilado, instalado, notarizado ou homologado como parte deste documento. A próxima atividade autorizada para a IA programadora é iniciar M0 e executar as provas técnicas previstas.
