"""Money in integer minor units with explicit currency (spec 7.4, 13.1).

The minor-unit exponent depends on the currency (ISO 4217). It is never assumed to be 2.
Unknown currencies are rejected instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# ISO 4217 minor-unit exponents for currencies the product supports. Extend deliberately.
CURRENCY_EXPONENT: dict[str, int] = {
    "USD": 2,
    "BRL": 2,
    "EUR": 2,
    "GBP": 2,
    "CHF": 2,
    "CAD": 2,
    "AUD": 2,
    "MXN": 2,
    "ARS": 2,
    "CLP": 0,
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "BHD": 3,
}


class MoneyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise MoneyError("amount_minor must be an integer")
        if self.currency not in CURRENCY_EXPONENT:
            raise MoneyError(f"unsupported currency: {self.currency!r}")

    @property
    def exponent(self) -> int:
        return CURRENCY_EXPONENT[self.currency]

    @classmethod
    def from_major(cls, amount: str | Decimal, currency: str) -> Money:
        """Build from a decimal string such as ``"12.34"``. Rejects excess precision."""
        if currency not in CURRENCY_EXPONENT:
            raise MoneyError(f"unsupported currency: {currency!r}")
        exp = CURRENCY_EXPONENT[currency]
        d = Decimal(amount)
        scaled = d.scaleb(exp)
        if scaled != scaled.to_integral_value():
            raise MoneyError(f"{amount} has more precision than {currency} allows ({exp})")
        return cls(int(scaled), currency)

    def to_major_str(self) -> str:
        if self.exponent == 0:
            return str(self.amount_minor)
        return str(Decimal(self.amount_minor).scaleb(-self.exponent))

    def _same(self, other: Money) -> None:
        if self.currency != other.currency:
            raise MoneyError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __le__(self, other: Money) -> bool:
        self._same(other)
        return self.amount_minor <= other.amount_minor

    def __lt__(self, other: Money) -> bool:
        self._same(other)
        return self.amount_minor < other.amount_minor

    def to_json(self) -> dict[str, Any]:
        return {"amount_minor": self.amount_minor, "currency": self.currency}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Money:
        if set(data) != {"amount_minor", "currency"}:
            raise MoneyError("money requires exactly amount_minor and currency")
        return cls(data["amount_minor"], data["currency"])
