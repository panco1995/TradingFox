from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from quant.data.collector import Collector, compute_backfill_start
from quant.data.store import read_bars


def _event(symbol: str = "BTCUSDT", final: bool = True, open_ms: int = 1793427780000) -> dict:
    return {
        "data": {
            "e": "kline",
            "s": symbol,
            "k": {
                "t": open_ms,
                "T": open_ms + 59_999,
                "s": symbol,
                "i": "1m",
                "o": "100.0",
                "c": "101.0",
                "h": "102.0",
                "l": "99.0",
                "v": "5.0",
                "n": 10,
                "x": final,
                "q": "500.0",
                "V": "2.0",
                "Q": "200.0",
            },
        }
    }


@pytest.fixture
def collector(tmp_path):
    return Collector(symbols=["BTCUSDT", "ETHUSDT"], root=tmp_path)


def test_only_final_bars_are_buffered(collector):
    assert collector.handle_message(_event(final=False)) is None
    assert collector.pending() == 0

    bar = collector.handle_message(_event(final=True))
    assert bar is not None
    assert collector.pending() == 1


def test_unknown_symbol_is_ignored(collector):
    assert collector.handle_message(_event(symbol="DOGEUSDT")) is None
    assert collector.pending() == 0


def test_non_kline_is_ignored(collector):
    assert collector.handle_message({"result": None, "id": 1}) is None


def test_flush_writes_per_symbol(collector, tmp_path):
    collector.handle_message(_event("BTCUSDT", open_ms=1793427780000))
    collector.handle_message(_event("ETHUSDT", open_ms=1793427780000))

    written = collector.flush()

    assert written == 2
    assert collector.pending() == 0
    assert read_bars("BTCUSDT", root=tmp_path, interval="1m").height == 1
    assert read_bars("ETHUSDT", root=tmp_path, interval="1m").height == 1


def test_duplicate_bars_do_not_duplicate_rows(collector, tmp_path):
    collector.handle_message(_event())
    collector.flush()
    collector.handle_message(_event())
    collector.flush()

    assert read_bars("BTCUSDT", root=tmp_path, interval="1m").height == 1


def test_flush_is_noop_when_empty(collector):
    assert collector.flush() == 0


def test_stats_track_progress(collector):
    collector.handle_message(_event(final=False))
    collector.handle_message(_event(final=True))

    assert collector.stats.bars_seen == 2
    assert collector.stats.messages == 0  # messages are counted by the ws loop


def test_invalid_interval_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsupported interval"):
        Collector(symbols=["BTCUSDT"], interval="2m", root=tmp_path)


def test_empty_symbols_rejected(tmp_path):
    with pytest.raises(ValueError, match="at least one symbol"):
        Collector(symbols=[], root=tmp_path)


def test_run_flushes_buffered_bars_on_exit(monkeypatch, tmp_path):
    collector = Collector(symbols=["BTCUSDT"], root=tmp_path)

    async def no_backfill(*_args, **_kwargs):
        return None

    async def one_bar_then_stop(deadline):
        collector.handle_message(_event())
        collector.request_stop()

    monkeypatch.setattr(collector, "_backfill_all", no_backfill)
    monkeypatch.setattr(collector, "_stream_once", one_bar_then_stop)

    asyncio.run(collector.run())

    assert read_bars("BTCUSDT", root=tmp_path, interval="1m").height == 1


def test_reconnect_loop_survives_errors(monkeypatch, tmp_path):
    collector = Collector(symbols=["BTCUSDT"], root=tmp_path)
    attempts = {"n": 0}

    async def no_backfill(*_args, **_kwargs):
        return None

    async def no_sleep(_seconds):
        return None

    async def flaky_stream(deadline):
        attempts["n"] += 1
        collector.handle_message(_event(open_ms=1793427780000 + attempts["n"] * 60_000))
        if attempts["n"] < 3:
            raise ConnectionError("simulated drop")
        collector.request_stop()

    monkeypatch.setattr(collector, "_backfill_all", no_backfill)
    monkeypatch.setattr(collector, "_sleep", no_sleep)
    monkeypatch.setattr(collector, "_stream_once", flaky_stream)

    asyncio.run(collector.run())

    assert attempts["n"] == 3
    assert read_bars("BTCUSDT", root=tmp_path, interval="1m").height == 3


def test_backfill_start_without_data_is_history():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    start = compute_backfill_start(None, now, timedelta(minutes=1), backfill_days=2)
    assert start == now - timedelta(days=2)


def test_backfill_start_continues_after_last_bar():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=10)
    start = compute_backfill_start(last, now, timedelta(minutes=1), backfill_days=2)
    assert start == last + timedelta(minutes=1)


def test_backfill_start_repairs_recent_tail():
    # a hole behind the newest bar must still be re-fetched
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    last = now - timedelta(minutes=1)
    start = compute_backfill_start(
        last, now, timedelta(minutes=1), backfill_days=2, repair_window=timedelta(hours=2)
    )
    assert start == now - timedelta(hours=2)
