"""load_market must work for every interval the UI offers, not just 1m.

Higher timeframes are derived from 1m bars at read time, so a backtest that
asks for 1h would previously fail with "no stored bars".
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant.backtest.market import load_market
from quant.data.resample import SUPPORTED_INTERVALS
from quant.data.store import write_bars


@pytest.fixture
def store(bars_factory, tmp_path):
    """One day of 1m bars for two symbols."""
    start = datetime(2026, 3, 1, tzinfo=UTC)
    for symbol, base in (("BTCUSDT", 100.0), ("ETHUSDT", 50.0)):
        write_bars(bars_factory(40 * 1_440, start=start, base_price=base), symbol, root=tmp_path)
    return tmp_path


def test_every_interval_loads(store):
    for interval in SUPPORTED_INTERVALS:
        market = load_market(
            ["BTCUSDT"],
            root=store,
            interval=interval,
            start=datetime(2026, 3, 1, tzinfo=UTC),
            end=datetime(2026, 4, 9, 23, 59, tzinfo=UTC),
        )
        assert len(market) > 0, interval


def test_bar_counts_match_the_interval(store):
    start = datetime(2026, 3, 2, tzinfo=UTC)
    # `end` is inclusive, so stop at the last minute of the day.
    end = datetime(2026, 3, 2, 23, 59, tzinfo=UTC)

    expected = {"1m": 1_440, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "4h": 6, "12h": 2, "1d": 1}
    for interval, count in expected.items():
        market = load_market(["BTCUSDT"], root=store, interval=interval, start=start, end=end)
        assert len(market) == count, (interval, len(market))


def test_forming_bar_is_excluded(store):
    # The fixture covers 00:00-23:59, so a 1h window ending at 23:30 has a
    # partial final bucket that must not be handed to the engine.
    market = load_market(
        ["BTCUSDT"],
        root=store,
        interval="1h",
        start=datetime(2026, 3, 2, tzinfo=UTC),
        end=datetime(2026, 3, 2, 23, 30, tzinfo=UTC),
    )
    assert len(market) == 23


def test_aggregated_prices_match_underlying_bars(bars_factory, tmp_path):
    start = datetime(2026, 3, 2, tzinfo=UTC)
    write_bars(bars_factory(120, start=start), "BTCUSDT", root=tmp_path)

    hourly = load_market(["BTCUSDT"], root=tmp_path, interval="1h", start=start)
    daily_1m = load_market(["BTCUSDT"], root=tmp_path, interval="1m", start=start)

    assert len(hourly) == 2
    # First hour opens at the first 1m open and closes on the 60th bar.
    assert hourly.open["BTCUSDT"][0] == pytest.approx(daily_1m.open["BTCUSDT"][0])
    assert hourly.close["BTCUSDT"][0] == pytest.approx(daily_1m.close["BTCUSDT"][59])
    # Volume is summed, not sampled.
    assert hourly.volume["BTCUSDT"][0] == pytest.approx(sum(daily_1m.volume["BTCUSDT"][:60]))


def test_two_symbols_align_on_aggregated_bars(store):
    market = load_market(
        ["BTCUSDT", "ETHUSDT"],
        root=store,
        interval="4h",
        start=datetime(2026, 3, 2, tzinfo=UTC),
        end=datetime(2026, 3, 3, tzinfo=UTC),
    )
    assert len(market) == 6
    assert market.symbols == ["BTCUSDT", "ETHUSDT"]


def test_missing_history_gives_an_actionable_error(tmp_path):
    with pytest.raises(ValueError, match="1m history is too short"):
        load_market(["BTCUSDT"], root=tmp_path, interval="1d")
