# ADR-014 — App de desenvolvimento com Python embutido

**Referência:** spec 3.1 (UX-001), 4.1, 5.1, 16.4; revisão 21422f3 (Etapas 4-5)  
**Status:** Aceita
**Data:** 2026-09-23

## Contexto
O proprietário não deve instalar Python, bibliotecas nem usar terminal. O núcleo é Python (ADR-001/012).

## Decisão
O Atlas.app de desenvolvimento embute um CPython 3.12.14 do projeto python-build-standalone. O hash
SHA-256 fica fixado no script e confere com o checksum publicado pelo projeto. O pacote também traz as
fontes do núcleo e as dependências fixadas (`packaging/macos/runtime-requirements.lock`, instaladas com
`--no-deps` e só a partir de wheels). O Supervisor (Swift) inicia o serviço de Keychain e o atlas-core
como processos separados. O CI monta o pacote e o executa sem Python do sistema no PATH.

## Consequências
- O pacote é assinado apenas ad-hoc: não usa Developer ID e **não é notarizado** (M16, D-07). O
  Gatekeeper pede confirmação na primeira abertura, e o pacote não é distribuível a terceiros.
- Sair do app encerra os serviços. Continuar trabalhando depois de sair exige item de login
  (SMAppService), a validar num Mac real (D-01).
- Só Apple Silicon (aarch64). Mac Intel fica fora da garantia inicial (spec 4.1).
