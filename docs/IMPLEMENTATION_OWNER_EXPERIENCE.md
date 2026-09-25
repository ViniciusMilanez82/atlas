# Implementação direta — experiência do proprietário, N20/N22

Base local: snapshot GitHub `462df21ff283ec5a35fe0385c821900ac645ad96`, contendo PR7 sobre a main pós-PR6.
Esta entrega é uma fatia integrada do contrato v2; não declara a V1 concluída nem muda os gates G4–G10.

## Implementado

- Perfil persistente: nome do funcionário e proprietário, idioma de conversa, fuso IANA e progresso de apresentação.
- `setup.get/update` e `privacy.get/update` autenticam o proprietário local e o vínculo proprietário/funcionário.
- Mutação + recibo idempotente + revisão otimista na mesma transação; reenvio com conteúdo diferente é conflito.
- Consentimento explícito por finalidade de inferência e configuração de pesquisa mediada. Não altera orçamento/segredos.
- Salvar modelos/orçamento preserva as seções não editadas (privacidade/pesquisa). Formulário obsoleto não sobrescreve consentimento novo.
- Nome, idioma e data local entram como dados de identidade no contexto comum de conversa/tarefa. Não conferem autoridade e levam classificação PERSONAL.
- Primeiros passos, identidade, privacidade e botões para início do app ao login usando SMAppService. Início ao login NÃO é helper independente da UI; essa distinção é exibida.
- Voz nativa: captura explícita, exige reconhecimento on-device suportado, limite de 60 segundos, transcrição revisável e reprodução com voz sintetizada do sistema. Sem fallback de áudio para nuvem, sem persistir gravações.
- Transcrição nunca cria tarefa nem aprovação. "Usar no rascunho" permite revisar e enviar pela conversa existente. Parar reprodução não cancela tarefas.
- Sessões de captura descartam retornos atrasados; sair da tela, cancelar, suspender o Mac ou encerrar o app libera o microfone.
- Info.plist inclui as descrições de permissão necessárias; nenhuma permissão é solicitada na inicialização apenas para mostrar a interface.

## Testes

Local: Linux, Python 3.13.5, bibliotecas disponíveis no ambiente (não o conjunto exato do lock).

- `python -m pytest -q tests/integration/test_product_setup.py`: 16 aprovados, com IPC real e SQLite.
- Conjunto com regressões de privacidade, memória e contexto: 39 aprovados.
- `python -m compileall -q core runtime`: passou.
- Novos testes Swift: revisão da fala, negação de permissão, cancelamento durante autorização, resultado tardio, parada de playback e limite de captura; preservação de privacidade ao salvar modelos. Dependem do CI macOS para compilar/executar.

A baseline anterior às alterações executou 751 aprovados, 4 ignorados e 2 falhas locais: SBOM recusou versões diferentes do lock; teste de subprocesso com prazo curto não alcançou o marcador de efeito neste ambiente. Ruff e mypy não estavam instalados localmente. Nenhum desses resultados foi renomeado como sucesso; o CI com dependências fixadas é exigido antes de integrar.

## Limites

Não houve áudio capturado, interação humana no Mac, chamada paga, credencial real ou dado pessoal. Teste com SpeechDriver falso prova orquestração, não qualidade do reconhecimento de voz. O reconhecimento nativo pode estar indisponível para um idioma/hardware, caso em que a UI explica e mantém texto. A proteção de volume/banco e o serviço independente não são implementados por essa fatia. Browser/VM, relay/companion, e-mail, skills, assinatura/notarização mantêm seus gates próprios.

## Fontes primárias usadas na implementação

- Apple Speech: `supportsOnDeviceRecognition` e `requiresOnDeviceRecognition`; o segundo só é honrado quando o primeiro é verdadeiro.
- Apple AVFoundation: `AVCaptureDevice.requestAccess`, `AVAudioEngine`, `AVSpeechSynthesizer`.
- Apple ServiceManagement: `SMAppService.mainApp`, register/unregister e estados de consentimento.

A adoção de APIs do sistema evita novos custos de API de áudio. Isso não é uma medição da qualidade de voz em hardware real nem uma promessa de disponibilidade em todo Mac.
