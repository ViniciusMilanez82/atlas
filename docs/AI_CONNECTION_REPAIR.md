# Conexão de IA — reparo sobre PR13

## Problema e alcance
O diagnóstico da Alpha indicava serviços locais saudáveis e inteligência bloqueada, mas ocultava o
motivo. Uma chave colada não comprovava salvamento de configuração, aceite de preços ou validação.
O relatório antigo não permite concluir se uma chave é válida ou se o projeto tem crédito. Não foi
utilizada a chave do proprietário nos testes desta entrega.

## Implementação
- Botão **Conectar IA**, acessível antes e depois do onboarding. Lê o estado autenticado existente,
  reconhece a chave já guardada e a reutiliza quando o campo de substituição fica vazio.
- Fluxo explícito **Salvar e conectar** com confirmação de custo: preserva privacidade e pesquisa,
  salva modelo/orçamento/revisão e solicita uma validação. Falha de salvamento impede a chamada.
- O aceite de preços permanece uma decisão do dono. Nenhuma permissão, teto ou conta é liberado
  automaticamente. Preços continuam estimativos. Credenciais não são devolvidas ao painel.
- Validação em conexão IPC separada, com 90 segundos e sem repetição automática. Não concorre com
  a fila da conversa ou a parada prioritária. A verificação interna mantém limite de 60 s na geração.
- Reserva de 2048 tokens e esforço baixo no teste, em vez de 64 tokens para saída E raciocínio.
  Continua uma única geração. O teto autorizado é respeitado: um modelo mais caro pode exigir um
  teto de teste maior, que deve ser autorizado pelo usuário. Sem ajuste silencioso ou teste grátis fictício.
- Resposta incompleta, palavra errada ou consumo ausente não habilitam a inteligência. O consumo
  estimado do ledger não é confundido com consumo informado pelo provedor. Custos incertos persistem.
- Códigos estáveis em `IntelligenceStatus.reason` e no relatório de validação: falta de configuração,
  aceite, autenticação, permissão, modelo, saldo/cota, frequência, TLS, rede, prazo e formato.
  Interface e exportação traduzem apenas vocabulário fixo; não copiam erros livres ou chaves.
- Espaços externos da chave são normalizados; chave vazia ou com caracteres de cabeçalho inválidos
  é rejeitada antes de revogar a anterior. Credencial e resultado do teste ficam vinculados à mesma
  referência: troca durante a chamada não aprova a credencial nova.
- Erro de saldo/cota da API não dispara fallback para outro modelo. Nenhum redirecionamento de
  credencial, desativação de TLS ou mudança de endpoint foi adicionada.

## Evidência
Os números finais de CI e instalação devem ser registrados no PR; não inferir aprovação desta nota.
Testes dirigidos usam servidor HTTP local, SQLite e IPC reais, credenciais fictícias e resposta
controlada. Cobrem registro, estado sem inferência, precondições, truncamento, consumo faltante,
autenticação, quota, preservação de chave e validação seguida de conversa. Testes Swift exercitam
reutilização, ordem de operações, conflitos, consentimento, cliques simultâneos e diagnóstico.
O fixture dos testes de modos autoriza 20 centavos sintéticos porque a reserva Astra de 2048 tokens
não cabe nos 5 centavos anteriores. Há regressão separada que comprova bloqueio do teto insuficiente.

Antes do reparo, o runtime embutido foi compilado em macOS 15 e consultou o endpoint público de
modelos SEM credencial. TLS foi verificado, com 128 raízes e HTTP 401 esperado. Isso comprova somente
transporte nesse ambiente, não a chave do dono, a conexão no Mac dele ou uma inferência real.

## Referências oficiais verificadas em 29/09/2026
- https://developers.openai.com/api/docs/guides/reasoning
- https://developers.openai.com/api/docs/guides/error-codes
- https://developers.openai.com/api/docs/guides/structured-outputs

## Limites
Não resolve VM, navegador, contas/e-mail, skills bloqueadas, companion ou o resto da V1. Nenhuma
republicação de código anteriormente bloqueado foi feita. Distribuição permanece Alpha não notarizada.
A chave do usuário e o crédito do seu projeto não foram acessados nem homologados aqui.
