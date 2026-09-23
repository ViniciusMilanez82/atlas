# ATLAS — Funcionário Digital

Aplicativo macOS de um funcionário digital persistente, com identidade, memória, contas e
ambiente de trabalho próprios. O usuário conversa e delega objetivos; o Atlas planeja, executa
dentro das autorizações, verifica e entrega.

**Estado:** em desenvolvimento, fase de fundação. **Não é um produto utilizável ainda.**
Nenhum gate (READY FOR BETA, READY FOR RELEASE) foi atingido. Veja [docs/PROGRESS.md](docs/PROGRESS.md).

| Documento | Para quê |
| --- | --- |
| [docs/MASTER_SPEC.md](docs/MASTER_SPEC.md) | Especificação v1.0, preservada byte a byte (contrato do produto) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Como a spec está sendo realizada e o mapa do repositório |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | Ativos, fronteiras, ameaças e controles |
| [docs/REQUIREMENTS_TRACEABILITY.md](docs/REQUIREMENTS_TRACEABILITY.md) | Requisito → implementação → teste |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Tarefas pequenas em ordem de dependência |
| [docs/EXTERNAL_DEPENDENCIES.md](docs/EXTERNAL_DEPENDENCIES.md) | O que depende do proprietário (Mac, contas, credenciais) |
| [docs/BUILD_AND_RUN.md](docs/BUILD_AND_RUN.md) | Preparar ambiente e rodar a verificação |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Parada, recuperação, backup |
| [docs/ADR/](docs/ADR/) | Decisões arquiteturais |

Verificação rápida:

```bash
<venv-python> scripts/check.py
```
