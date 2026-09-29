# N23 — Instalador nativo da Alpha

## Escopo exato

Entrega PKG nativo e DMG que contém `Instalar Atlas.pkg` e um guia pt-BR offline. Instala o aplicativo
atual em `/Applications/Atlas.app`, sem Python/Docker/Terminal para o usuário. Não implementa a V1
completa. Continua sem Developer ID e sem notarização. Não publicar como uma versão estável.

Requisitos iguais aos do bundle existente: Apple Silicon, macOS >= 15.0. O pacote declarativo rejeita
arquitetura e sistema incompatíveis, exige encerrar o aplicativo e não pede reinicialização.
Não contém scripts de pré/pós-instalação. Nenhuma conta, chamada de IA ou serviço privilegiado é
criado. O instalador não abre o Atlas como root, não remove quarentena, não altera Gatekeeper,
firewall, acesso a arquivos, microfone ou conta pessoal. O sistema pode pedir autenticação de um
administrador somente para instalar na pasta Aplicativos.

## Integridade e preservação

Antes do empacotamento: validar identidade, runtime presente, arquitetura de cada executável e
assinatura existente; rejeitar symlinks externos/quebrados. Payload restrito a Atlas.app, não relocável
para outra cópia encontrada no computador. O componente usa upgrade apenas dentro do bundle.
O banco, memórias, arquivos e Keychain do usuário não são payloads nem alvos de remoção.

O pacote tem versão numérica `0.1.<número da execução>`. Os bundles Alpha anteriores usavam hashes
Git em CFBundleVersion, por isso a comparação de versão de bundle legado não é usada para decidir
reinstalação. Isso NÃO é um atualizador seguro com proteção de downgrade; essa parte permanece em N23.
Não orientar reversão de versões sobre bancos mais recentes. Preservar backups.

## Verificação

`tests/regression/test_installer_contract.py`: contratos puros; 16 casos cobrem metadados, requisitos,
identidade errada, symlinks, manifesto, pacote sem scripts e transparência do guia. Testes sintéticos
não comprovam instalação no Mac.

`.github/workflows/macos-installer.yml`: runner macOS descartável compila o app, gera PKG/DMG,
monta DMG somente leitura, compara hashes/payload, instala o PKG real, abre o app instalado, encerra,
reinstala, confirma preservação byte a byte dos dados sintéticos e executa Supervisor/Keychain/IPC
usando o Python embutido. A avaliação Gatekeeper é somente leitura; sua rejeição é registrada, não
contornada. Os instaladores só são publicados como artefato depois do teste de instalação passar.

Capturas, quando disponíveis, são da janela real no runner. Não equivalem à validação humana,
notarização, teste do microfone, avaliação de LLM real ou comprovação da V1.

## Dependências que não podem ser substituídas por um ZIP/PKG

Developer ID Application/Installer e notarização precisam de credenciais oficiais controladas pelo
proprietário. Não solicitar essas chaves em texto no chat nem colocar segredos no repositório.
VM/Execution Box/browser/contas/companion/skills, cifra em repouso e demais faltas do contrato não
estão resolvidas pelo instalador. O usuário vê esse aviso no início, nas instruções e na conclusão.

## Fontes técnicas consultadas

- Apple — Packaging Mac software for distribution:
  https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution
- Apple — Distribution Definition XML (allowed-os-versions, must-close, domains):
  https://developer.apple.com/library/archive/documentation/DeveloperTools/Reference/DistributionDefinitionRef/Chapters/Distribution_XML_Ref.html
- Apple — Abrir apps com segurança no Mac:
  https://support.apple.com/pt-br/102445
