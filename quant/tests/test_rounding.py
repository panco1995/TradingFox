from __future__ import annotations

from decimal import Decimal

import pytest

from quant.core.rounding import build_order, check_order, floor_qty, round_price


def test_floor_qty():
    assert floor_qty("0.0012345", "0.0001") == Decimal("0.0012")
    assert floor_qty(1.999, 1) == Decimal("1")
    assert floor_qty("12.3456", "0.001") == Decimal("12.345")


def test_round_price():
    assert round_price("100.567", "0.01") == Decimal("100.57")
    assert round_price("100.564", "0.01") == Decimal("100.56")
    assert round_price(1.0004, "0.0001") == Decimal("1.0004")


def test_rounding_avoids_float_noise():
    # 0.1 + 0.2 style errors must not leak into order prices
    assert round_price(0.30000000000000004, "0.01") == Decimal("0.30")
    assert floor_qty(0.30000000000000004, "0.1") == Decimal("0.3")


def test_check_order_rejects_misaligned():
    ok, reason = check_order("100.005", "1", tick_size="0.01", step_size="0.001")
    assert not ok
    assert "tick" in reason


def test_check_order_rejects_min_notional():
    ok, reason = check_order("100", "0.01", tick_size="0.01", step_size="0.01", min_notional="5")
    assert not ok
    assert "notional" in reason


def test_check_order_accepts_valid():
    ok, reason = check_order("100.12", "0.5", tick_size="0.01", step_size="0.1", min_notional="5")
    assert ok
    assert reason == ""


def test_build_order_rounds_into_range():
    order = build_order("100.567", "0.1234", tick_size="0.01", step_size="0.001", min_notional="5")
    assert order == (Decimal("100.57"), Decimal("0.123"))


def test_build_order_returns_none_below_min_notional():
    assert build_order("10", "0.1", tick_size="0.01", step_size="0.001", min_notional="5") is None


def test_invalid_step():
    with pytest.raises(ValueError):
        floor_qty(1, 0)
