# Regras de trabalho para agentes de programação do Atlas

Este arquivo é um complemento proposto para as instruções do repositório. Antes de adotar, ler o AGENTS.md existente e mesclar sem apagar regras legítimas. Não substitui o contrato integral v2.0.

## Missão
Continuar o funcionário digital generalista para Mac, sem refazer o projeto nem convertê-lo em chatbot ou automação de domínio único. O funcionário usa identidade, memória, contas e ambiente próprios. Não herda contas pessoais. Corrigir Alpha e completar V1 são entregas diferentes.

## Ordem e fonte de verdade
Ler ATLAS_CONTRATO_IMPLEMENTACAO_v2.md e anexos, backlog JSON, cenários T01–T40, Master Spec/ADRs preservados e código real. Revalidar HEAD e alterações locais. O contrato detalhado prevalece sobre resumos; segurança e autorização prevalecem sobre conveniência.

## Antes de alterar
Diagnosticar ambiente, executar baseline disponível, escolher item A3/N, localizar caminhos reais e escrever teste da propriedade. Usar branch; preservar alterações; não force-push/reset/apagar histórico. Registrar ADR para mudança de fronteira ou arquitetura material.

## Implementação
Uma mudança revisável por vez. Validação completa nas fronteiras; autoridade fora do LLM; parada prioritária; revisões vigentes; idempotência e recuperação de pedidos; outbox transacional; classificação e proveniência preservadas; workspace/código isolados; segredos escopados. Não simular capacidades de produção.

## Testes e limites
Mocks para controle determinístico são legítimos. Mock não prova fornecedor, Mac, VM ou voz reais. Não remover asserts, usar skip/xfail ou continue-on-error para transformar gate crítico em sucesso. Credenciais, gastos, termos e publicação dependem de autorização apropriada. Falta de recurso bloqueia somente o teste dependente.

## Definição de pronto por item
Commit, arquivos, regressão, teste integrado pertinente, comando e saída, ambiente, limitações e rastreabilidade atualizados. Não declarar teste executado sem executá-lo. No fim da sessão, atualizar PROGRESS com próximo item concreto, sem prometer trabalho assíncrono não suportado.

## V1
Exige memória duradoura comum, documentos compreendidos, conversa/objetivos, autonomia controlada, workspace/browser reais, contas operacionais, voz, companion, skills, recuperação e instalação leiga. O aceite tem T01–T40 e revisão humana. Um instalador ou número de testes não substitui isso.
