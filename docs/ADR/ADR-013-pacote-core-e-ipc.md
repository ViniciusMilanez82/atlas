# ADR-013 — Pacote `core/` e API IPC autenticada

**Referência:** spec 13.4, 13.5; ADR-012; revisão 21422f3 (Etapa 3)  
**Status:** Aceita
**Data:** 2026-09-23

## Contexto
O processo atlas-core (ADR-012) precisa de um ponto de entrada: servidor IPC, sessões e o mapeamento
dos métodos obrigatórios para o núcleo. A árvore da spec não tem pasta para isso.

## Decisão
Criar o pacote `core/` (servidor e handlers do atlas-core). O transporte é JSON-RPC 2.0 com
prefixo de tamanho de 4 bytes e limite de 1 MiB. A primeira mensagem de cada conexão é um
handshake com token de sessão emitido pelo Supervisor; o ator vem da sessão, nunca do corpo.
Em macOS o socket é Unix Domain Socket em diretório privado 0700, com verificação de UID do
par quando o sistema oferece. Em Windows (host de desenvolvimento) os testes usam `socketpair`.
O contrato de erros ganha `INTERNAL_ERROR` para falhas inesperadas, sem expor detalhes.

## Consequências
Métodos cujo componente ainda não existe (workspace, importação por upload) respondem com erro
explícito, nunca com sucesso simulado. A autenticação de processo pelo Supervisor (assinatura de
código, launchd) é validada em M4 (D-01).
