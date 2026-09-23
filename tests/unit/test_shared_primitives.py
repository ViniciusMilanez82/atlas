from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from shared.canonical import CanonicalizationError, canonical_bytes, canonical_hash
from shared.clock import ManualClock, parse_utc, to_utc_str
from shared.config import load_config, paid_calls_configured, parse_config
from shared.contracts import ContractError
from shared.errors import AtlasError, ErrorCode
from shared.ids import is_uuid, new_id, new_nonce
from shared.money import Money, MoneyError

ROOT = Path(__file__).resolve().parents[2]


class TestCanonical:
    def test_key_order_does_not_change_hash(self) -> None:
        assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})

    def test_material_change_changes_hash(self) -> None:
        base = {"to": "a@example.test", "amount_minor": 1000}
        assert canonical_hash(base) != canonical_hash({**base, "amount_minor": 1001})
        assert canonical_hash(base) != canonical_hash({**base, "to": "b@example.test"})

    def test_floats_rejected(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonical_bytes({"amount": 10.5})

    def test_unicode_is_stable(self) -> None:
        assert canonical_bytes({"n": "ação"}) == '{"n":"ação"}'.encode()

    def test_unsupported_types_rejected(self) -> None:
        with pytest.raises(CanonicalizationError):
            canonical_bytes({"when": datetime.now(UTC)})


class TestMoney:
    @pytest.mark.parametrize(
        ("major", "cur", "minor"),
        [("12.34", "USD", 1234), ("129.90", "BRL", 12990), ("1500", "JPY", 1500), ("1.234", "KWD", 1234)],
    )
    def test_exponent_depends_on_currency(self, major: str, cur: str, minor: int) -> None:
        assert Money.from_major(major, cur).amount_minor == minor

    def test_excess_precision_rejected(self) -> None:
        with pytest.raises(MoneyError):
            Money.from_major("10.5", "JPY")
        with pytest.raises(MoneyError):
            Money.from_major(Decimal("1.001"), "USD")

    def test_unknown_currency_rejected(self) -> None:
        with pytest.raises(MoneyError):
            Money(100, "XYZ")

    def test_mixed_currency_arithmetic_rejected(self) -> None:
        with pytest.raises(MoneyError):
            _ = Money(1, "USD") + Money(1, "BRL")

    def test_bool_is_not_an_amount(self) -> None:
        with pytest.raises(MoneyError):
            Money(True, "USD")  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        m = Money(12990, "BRL")
        assert Money.from_json(m.to_json()) == m
        assert m.to_major_str() == "129.90"


class TestClockAndIds:
    def test_utc_formatting(self) -> None:
        dt = datetime(2026, 9, 22, 9, 0, tzinfo=timezone(timedelta(hours=-3)))
        assert to_utc_str(dt) == "2026-09-22T12:00:00.000Z"
        assert parse_utc("2026-09-22T12:00:00.000Z") == dt

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(ValueError):
            to_utc_str(datetime(2026, 1, 1))

    def test_manual_clock(self) -> None:
        c = ManualClock()
        t0 = c.now()
        c.advance(seconds=5)
        assert (c.now() - t0).total_seconds() == 5

    def test_ids(self) -> None:
        assert is_uuid(new_id())
        assert not is_uuid("task-example-001")
        assert len(new_nonce()) == 32


class TestConfig:
    def test_default_config_is_valid_and_paid_calls_blocked(self) -> None:
        cfg = load_config(ROOT / "config" / "atlas.default.yaml")
        assert cfg["intelligence"]["default_profile"] == "general"
        assert paid_calls_configured(cfg) is False

    def test_default_profile_must_exist(self) -> None:
        cfg = load_config(ROOT / "config" / "atlas.default.yaml")
        cfg["intelligence"]["default_profile"] = "missing"
        with pytest.raises(ContractError):
            parse_config(cfg)

    def test_cross_provider_fallback_not_grantable_by_config(self) -> None:
        cfg = load_config(ROOT / "config" / "atlas.default.yaml")
        cfg["intelligence"]["profiles"]["second"] = {"provider": "anthropic", "model_id": "claude-opus-5-5"}
        cfg["intelligence"]["allow_cross_provider_fallback"] = True
        with pytest.raises(ContractError):
            parse_config(cfg)

    def test_task_limit_cannot_exceed_monthly(self) -> None:
        cfg = load_config(ROOT / "config" / "atlas.default.yaml")
        cfg["budget"]["monthly_limit_minor"] = 1000
        cfg["budget"]["per_task_limit_minor"] = 2000
        with pytest.raises(ContractError):
            parse_config(cfg)


def test_errors_carry_retry_and_persistence_info() -> None:
    err = AtlasError(ErrorCode.EXTERNAL_EFFECT_UNKNOWN, "send may have happened", persisted="action UNKNOWN")
    payload = err.to_jsonrpc("corr-00000001")
    assert payload["data"]["retryable"] is False  # type: ignore[index]
    assert AtlasError(ErrorCode.RATE_LIMITED, "slow down").retryable is True
