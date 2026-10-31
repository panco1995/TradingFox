from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from quant.backtest.metrics import compute_metrics, drawdown_series, max_drawdown


def test_max_drawdown():
    assert max_drawdown(np.array([100, 120, 60, 90])) == pytest.approx(-0.5)
    assert max_drawdown(np.array([100, 110, 120])) == pytest.approx(0.0)


def test_drawdown_series_shape():
    dd = drawdown_series(np.array([100, 110, 55]))
    assert dd[0] == 0
    assert dd[-1] == pytest.approx(-0.5)


def test_metrics_on_flat_equity():
    times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(10)]
    metrics = compute_metrics(times, [1000.0] * 10, [], 1000.0)

    assert metrics["total_return"] == 0
    assert metrics["max_drawdown"] == 0
    assert metrics["trades"] == 0
    # too short to annualise
    assert np.isnan(metrics["cagr"])


def test_short_history_reports_ratios_as_nan():
    times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(3)]
    metrics = compute_metrics(times, [1000.0, 1010.0, 1005.0], [], 1000.0)

    assert np.isnan(metrics["cagr"])
    assert np.isnan(metrics["sharpe"])
    assert np.isnan(metrics["sortino"])
    assert np.isnan(metrics["volatility"])
    assert np.isnan(metrics["calmar"])


def test_metrics_on_growth():
    times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(400)]
    equity = [1000.0 * (1.001**i) for i in range(400)]

    metrics = compute_metrics(times, equity, [], 1000.0)

    assert metrics["total_return"] > 0
    assert metrics["cagr"] > 0
    assert metrics["max_drawdown"] == 0
    assert metrics["volatility"] == pytest.approx(0.0)


def test_trade_stats():
    from quant.backtest.types import Side, TradeRecord

    times = [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(30)]
    equity = [1000.0] * 30
    trades = [
        TradeRecord("BTCUSDT", Side.BUY, 1, 100, 0.1, times[1], 0.0, "entry"),
        TradeRecord("BTCUSDT", Side.SELL, 1, 110, 0.1, times[2], 9.9, "exit"),
        TradeRecord("BTCUSDT", Side.BUY, 1, 100, 0.1, times[3], 0.0, "entry"),
        TradeRecord("BTCUSDT", Side.SELL, 1, 90, 0.1, times[4], -10.1, "exit"),
    ]

    metrics = compute_metrics(times, equity, trades, 1000.0)

    assert metrics["trades"] == 4
    assert metrics["round_trips"] == 2
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["profit_factor"] == pytest.approx(9.9 / 10.1)
