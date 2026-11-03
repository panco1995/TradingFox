"""Unit tests for the intraday strategies added for 15-minute trading."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from quant.backtest.engine import BacktestConfig, BacktestEngine
from quant.backtest.market import MarketData
from quant.strategies import registry
from quant.strategies.bollinger_rsi import (
    BollingerRSIParams,
    _ema,
    _rsi,
)
from quant.strategies.supertrend import SupertrendParams, SupertrendState, _supertrend

# --------------------------------------------------------------------------- #
# bollinger_rsi helpers
# --------------------------------------------------------------------------- #


def test_rsi_is_100_when_every_change_is_a_gain():
    closes = np.arange(1.0, 21.0)
    assert _rsi(closes, 14) == pytest.approx(100.0)


def test_rsi_is_0_when_every_change_is_a_loss():
    closes = np.arange(20.0, 0.0, -1.0)
    assert _rsi(closes, 14) == pytest.approx(0.0)


def test_rsi_needs_one_more_bar_than_the_window():
    assert _rsi(np.arange(10.0), 14) is None
    assert _rsi(np.arange(15.0), 14) is not None


def test_ema_of_a_constant_series_is_that_constant():
    assert _ema(np.full(50, 42.0), 20) == pytest.approx(42.0)


def test_ema_needs_at_least_one_period():
    assert _ema(np.arange(5.0), 10) is None


def test_bollinger_params_reject_inverted_rsi_thresholds():
    with pytest.raises(ValidationError):
        BollingerRSIParams(rsi_entry=60.0, rsi_exit=50.0)


# --------------------------------------------------------------------------- #
# supertrend helpers
# --------------------------------------------------------------------------- #


def test_atr_of_a_constant_range_is_that_range():
    state = SupertrendState(period=10, multiplier=3.0)
    close = 100.0
    for _ in range(10):
        state.update(high=101.0, low=99.0, close=close)

    assert state.atr == pytest.approx(2.0)

    state.update(high=101.0, low=99.0, close=close)
    assert state.atr == pytest.approx(2.0)


def test_supertrend_reports_warmup_before_the_first_atr():
    state = SupertrendState(period=5, multiplier=3.0)
    for _ in range(4):
        direction, _ = state.update(high=101.0, low=99.0, close=100.0)
        assert direction == 0
    direction, _ = state.update(high=101.0, low=99.0, close=100.0)
    assert direction == 1


def test_supertrend_points_up_in_an_uptrend():
    close = np.arange(100.0, 200.0)
    high = close + 0.5
    low = close - 0.5

    direction, _ = _supertrend(high, low, close, 10, 3.0)

    assert direction[-1] == 1
    assert direction[-10:].min() == 1


def test_supertrend_points_down_in_a_downtrend():
    close = np.arange(200.0, 100.0, -1.0)
    high = close + 0.5
    low = close - 0.5

    direction, _ = _supertrend(high, low, close, 10, 3.0)

    assert direction[-1] == -1
    assert direction[-10:].max() == -1


def test_supertrend_params_reject_a_one_bar_atr():
    with pytest.raises(ValidationError):
        SupertrendParams(atr_period=1)


# --------------------------------------------------------------------------- #
# registry wiring
# --------------------------------------------------------------------------- #


def test_intraday_strategies_are_registered_and_described():
    names = set(registry.names())
    assert {"bollinger_rsi", "supertrend"} <= names

    specs = {item["name"]: item for item in registry.describe_all()}
    for name in ("bollinger_rsi", "supertrend"):
        assert specs[name]["title"]
        assert specs[name]["description"]
        assert specs[name]["params_schema"]["type"] == "object"
        assert specs[name]["defaults"]["target"] == 0.95


def test_supertrend_build_coerces_string_parameters():
    strategy = registry.build("supertrend", {"atr_period": "5", "atr_mult": "2.5"})
    assert strategy.params.atr_period == 5
    assert strategy.params.atr_mult == 2.5


# --------------------------------------------------------------------------- #
# end-to-end: the strategy actually enters on a trending market
# --------------------------------------------------------------------------- #


def _rising_market(count: int = 160) -> MarketData:
    times = np.arange(count, dtype=np.int64) * 15 * 60_000 + 1_767_225_600_000
    close = np.arange(100.0, 100.0 + count)
    return MarketData(
        symbols=["BTCUSDT"],
        times_ms=times,
        open={"BTCUSDT": close.copy()},
        high={"BTCUSDT": close + 0.8},
        low={"BTCUSDT": close - 0.8},
        close={"BTCUSDT": close},
        volume={"BTCUSDT": np.full(count, 10.0)},
    )


def test_supertrend_goes_long_in_a_sustained_uptrend():
    strategy = registry.build("supertrend", {"atr_period": 10, "atr_mult": 3.0})
    engine = BacktestEngine(
        _rising_market(),
        strategy,
        BacktestConfig(initial_cash=10_000, fee_rate=0.0, slippage_bps=0),
    )

    result = engine.run()

    assert result.trades, "expected at least one entry"
    assert result.trades[0].side == "buy"
    assert result.trades[0].reason == "supertrend_long"
    assert all(trade.side == "buy" for trade in result.trades)
    assert result.final_equity > result.initial_cash
