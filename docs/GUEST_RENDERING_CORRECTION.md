# Retomada do PR #10 — renderização no componente Linux

Base inspecionada: 12ef90af750becfdfcc3eb0c953d205a0ce3e8f4. O CI geral passou, mas o teste
específico 36481551036 falhou. O log real registra nove verificações de ExecutionBox concluídas,
seguido de falhas EGL/ANGLE/Vulkan e `GPU process isn't usable` durante Page.captureScreenshot.
O Linux desse componente não tem GPU: a correção configura compositor CPU e desativa o fallback
WebGL/SwiftShader. Não remove o sandbox, não muda usuário, NIC, permissões ou mediação de rede.

Regressão de configuração acrescentada. A correção só pode ser declarada funcional depois de
uma nova execução do boot real exigir renderização, screenshot e clique, além dos testes negativos.
A imagem de teste permanece separada da imagem componente; não diminuir os critérios para publicá-la.

Referência primária: Chromium, docs/gpu/using-gpu-hardware-in-headless-chrome.md e mudança
https://chromium.googlesource.com/chromium/src/+/d99a9664c873fc38e226e33bc92da974fb852da3
sobre os switches de desativação de WebGL em headless. Teste no Chromium efetivamente empacotado
continua sendo a evidência decisiva, não somente esta referência.

A restrição registrada em WORKSPACE_COMPONENT_STATUS.md quanto à publicação da integração nativa
Mac/VM não foi contornada. Esta correção é restrita ao launcher Linux já publicado. Não há novo
instalador Mac com VM, nem conclusão da V1.
