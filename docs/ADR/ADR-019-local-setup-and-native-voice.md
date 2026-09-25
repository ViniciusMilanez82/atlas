# ADR-019 — Configuração inicial e voz nativa sem envio automático

Data: 2026-09-25. Contrato v2: N20 e parte de N22. Estado: implementação parcial, sujeita a validação interativa.

## Decisão

Adicionar primeira utilização persistente, identidade editável e painel de consentimento. O usuário escolhe nome, idioma e fuso sem criar outro funcionário. O orçamento continua no serviço existente; salvar orçamento não reconstrói nem apaga o restante das configurações. Concluir o onboarding não concede novos poderes e não declara V1 pronta.

Voz inicial usa Speech/AVFoundation do macOS, apenas mediante ação do usuário. O reconhecimento exige `supportsOnDeviceRecognition` e `requiresOnDeviceRecognition=true`. Sem suporte ao idioma local, o ditado fica indisponível, não troca silenciosamente por um serviço remoto. Não há wake word, áudio armazenado ou autorização automática por fala. O resultado é um rascunho editável; o proprietário o coloca no compositor e envia pelo mesmo protocolo do chat. Síntese usa a voz instalada do sistema e botão explícito “Ouvir resposta”. “Parar fala” não é “Pare tudo”.

## Autoridade e privacidade

`identity.update` e `setup.complete` requerem o dono autenticado no aplicativo local. Revisões impedem sobrescrita concorrente. O nome é dado citado, nunca texto de sistema. Os idiomas suportados nesta interface são pt-BR/en-US/es-ES; os fusos são validados pela base IANA.

O painel de privacidade edita consentimentos já suportados no Egress Guard, por provedor OpenAI e finalidade (conversa/tarefa). Ele informa que permissões valem até revogação, não são consentimento específico de uma única tarefa, não autorizam compras e não recuperam informação já enviada. Revogação afeta novas saídas. As restrições de domínio e dados dos demais provedores permanecem intactas.

## Limites

Dictation/synthesis nativos não são conversa de voz em tempo real validada. Disponibilidade de ditado offline depende do Mac, versão do sistema, idioma e modelos locais instalados. Compilar ou testar com doubles não comprova microfone/voz em hardware. O assistente de configuração não cifra o banco nem implementa serviço de login, navegador ou companion. Esses requisitos continuam pendentes.

## Referências primárias

- Apple: SFSpeechRecognizer.supportsOnDeviceRecognition — https://developer.apple.com/documentation/speech/sfspeechrecognizer/supportsondevicerecognition
- Apple: SFSpeechRecognitionRequest.requiresOnDeviceRecognition — https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition
- Apple: AVSpeechSynthesizer — https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer

Não há contratação, chave, dado real ou chamada paga neste incremento.
