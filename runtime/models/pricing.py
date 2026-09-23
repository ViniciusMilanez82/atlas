"""Versioned price tables and conservative cost estimation (spec 7.1, 7.4).

cost = uncached_input * p_in + cached_input * p_cached + billable_output * p_out
(+ tools, audio and services, accounted separately). Uses provider-reported usage without
double-counting cached tokens (they are a subset of input). Rounds UP to the currency minor unit
so reservations never under-estimate. Estimate, reported cost and reconciliation stay separate.

The reference table below is copied from the specification (consulted 2026-09-22). It is marked
``verified=False`` until the owner's account confirms availability and prices (D-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from runtime.models.types import Usage
from shared.money import CURRENCY_EXPONENT, Money

PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelPrice:
    provider: str
    model_id: str
    currency: str
    input_per_million: Decimal
    output_per_million: Decimal
    cached_input_per_million: Decimal | None = None  # None: bill cached tokens at the input rate

    def cost(self, usage: Usage) -> Money:
        cached_rate = (
            self.cached_input_per_million
            if self.cached_input_per_million is not None
            else (self.input_per_million)
        )
        uncached = usage.input_tokens - usage.cached_input_tokens
        total = (
            Decimal(uncached) * self.input_per_million
            + Decimal(usage.cached_input_tokens) * cached_rate
            + Decimal(usage.output_tokens) * self.output_per_million
        ) / PER_MILLION
        exp = CURRENCY_EXPONENT[self.currency]
        minor = (total.scaleb(exp)).to_integral_value(rounding=ROUND_CEILING)
        return Money(int(minor), self.currency)

    def max_cost(self, input_tokens: int, max_output_tokens: int) -> Money:
        """Upper bound used for budget reservation before the call."""
        return self.cost(Usage(input_tokens, 0, max_output_tokens))


@dataclass(frozen=True)
class PriceTable:
    version: str
    verified: bool
    prices: tuple[ModelPrice, ...]

    def get(self, provider: str, model_id: str) -> ModelPrice:
        for p in self.prices:
            if p.provider == provider and p.model_id == model_id:
                return p
        raise KeyError(f"no price for {provider}/{model_id} in table {self.version}")


SPEC_REFERENCE_TABLE = PriceTable(
    version="spec-2026-09-22",
    verified=False,
    prices=(
        ModelPrice("openai", "gpt-6-sol", "USD", Decimal(2), Decimal(10)),
        ModelPrice("openai", "gpt-6-astra", "USD", Decimal(10), Decimal(50)),
        ModelPrice("openai", "gpt-6-luna", "USD", Decimal("0.10"), Decimal("0.50")),
        ModelPrice("anthropic", "claude-opus-5-5", "USD", Decimal(4), Decimal(20)),
    ),
)
