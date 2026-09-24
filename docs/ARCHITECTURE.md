# ATLAS — Arquitetura

Referência normativa: [MASTER_SPEC.md](MASTER_SPEC.md) (cópia byte a byte da Especificação v1.0).
Este documento descreve **como** a spec está sendo realizada no repositório e o que já existe.
Decisões estão em [ADR/](ADR/).

## 1. Visão de processos (alvo)

```text
 Atlas App (SwiftUI)          Web companion (TS)        [M4, M14 — não iniciados]
        |  IPC UDS + JSON-RPC            | relay (só fila, ADR-007)
        v                                v
 Supervisor (Swift) --- ciclo de vida, saúde, SMAppService      [M1/M4 — requer Mac]
        |
        +--> atlas-core (Python)  ← ÚNICO escritor do SQLite (ADR-012)
        |      storage/   banco, migrações, backup/restore
        |      security/  policy, approvals, vault(refs), budget, broker, ledger
        |      runtime/tasks  máquina de estados, leases, fencing, cancelamento
        |
        +--> atlas-runtime (Python) — LLM, ContextBuilder, Planner, Verifier   [M6+]
        |      fala com atlas-core só por IPC; não lê segredos nem escreve autoridade
        |
        +--> Workspace Host (Swift, Virtualization.framework)                  [M1]
               VM Linux ARM64: Guest Agent, Playwright fixado, Execution Box
```

Rede do guest mediada **fora** da VM (spec 5.3). Não há shell no host, nem fallback
para o navegador pessoal (spec 5.2, 5.4).

## 2. Mapa do repositório

| Pasta | Conteúdo | Estado |
| --- | --- | --- |
| `shared/schemas` | Contratos JSON Schema 2020-12 (ADR-011) | Implementado (M0) |
| `shared/fixtures/valid` | Fixtures sintéticas, uma por contrato | Implementado (M0) |
| `shared/*.py` | contratos, JSON canônico, dinheiro, relógio, IDs, erros, config | Implementado (M0) |
| `storage/` | SQLite, migrações, journal, backup/restore | Implementado (M2) |
| `security/policy` | Policy Engine R0–R5 | Implementado (M3) |
| `security/approvals` | Aprovações e mandatos | Implementado (M3) |
| `security/vault` | Referências de credencial | Implementado; backend Keychain requer Mac |
| `security/broker` | Broker de despacho, Action Ledger, reconciliação | Implementado (M3/M12 parcial) |
| `security/budget` | Reservas e tetos de orçamento | Implementado (parte de M6) |
| `runtime/tasks` | Estados, leases, fencing, pausa, parada, recuperação | Implementado (M5 núcleo) |
| `runtime/tools/registry.py` | Tool Registry confiável | Implementado (M3) |
| `runtime/tasks/limits.py`, `scheduler.py` | Limites de tentativa, backoff, circuit breaker, jobs com fuso | Implementado (M5) |
| `runtime/memory/manager.py` | Memória com proveniência, correção, exclusão, FTS5 reconstruível | Implementado (M7, sem índice semântico) |
| `runtime/models/` | Contratos de modelo, preços, roteador, cliente com orçamento, ContextBuilder | Implementado sem adaptador real (D-03) |
| `runtime/{agent,verification}` | Laço do agente (catálogo de manifestos, validação antes do broker, retomada), verificador objetivo | Implementado com modelo falso; modelo real: D-03 |
| `core/` | Daemon atlas-core, IPC autenticado, serviço, conversa (`conversation.py`), inteligência | Implementado |
| `platform/macos/AtlasKit` | Framing, `IPCClient` com prazo e correlação, `AtlasConnection` (assíncrona, reconexão), `AtlasViewModel`, Supervisor, Keychain, app SwiftUI | Compilado e testado no CI macOS 15; interação: D-01 |
| `platform/{workspace,execution}` | VM, Execution Box | Requer Mac com virtualização, não iniciado |
| `apps/companion-web` | Interface remota | Não iniciado |
| `config/atlas.default.yaml` | Configuração de referência (spec 7.5) | Implementado, validado |
| `scripts/` | `check.py`, `scan_secrets.py` | Implementado |
| `tests/` | unit, contract, integration, security, recovery | Em uso |

## 3. Fluxo de uma ação externa (contrato do broker)

1. Runtime envia `ActionProposal` (schema fechado: sem efeito, risco, hash ou credencial).
2. Broker valida o schema e resolve a ferramenta no **registro confiável** (versão e classe de efeito).
3. Broker verifica o **lease e o fencing token** da tarefa (worker obsoleto é recusado).
4. Policy Engine decide ALLOW, ASK ou DENY (proibições primeiro; falha resulta em DENY).
5. ASK exige aprovação válida: hash canônico idêntico, dentro da validade, com usos restantes.
6. Orçamento: reserva do custo máximo plausível; sem teto configurado, chamadas pagas ficam bloqueadas.
7. **Na mesma transação**: ledger PROPOSED→AUTHORIZED→DISPATCHING, aprovação RESERVED, reserva criada.
8. Adaptador executa. O resultado vira CONFIRMED (com recibo), FAILED (comprovado) ou UNKNOWN.
9. UNKNOWN bloqueia a tarefa (`EXTERNAL_EFFECT_UNKNOWN`) até reconciliação. Não há repetição cega.

## 4. Dados

Um arquivo SQLite (WAL, `foreign_keys=ON`, migrações versionadas em `storage/migrations`).
Instantes em UTC com sufixo `Z`; fuso IANA guardado quando relevante. Dinheiro em inteiros de
unidade mínima com moeda. Artefatos referenciados por `artifact_id` + SHA-256.
Criptografia em repouso: **pendente M2** (THREAT_MODEL, ameaça T-12). A escolha exige
implementação auditada compatível com FTS5 e empacotamento validado em Mac.

## 5. Inteligência (M6: contratos prontos, adaptador real pendente de D-03)

`ModelProvider` (capabilities, generate, stream, cancel, estimate_usage, health), `ModelRouter`
(filtra por capacidade, privacidade, disponibilidade e orçamento; nunca muda de fornecedor sem
consentimento), `ContextBuilder` (ordem de autoridade da spec 6.3; conteúdo externo sempre
marcado como não confiável). Catálogo inicial da spec (gpt-6-sol/astra/luna, claude-opus-5-5)
permanece **não validado** até o teste "Testar inteligência" autorizado pelo proprietário.

## 6. O que não existe (e não deve existir)

- Shell livre no host, ferramenta genérica `read_secret`, fallback para o browser pessoal.
- Mock de workspace em build de produção (fakes só em `tests/fakes`).
- Marcos declarados concluídos com stub, TODO ou resposta fixa.
