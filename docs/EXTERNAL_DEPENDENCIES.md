# ATLAS — Dependências externas

Lista objetiva do que depende do proprietário ou de terceiros (spec 22.3). O trabalho continua
em tudo que não está bloqueado.

| # | Dependência | Quem provê | Bloqueia | Estado |
| --- | --- | --- | --- | --- |
| D-01 | **Mac Apple Silicon de desenvolvimento** com macOS 15+, 16 GB (32 GB preferível), Xcode instalado, acesso remoto ou local para a IA | Proprietário | M1, M4, M13, M16, M17; AT-003, AT-004, AT-009; Vault de produção (Keychain) | **Pendente** — host atual é Windows x86_64 |
| D-02 | Modelo exato do Mac de testes e versão do macOS | Proprietário | Matriz de suporte, metas de memória (spec 4.1) | Pendente |
| D-03 | Conta de API OpenAI com orçamento autorizado (teto mensal e por tarefa, em moeda definida) | Proprietário | M6 (chamada real), validação dos IDs gpt-6-sol/astra/luna | Pendente |
| D-04 | Consentimento e conta Anthropic, se o segundo provedor for desejado | Proprietário | Adaptador Anthropic, fallback entre provedores | Opcional, pendente |
| D-05 | Conta de e-mail operacional dedicada ao Atlas (sob controle do proprietário) | Proprietário | Canal de entrega por e-mail (M14) | Pendente |
| D-06 | Infraestrutura para o relay do web companion (domínio, hospedagem) | Proprietário | M14 | Pendente |
| D-07 | Apple Developer Program: certificado Developer ID e credenciais de notarização | Proprietário | M16 (assinatura, notarização, instalador) | Pendente |
| D-08 | Imagem base Linux ARM64 e sua licença de redistribuição | Decisão técnica em M1 | M1 | Pendente (decidida pela IA no Mac) |
| D-09 | Biblioteca de criptografia do SQLite compatível com FTS5 (ex.: SQLCipher) e licença | Decisão técnica em M2, validada em Mac | T-12 | Pendente |
| D-10 | Repositório remoto (GitHub ou outro) para CI | Proprietário | Execução do CI | Resolvido em 2026-09-23: repositório privado ViniciusMilanez82/atlas, autorizado pelo proprietário |
| D-11 | Provedor de voz (transcrição e síntese em pt-BR) e seu custo | Proprietário + validação em M13 | M13 | Pendente |
| D-12 | API oficial do WhatsApp (elegibilidade, número, custos) | Proprietário | Pós-V1 | Fora da V1 |

Nenhuma credencial real foi solicitada ou usada até aqui. Testes usam somente dados sintéticos.
