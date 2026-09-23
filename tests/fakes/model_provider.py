"""FAKE model provider for deterministic tests. Never used in production; performs no network I/O."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from runtime.models.types import (
    FinishReason,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorKind,
    Usage,
)


@dataclass
class FakeModelProvider:
    provider_id: str
    caps: ModelCapabilities = field(
        default_factory=lambda: ModelCapabilities(
            structured_output=True,
            tool_calls=True,
            streaming=True,
            effort_levels=("low",),
            context_window_tokens=100_000,
            max_output_tokens=4_000,
        )
    )
    script: list[str] = field(default_factory=list)  # e.g. ["429", "ok"]; default ok
    calls: list[ModelRequest] = field(default_factory=list)
    reported: Usage = field(default_factory=lambda: Usage(1_000, 200, 300))

    def capabilities(self, model_id: str) -> ModelCapabilities:
        return self.caps

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        step = self.script.pop(0) if self.script else "ok"
        errors = {
            "429": ProviderErrorKind.RATE_LIMITED,
            "503": ProviderErrorKind.UNAVAILABLE,
            "401": ProviderErrorKind.AUTH,
            "policy": ProviderErrorKind.POLICY,
        }
        if step in errors:
            return ModelResponse(
                self.provider_id,
                request.model_id,
                None,
                "",
                finish_reason=FinishReason.ERROR,
                error=ProviderError(errors[step], f"fake {step}"),
            )
        return ModelResponse(
            self.provider_id,
            request.model_id,
            f"req-{len(self.calls)}",
            "resposta sintetica",
            usage=self.reported,
        )

    def stream(self, request: ModelRequest) -> Iterator[str]:
        yield "resposta "
        yield "sintetica"

    def cancel(self, request_id: str) -> None:
        return None

    def estimate_usage(self, request: ModelRequest) -> Usage:
        chars = sum(len(m.content) for m in request.messages)
        return Usage(max(1, chars // 3), 0, request.max_output_tokens)

    def health(self) -> bool:
        return True
