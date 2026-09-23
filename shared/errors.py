"""Normalized error codes (spec 13.5).

Every error states whether it may be retried, what was persisted, and the recommended action.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_UNSUPPORTED = "MODEL_UNSUPPORTED"
    WORKSPACE_OFFLINE = "WORKSPACE_OFFLINE"
    EXTERNAL_EFFECT_UNKNOWN = "EXTERNAL_EFFECT_UNKNOWN"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"  # unexpected failure; details stay in local diagnostics


# JSON-RPC server error range (-32000..-32099) mapping.
JSONRPC_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: -32602,
    ErrorCode.UNAUTHORIZED: -32001,
    ErrorCode.POLICY_DENIED: -32002,
    ErrorCode.APPROVAL_REQUIRED: -32003,
    ErrorCode.BUDGET_EXCEEDED: -32004,
    ErrorCode.PROVIDER_UNAVAILABLE: -32005,
    ErrorCode.MODEL_UNSUPPORTED: -32006,
    ErrorCode.WORKSPACE_OFFLINE: -32007,
    ErrorCode.EXTERNAL_EFFECT_UNKNOWN: -32008,
    ErrorCode.VERSION_CONFLICT: -32009,
    ErrorCode.RATE_LIMITED: -32010,
    ErrorCode.INTERNAL_ERROR: -32603,
}

DEFAULT_RETRYABLE: dict[ErrorCode, bool] = {
    ErrorCode.INVALID_INPUT: False,
    ErrorCode.UNAUTHORIZED: False,
    ErrorCode.POLICY_DENIED: False,
    ErrorCode.APPROVAL_REQUIRED: False,
    ErrorCode.BUDGET_EXCEEDED: False,
    ErrorCode.PROVIDER_UNAVAILABLE: True,
    ErrorCode.MODEL_UNSUPPORTED: False,
    ErrorCode.WORKSPACE_OFFLINE: True,
    # Never blindly retried: requires reconciliation first (spec 12.2).
    ErrorCode.EXTERNAL_EFFECT_UNKNOWN: False,
    ErrorCode.VERSION_CONFLICT: True,
    ErrorCode.RATE_LIMITED: True,
    ErrorCode.INTERNAL_ERROR: False,
}


class AtlasError(Exception):
    """Normalized error. Mutable on purpose: exceptions get ``__traceback__`` assigned when
    re-raised through context managers."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        persisted: str = "nothing",
        recommended_action: str = "",
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.persisted = persisted
        self.recommended_action = recommended_action
        self.retryable = DEFAULT_RETRYABLE[code] if retryable is None else retryable

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_jsonrpc(self, correlation_id: str | None) -> dict[str, object]:
        return {
            "code": JSONRPC_CODE[self.code],
            "message": self.message,
            "data": {
                "atlas_code": str(self.code),
                "retryable": bool(self.retryable),
                "persisted": self.persisted,
                "recommended_action": self.recommended_action,
                "correlation_id": correlation_id,
            },
        }
