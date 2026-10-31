from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant.backtest.broker import BrokerConfig, SimBroker
from quant.backtest.types import Order, Position, Side

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def broker(**kwargs) -> SimBroker:
    return SimBroker(BrokerConfig(**kwargs))


def test_buy_applies_fee_and_slippage():
    b = broker(fee_rate=0.001, slippage_bps=10)
    pos = Position("BTCUSDT")

    fill = b.execute(Order("BTCUSDT", Side.BUY, qty=1.0), 100.0, 1_000.0, 1_000.0, pos, NOW)

    assert fill is not None
    assert fill.price == pytest.approx(100.1)
    assert fill.fee == pytest.approx(0.1001)
    assert pos.qty == pytest.approx(1.0)
    assert pos.avg_price == pytest.approx(100.1)


def test_buy_is_capped_by_cash():
    b = broker(fee_rate=0.0, slippage_bps=0.0)
    pos = Position("BTCUSDT")

    fill = b.execute(Order("BTCUSDT", Side.BUY, qty=100.0), 100.0, 10_000.0, 500.0, pos, NOW)

    assert fill is not None
    assert fill.qty == pytest.approx(5.0)


def test_buy_is_capped_by_bar_volume():
    b = broker(fee_rate=0.0, slippage_bps=0.0, max_participation=0.01)
    pos = Position("BTCUSDT")

    fill = b.execute(Order("BTCUSDT", Side.BUY, qty=100.0), 100.0, 10.0, 1e9, pos, NOW)

    assert fill is not None
    assert fill.qty == pytest.approx(0.1)  # 1% of 10


def test_buy_below_min_notional_is_rejected():
    b = broker(fee_rate=0.0, slippage_bps=0.0, min_notional=5.0)
    pos = Position("BTCUSDT")

    assert b.execute(Order("BTCUSDT", Side.BUY, qty=0.01), 100.0, 1e6, 1e9, pos, NOW) is None
    assert pos.qty == 0.0


def test_sell_is_not_volume_capped():
    """Exits must not get stuck because a single bar was thin."""
    b = broker(fee_rate=0.0, slippage_bps=0.0, max_participation=0.01)
    pos = Position("BTCUSDT", qty=10.0, avg_price=100.0)

    fill = b.execute(Order("BTCUSDT", Side.SELL, qty=None), 110.0, 1.0, 0.0, pos, NOW)

    assert fill is not None
    assert fill.qty == pytest.approx(10.0)
    assert pos.is_flat


def test_sell_realises_pnl():
    b = broker(fee_rate=0.001, slippage_bps=0.0)
    pos = Position("BTCUSDT", qty=2.0, avg_price=100.0)

    fill = b.execute(Order("BTCUSDT", Side.SELL, qty=None), 110.0, 1e6, 0.0, pos, NOW)

    assert fill is not None
    # (110 - 100) * 2 - fee(2.2)
    assert fill.realized_pnl == pytest.approx(20.0 - 0.22)
    assert pos.realized_pnl == pytest.approx(20.0 - 0.22)


def test_sell_cannot_exceed_position():
    b = broker(fee_rate=0.0, slippage_bps=0.0)
    pos = Position("BTCUSDT", qty=1.0, avg_price=100.0)

    fill = b.execute(Order("BTCUSDT", Side.SELL, qty=5.0), 100.0, 1e6, 0.0, pos, NOW)

    assert fill is not None
    assert fill.qty == pytest.approx(1.0)


def test_flat_position_sell_is_noop():
    b = broker()
    pos = Position("BTCUSDT")

    assert b.execute(Order("BTCUSDT", Side.SELL), 100.0, 1e6, 1000.0, pos, NOW) is None


def test_invalid_price_is_ignored():
    b = broker()
    pos = Position("BTCUSDT")
    assert b.execute(Order("BTCUSDT", Side.BUY, qty=1.0), 0.0, 1e6, 1000.0, pos, NOW) is None
