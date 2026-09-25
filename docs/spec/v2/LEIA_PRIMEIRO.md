# Como entregar este pacote à IA programadora

**Este pacote é o contrato de implementação. Não é uma nova versão do aplicativo.**

## Para Vinícius

1. Envie o ZIP completo à IA que trabalha no repositório Atlas. Em uma ferramenta que acessa pastas, descompacte-o numa pasta de documentação do projeto.
2. Cole o conteúdo de `PROMPT_INICIAR_IMPLEMENTACAO.txt` na conversa. Peça que leia `ATLAS_CONTRATO_IMPLEMENTACAO_v2.md` integralmente, inclusive anexos.
3. A IA deve começar a trabalhar no código existente e devolver evidências por item; não apenas outro plano. Você não precisa escolher bibliotecas, escrever comandos ou entender a arquitetura para delegar esse trabalho.

A aprovação de compra, API, conta, publicação ou acesso pessoal continua separada. Nunca cole sua chave de API no prompt. Quando necessária, use o campo seguro ou mecanismo de segredo do ambiente autorizado.

## O que enviar

O arquivo principal em Markdown é o formato prioritário para a IA: contém todos os capítulos e anexos num só texto. O PDF é a versão de leitura. Não é necessário enviar os dois se a ferramenta já leu o Markdown completo.

- `ATLAS_CONTRATO_IMPLEMENTACAO_v2.md`: visão, arquitetura, implementação, gates e anexos obrigatórios.
- `ATLAS_CONTRATO_IMPLEMENTACAO_v2.pdf`: cópia de leitura do contrato, com sumário.
- `PROMPT_INICIAR_IMPLEMENTACAO.txt`: ordem para começar e conduzir a implementação.
- `BACKLOG_EXECUTAVEL.json` e `.md`: 56 itens, sendo 32 correções e 24 pacotes do produto.
- `CENARIOS_ACEITE.json`: 40 cenários de validação, também descritos no contrato.
- `AGENTS_ATLAS.md`: complemento proposto para as regras do agente; mesclar com instruções existentes, não sobrescrever cegamente.
- `referencias/`: Master Spec v1 e auditoria da Alpha 2, preservadas como histórico.
- `MANIFESTO.json` e `SHA256SUMS.txt`: inventário e integridade deste pacote documental.

## O que cobrar em cada entrega

Peça o ID do item, o que mudou, os arquivos, o commit, os testes executados, os resultados e o que não pôde ser validado. Não aceite “concluído” porque existe um botão ou porque um modelo falso respondeu conforme o teste. Não confunda “Alpha corrigida” com a V1 completa.

## Baseline e limites

Baseline consultada: `d81cece2713ccb5b12e58902e55b05a614467951`, Alpha 2, 24/09/2026. A IA deve conferir se houve novos commits antes de alterar. Este pacote não mudou o repositório e não executou um novo teste do Atlas no Mac nem chamadas pagas. Os achados originais mantêm suas limitações e precisam de revalidação no HEAD.
