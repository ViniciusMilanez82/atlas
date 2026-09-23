# ADR-009 — Host de desenvolvimento atual é Windows

**Referência:** spec 1.1, 18, 24  
**Status:** Aceita (temporária, até existir Mac de desenvolvimento)
**Data:** 2026-09-23

## Contexto
O diagnóstico de 2026-09-23 encontrou Windows 11 x86_64, Python 3.14.2, SQLite 3.50.4 com FTS5, Git, Node 22, Docker e WSL2. Não há Swift, Xcode, Virtualization.framework nem Keychain. A spec pressupõe um ambiente macOS.

## Alternativas consideradas
1. Parar tudo até haver Mac. 2. Simular macOS com mocks e declarar marcos concluídos (proibido pela spec). 3. Implementar agora o núcleo independente de plataforma e marcar o resto como NÃO EXECUTADO.

## Decisão
Alternativa 3. O núcleo Python (contratos, armazenamento, autoridade, tarefas, orçamento, ledger) é desenvolvido e testado aqui. Tudo que depende de macOS fica NÃO EXECUTADO, com a dependência exata registrada em EXTERNAL_DEPENDENCIES.md. Docker e WSL não substituem a VM do produto e não são usados como fronteira.

## Consequências
Nenhum marco que exija Mac (M1, M4, M13, M16, M17) pode ser declarado concluído. O código Python precisa rodar em macOS depois, então o caminho de produção evita APIs específicas de Windows.
