from __future__ import annotations

import numpy as np

from quant.backtest.engine import BacktestConfig, BacktestEngine
from quant.backtest.market import MarketData


class Recorder:
    """Strategy that buys on the first bar and records what it could see."""

    def __init__(self) -> None:
        self.history_lengths: list[int] = []
        self.seen_closes: list[float] = []
        self.bar_times: list = []

    def on_start(self, ctx) -> None:
        pass

    def on_bar(self, ctx, bar) -> None:
        self.history_lengths.append(len(ctx.history(bar.symbol, "close", 10_000)))
        self.seen_closes.append(bar.close)
        self.bar_times.append(bar.open_time)
        if len(self.history_lengths) == 1:
            ctx.target_percent(bar.symbol, 0.9, reason="entry")

    def on_stop(self, ctx) -> None:
        pass


def make_market(opens: list[float], closes: list[float]) -> MarketData:
    n = len(closes)
    times = np.arange(n, dtype=np.int64) * 60_000 + 1_767_225_600_000
    arr = np.asarray
    return MarketData(
        symbols=["BTCUSDT"],
        times_ms=times,
        open={"BTCUSDT": arr(opens, dtype=float)},
        high={"BTCUSDT": arr([max(o, c) + 1 for o, c in zip(opens, closes, strict=True)])},
        low={"BTCUSDT": arr([min(o, c) - 1 for o, c in zip(opens, closes, strict=True)])},
        close={"BTCUSDT": arr(closes, dtype=float)},
        volume={"BTCUSDT": arr([1_000.0] * n)},
    )


def test_order_fills_at_next_bar_open():
    market = make_market(opens=[100, 101, 102, 103], closes=[100, 100, 101, 102])
    strategy = Recorder()
    engine = BacktestEngine(
        market,
        strategy,
        BacktestConfig(initial_cash=1_000, fee_rate=0.0, slippage_bps=10),
    )

    result = engine.run()

    assert len(result.trades) == 1
    trade = result.trades[0]
    # decided on bar 0 (close 100), filled on bar 1 open (101) + 10bps slippage
    assert trade.time == result.times[1]
    assert trade.price == 101 * 1.001


def test_strategy_never_sees_future_bars():
    market = make_market(opens=[100, 101, 102], closes=[100, 101, 102])
    strategy = Recorder()
    BacktestEngine(market, strategy, BacktestConfig(fee_rate=0, slippage_bps=0)).run()

    assert strategy.history_lengths == [1, 2, 3]
    assert strategy.seen_closes == [100, 101, 102]


def test_equity_curve_tracks_mark_to_market():
    market = make_market(opens=[100, 100, 110], closes=[100, 100, 110])
    strategy = Recorder()
    engine = BacktestEngine(
        market, strategy, BacktestConfig(initial_cash=1_000, fee_rate=0, slippage_bps=0)
    )

    result = engine.run()

    assert len(result.equity) == 3
    assert result.equity[0] == 1_000
    assert result.equity[-1] > 1_000  # holding 9 units while price went 100 -> 110
    assert result.final_equity == result.equity[-1]


def test_exposure_reported():
    market = make_market(opens=[100, 100, 100, 100], closes=[100, 100, 100, 100])
    strategy = Recorder()
    result = BacktestEngine(market, strategy, BacktestConfig(initial_cash=1_000)).run()

    assert 0.0 <= result.exposure <= 1.0
    assert result.bars_processed == 4
