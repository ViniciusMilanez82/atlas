"""Fixed diagnostic vocabulary. Never copy provider messages or credentials to the UI/export."""
from __future__ import annotations

from typing import Any

# Values here are product-owned text, not interpolated provider responses.
MESSAGES: dict[str, str] = {
    "READY": "Conexão de IA validada para esta chave e este modelo.",
    "KEYCHAIN_UNAVAILABLE": "O cofre do Mac não está disponível. Reinicie os serviços do Atlas sem apagar os dados.",
    "CREDENTIAL_MISSING": "Nenhuma chave registrada foi encontrada no cofre do Atlas.",
    "SETTINGS_MISSING": "A chave está registrada. Falta salvar modelo, orçamento e consentimento de preços.",
    "BUDGET_MISSING": "Defina os limites mensal e por tarefa antes de autorizar chamadas pagas.",
    "PROVIDER_UNSUPPORTED": "Este pacote possui adaptador somente para a API da OpenAI.",
    "MODEL_UNPRICED": "O modelo escolhido não possui preço nesta versão. Selecione um modelo com preço cadastrado.",
    "PRICE_CONSENT_REQUIRED": "A chave está registrada. Revise e aceite a tabela como estimativa e salve a configuração.",
    "VALIDATION_REQUIRED": "A chave está registrada. Falta autorizar a validação em Salvar e conectar.",
    "API_AUTH_REJECTED": "A OpenAI rejeitou a autenticação (401). Confira a validade da chave no projeto da API.",
    "API_ACCESS_DENIED": "A OpenAI negou acesso (403). Confira as permissões do projeto/chave para Models e Responses; não é necessário liberar outras funções.",
    "MODEL_NOT_AVAILABLE": "A conta não disponibilizou o modelo escolhido. Revise o ID e o acesso desse projeto.",
    "API_QUOTA_EXHAUSTED": "A API informou saldo, cota ou limite de gastos esgotado. Confira o faturamento do projeto; repetir a chamada não resolve esse bloqueio.",
    "API_RATE_LIMIT": "A API limitou a frequência de chamadas. Aguarde antes de tentar novamente.",
    "TLS_ERROR": "Não foi possível verificar o certificado da conexão. Confira rede, data e certificados; não desative a verificação de segurança.",
    "NETWORK_ERROR": "Não foi possível conectar à API. Confira internet, DNS, proxy e firewall.",
    "API_TIMEOUT": "A API não respondeu dentro do prazo. Não há confirmação do resultado; confira os custos antes de repetir.",
    "API_UNAVAILABLE": "O serviço da API está indisponível ou não respondeu corretamente. Tente novamente mais tarde.",
    "API_REQUEST_INVALID": "A API rejeitou o formato da solicitação. É um problema de compatibilidade do aplicativo; a chave foi preservada.",
    "METADATA_INVALID": "A consulta do modelo devolveu dados inválidos. Nenhuma chamada de geração foi iniciada.",
    "OUTPUT_LIMIT_REACHED": "O teste atingiu o limite de saída antes de concluir. A chave foi preservada; este resultado não valida a conexão.",
    "OUTPUT_INVALID": "A API respondeu, mas não entregou o formato esperado pelo Atlas. A chave foi preservada.",
    "USAGE_MISSING": "A resposta não informou o consumo real. O Atlas não validou o teste com uma estimativa inventada.",
    "LOCAL_BUDGET_BLOCKED": "O orçamento local não comporta este teste. Revise o teto do teste e o limite mensal disponível.",
    "POLICY_REFUSAL": "O provedor recusou a solicitação. O Atlas não repetirá com outro modelo para contornar a recusa.",
    "CONFIG_CHANGED": "A chave mudou durante o teste. O resultado antigo não valida a nova credencial.",
    "CHECK_FAILED": "O teste não foi validado. A chave foi preservada; salve o diagnóstico para investigar.",
}
QUOTA_CODES = frozenset({"insufficient_quota", "credit_balance_exhausted", "organization_spend_limit_exceeded",
                         "project_spend_limit_exceeded", "organization_usage_limit_exceeded", "billing_hard_limit_reached"})
HTTP_CODES = QUOTA_CODES | frozenset({"invalid_api_key", "permission_denied", "model_not_found",
    "invalid_request_error", "rate_limit_error", "rate_limit_exceeded", "slow_down", "server_error",
    "service_unavailable_error", "server_is_overloaded", "invalid_json_schema", "unsupported_parameter",
    "invalid_value", "content_policy_violation", "redirect_refused"})


def safe_code(value: Any) -> str:
    return value if isinstance(value, str) and value in MESSAGES else "CHECK_FAILED"


def message(code: Any) -> str:
    return MESSAGES[safe_code(code)]


def exception_code(exc: Exception) -> str:
    """Select a fixed code; exception text is examined but never exported or persisted here."""
    text = str(exc)
    if any(code in text for code in QUOTA_CODES):
        return "API_QUOTA_EXHAUSTED"
    if "401" in text or "provider credential rejected" in text:
        return "API_AUTH_REJECTED"
    if "403" in text:
        return "API_ACCESS_DENIED"
    if "404" in text:
        return "MODEL_NOT_AVAILABLE"
    if "429" in text:
        return "API_RATE_LIMIT"
    if "SSLCertVerificationError" in text or "CERTIFICATE_VERIFY_FAILED" in text:
        return "TLS_ERROR"
    if "timed out" in text or "TimeoutError" in text:
        return "API_TIMEOUT"
    if "could not connect" in text or "transport error" in text:
        return "NETWORK_ERROR"
    if "POLICY_DENIED" in text:
        return "POLICY_REFUSAL"
    if any(code in text for code in ("HTTP 400", "HTTP 422", "HTTP 30")):
        return "API_REQUEST_INVALID"
    if "PROVIDER_UNAVAILABLE" in text or "HTTP 5" in text:
        return "API_UNAVAILABLE"
    return "CHECK_FAILED"
