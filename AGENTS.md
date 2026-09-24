# Regras para agentes de programação do Atlas

Fonte: `docs/spec/v2/AGENTS_ATLAS.md` (contrato v2.0), adotado pela ADR-015. Não substitui o contrato
integral `docs/spec/v2/ATLAS_CONTRATO_IMPLEMENTACAO_v2.md`, que prevalece em qualquer conflito.

## Missão
Continuar o funcionário digital generalista para Mac, sem refazer o projeto nem convertê-lo em chatbot
ou automação de domínio único. O funcionário usa identidade, memória, contas e ambiente próprios e não
herda contas pessoais. Corrigir a Alpha e completar a V1 são entregas diferentes.

## Fonte de verdade
Contrato v2 e anexos, `BACKLOG_EXECUTAVEL.json`, cenários T01–T40, `docs/MASTER_SPEC.md`/ADRs e o
código real. Revalidar HEAD e alterações locais antes de mudar algo. Segurança e autorização
prevalecem sobre conveniência.

## Antes de alterar
Diagnosticar o ambiente, rodar `python scripts/check.py`, escolher o item A3/N, localizar os caminhos
reais e escrever o teste da propriedade. Trabalhar em branch; preservar alterações; nunca force-push,
reset destrutivo ou apagar histórico. ADR para mudança de fronteira ou arquitetura material.

## Implementação
Uma mudança revisável por vez. Validação completa nas fronteiras; autoridade fora do LLM; parada
prioritária; revisões vigentes; idempotência e recuperação de pedidos; outbox transacional;
classificação e proveniência preservadas; workspace/código isolados; segredos escopados. Não simular
capacidades de produção. Não editar migrações já aplicadas: criar nova migração.

## Testes e limites
Mocks para controle determinístico são legítimos; mock não prova fornecedor, Mac, VM ou voz reais.
Não remover asserts nem usar skip/xfail/continue-on-error para tornar gate crítico verde. Credenciais,
gastos, termos e publicação dependem de autorização. Falta de recurso bloqueia só o teste dependente.

## Pronto por item
Commit, arquivos, regressão (`tests/regression/test_a3_NN.py`), teste integrado pertinente, comando e
saída, ambiente, limitações e rastreabilidade (`docs/AUDIT_REMEDIATION.md`, `docs/PROGRESS.md`)
atualizados. Não declarar teste executado sem executá-lo.
