# ATLAS — Modelo de ameaças

Base: spec capítulos 5, 10, 11, 12, 16. Estes controles reduzem risco; **não** constituem prova
de segurança absoluta. Antes de distribuição é obrigatória revisão técnica independente (spec 11.5).

## 1. Ativos

| Ativo | Onde vive | Sensibilidade |
| --- | --- | --- |
| Credenciais (API keys, OAuth, senhas de contas operacionais) | Keychain (macOS); banco guarda só `credential_ref` | SECRET |
| Sessões autenticadas de browser | Perfis isolados no guest | SECRET (permitem personificação) |
| Políticas, mandatos, aprovações, reservas, ledger | SQLite no host, escrita só pelo atlas-core | Autoridade |
| Memória, conversas, artefatos do proprietário | SQLite + armazenamento de artefatos no host | PERSONAL/SENSITIVE |
| Orçamento e meios de pagamento | Política + provedores externos | Financeiro |
| Chaves de assinatura de release | Pipeline de distribuição, nunca na instalação | Cadeia de suprimentos |

## 2. Fronteiras de confiança

1. **Proprietário autenticado ↔ App**: única origem de instruções com autoridade.
2. **App ↔ atlas-core** (IPC UDS): ator derivado do canal; payload validado por schema.
3. **atlas-core ↔ Runtime**: o Runtime é não confiável para autoridade; só propõe.
4. **Runtime ↔ provedores de modelo**: recebem contexto mínimo; saída é não confiável.
5. **Host ↔ VM**: guest não confiável; transferência só pelo Artifact Broker.
6. **VM ↔ Internet**: egress mediado fora do guest.
7. **Relay remoto**: não confiável para autoridade; aprovações sensíveis voltam à interface autenticada.

Todo conteúdo que cruza 3, 4, 5 ou 6 é **dado não confiável**, nunca instrução.

## 3. Ameaças da spec 11.5 e rastreabilidade de controles

| ID | Ameaça | Controle | Teste de bloqueio | Estado |
| --- | --- | --- | --- | --- |
| T-01 | Prompt injection | Proposta sem campos de autoridade (schema); política determinística; efeito vem do registro | `tests/contract/test_schemas.py::test_llm_proposal_cannot_carry_authority_fields`; `tests/security/test_prompt_injection.py` | OK (camada de autoridade; comportamento do modelo: M6/M10) |
| T-02 | Contaminação de memória | Fonte com confiança derivada do canal, estado `proposed`, confirmação só pelo proprietário | `tests/integration/test_memory.py::test_t02_external_text_never_becomes_confirmed_preference` | OK |
| T-03 | Vazamento por ferramenta | Dados mínimos, destino permitido, broker | `tests/security/test_broker.py` (destino fora do escopo) | OK (broker, destino e SECRET_DATA_EGRESS) |
| T-04 | Escape de workspace | VM, sem pastas pessoais, sem shell de host | M1: arquivo-sentinela no host | **NÃO EXECUTADO** (requer Mac) |
| T-05 | Código malicioso | Execution Box sem segredos e sem rede | M8 | **NÃO EXECUTADO** (requer VM) |
| T-06 | Replay de aprovação | Nonce, validade, hash canônico, consumo atômico | `tests/security/test_broker.py` (TestApprovalFlow, TestPurchases) | OK |
| T-07 | Worker obsoleto | Lease com fencing token verificado no broker | `tests/integration/test_task_engine.py`, `tests/security/test_broker.py` | OK |
| T-08 | Execução duplicada | Action Ledger, UNKNOWN, reconciliação | `tests/recovery/test_ledger_recovery.py` | OK |
| T-09 | Abuso de custo | Reservas por tarefa e período, teto obrigatório | `tests/unit/test_budget.py` | OK |
| T-10 | Atualização adulterada | Assinatura, manifesto, verificação | M16 | **NÃO EXECUTADO** (requer credenciais Apple) |
| T-11 | Canal remoto comprometido | Pareamento, escopo, revogação | M14 | Planejado |

## 4. Ameaças adicionais identificadas na implementação

| ID | Ameaça | Controle | Estado |
| --- | --- | --- | --- |
| T-12 | Banco ou backup copiado do disco revela dados | Backups: AES-256-GCM (`cryptography`), plaintext removido, adulteração detectada (`tests/recovery/test_backup_restore.py`). Banco em uso: pendente (D-09); até lá depende do FileVault. | PARCIAL |
| T-13 | Segredo vazado em log | Filtro de redação em todo logger; JournalEvent sem campos livres de payload | `tests/security/test_redaction.py` |
| T-14 | Runtime se autoeleva via settings | `settings.update` rejeita ampliação de segurança por schema (`const`) | `tests/contract/test_schemas.py::test_config_cannot_widen_security` |
| T-15 | Restauração de backup reativa autorizações antigas | Restore revoga aprovações APPROVED/RESERVED e mandatos | `tests/recovery/test_backup_restore.py` |
| T-16 | Mudança de dinheiro por arredondamento de float | Floats proibidos no JSON canônico e em dinheiro | `tests/unit/test_shared_primitives.py` |
| T-17 | Segredo commitado no repositório | `scripts/scan_secrets.py` no check e em teste | `tests/contract/test_repository_hygiene.py` |
| T-18 | Host de desenvolvimento Windows sem Keychain | Nenhum segredo real é usado; backend de produção do Vault é só o Keychain (macOS), via serviço Swift com socket 0600, UID do par e token | ADR-009; `test_keychain_backend_round_trip` (CI macOS) |

## 5. Regras invariantes (auditáveis em código)

- O LLM propõe; o broker valida e executa.
- DENY domina: proibição não é superada por mandato, aprovação ou pontuação.
- Falha, exceção ou dado incompleto na Policy Engine resulta em DENY.
- Aprovação vincula o hash canônico dos parâmetros; mudança material exige nova aprovação.
- Nenhuma ação sai de DISPATCHING para "tentar de novo" sem reconciliação quando o resultado é UNKNOWN.
- Cancelamento impede novos despachos e não apaga efeitos já ocorridos.
- Sem teto configurado, chamadas pagas ficam bloqueadas (`null` não é ilimitado).
