"""Model provider contracts owned by Atlas (spec 6.4, ADR-005).

The interface does not assume identical support for temperature, reasoning effort, vision, tools,
audio or strict JSON: each adapter declares capabilities and applies only documented parameters.
State belongs to Atlas, never to a provider SDK session.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from shared.money import Money


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class ModelCapabilities:
    structured_output: bool = False
    tool_calls: bool = False
    vision: bool = False
    audio: bool = False
    streaming: bool = False
    effort_levels: tuple[str, ...] = ()
    context_window_tokens: int = 0
    max_output_tokens: int = 0


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    messages: tuple[Message, ...]
    max_output_tokens: int
    json_schema: dict[str, Any] | None = None
    effort: str | None = None
    timeout_s: float = 60.0


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.cached_input_tokens, self.output_tokens) < 0:
            raise ValueError("token counts cannot be negative")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached tokens are a subset of input tokens")


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALL = "tool_call"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    ERROR = "error"


class ProviderErrorKind(StrEnum):
    RATE_LIMITED = "RATE_LIMITED"  # 429: backoff, compatible fallback allowed
    UNAVAILABLE = "UNAVAILABLE"  # 5xx/timeouts: backoff, compatible fallback allowed
    AUTH = "AUTH"  # credential problem: ask the owner to re-authorize, never fall back
    POLICY = "POLICY"  # provider refused content: never route around it with another model
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"


@dataclass(frozen=True)
class ProviderError:
    kind: ProviderErrorKind
    message: str
    retry_after_s: float | None = None


@dataclass(frozen=True)
class ModelResponse:
    """Normalized result (spec 6.4). Output is untrusted model text, never an authorization."""

    provider: str
    model_id: str
    request_id: str | None
    output_text: str
    proposed_tool_calls: tuple[dict[str, Any], ...] = ()
    finish_reason: FinishReason = FinishReason.STOP
    usage: Usage | None = None
    estimated_cost: Money | None = None
    error: ProviderError | None = None
    raw_extra: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    provider_id: str

    def capabilities(self, model_id: str) -> ModelCapabilities: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> Iterator[str]: ...

    def cancel(self, request_id: str) -> None: ...

    def estimate_usage(self, request: ModelRequest) -> Usage: ...

    def health(self) -> bool: ...
