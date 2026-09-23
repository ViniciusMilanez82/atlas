# packaging/

`macos/build_app.sh` monta um **Atlas.app de desenvolvimento** (Apple Silicon) com Python embutido (hash fixado),
núcleo e serviço de Keychain. Assinatura ad-hoc apenas: **não** é Developer ID nem notarizado (M16, D-07).
O CI macOS monta o pacote, verifica que ele inicia sem Python do sistema e publica `Atlas-dev.zip` como artefato.
