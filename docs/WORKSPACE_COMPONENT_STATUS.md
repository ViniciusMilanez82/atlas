# Computador independente — componente experimental, não entregue no aplicativo

## Situação desta branch

Esta branch preserva a Alpha e seu instalador existente. Acrescenta somente o componente Linux,
seus scripts de construção, o protocolo limitado, a mediação pública de rede e testes desses
componentes. As ferramentas novas NÃO estão registradas no aplicativo distribuído. Não há novo
instalador com o computador virtual funcionando.

A implementação mais ampla foi escrita e testada localmente. A gravação pelo conector GitHub de
um componente nativo de comunicação Mac/VM foi bloqueada pela plataforma, que informou não ser
possível determinar a segurança da solicitação. Não houve repetição por outra rota, codificação
alternativa, workflow de aplicação ou alteração das proteções. O componente bloqueado e suas
integrações dependentes não foram incluídos nesta publicação. Não substituir essa ausência por
execução no Mac pessoal ou por acesso irrestrito ao host.

## Componente que pode ser avaliado independentemente

- Imagem Linux ARM com raiz somente leitura e disco de dados separado, sem adaptador de rede.
- Serviço interno de comandos limitados: Python descartável e navegador Chromium.
- Código gerado em usuário não-root, namespaces, seccomp e limites de recursos. Sem alternativa
  de execução no host; sem pasta do navegador ou credenciais dentro do sandbox.
- Chromium utiliza pipes internos de depuração. Requisições públicas GET/HEAD passam por política
  do host; cookies, autenticação, POST e destinatários privados não são encaminhados.
- Testes do protocolo, caminhos, limites, cancelamento de pipes e mediação de rede com HTTP local.
- Workflow separado inicializa realmente o Linux em QEMU, verifica isolamento e navegação sobre
  conteúdo sintético. Imagem somente é disponibilizada se esses testes passarem.

## Evidência: não confundir escopos

A suíte local da implementação mais ampla terminou com 844 testes aprovados e 4 ignorados; esse
número NÃO comprova esta branch publicada nem funcionamento da VM no Mac. Esta branch precisa
ter seus próprios resultados de CI conferidos. Os testes locais não usaram modelo pago ou dados
pessoais. O programa de auto-teste existe somente na imagem de teste, não na imagem componente.

A integração por Virtualization.framework, interface de acompanhamento, transferência autorizada
com tarefas, cancelamento ponta a ponta e instalador atualizado permanecem NÃO ENTREGUES nesta
branch. Não há validação de boot em Mac físico. Não remover ou marcar como aprovados esses critérios.

## A V1 continua pendente

Ainda faltam integração final do computador e navegador, contas/e-mail operacionais, ciclo de
habilidades, acesso pelo celular, conversa contínua por voz, criptografia em repouso, serviço
residente, assinatura/notarização, atualização e validação integral com modelo real.
O instalador anterior permanece uma Alpha. Esta publicação não altera a main nem declara o
pedido de conclusão integral cumprido.
