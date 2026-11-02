"""Gap detection decides whether the backfill button does anything at all.

The whole point of the button is to avoid re-downloading a year of 1m bars when
the data is already there, so these tests pin down what counts as "missing".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant.data.backfill import plan_backfill
from quant.data.store import write_bars

END = datetime(2026, 3, 10, tzinfo=UTC)
START = END - timedelta(days=2)


def _fill(bars_factory, tmp_path, start, count, symbol="BTCUSDT", base=100.0):
    write_bars(bars_factory(count, start=start, base_price=base), symbol, root=tmp_path)


def test_complete_window_needs_no_work(bars_factory, tmp_path):
    _fill(bars_factory, tmp_path, START, 2 * 1_440 + 1)

    plan = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END)

    assert plan.complete is True
    assert plan.spans == []
    assert plan.missing_bars == 0
    assert plan.ratio == pytest.approx(1.0, abs=1e-4)


def test_empty_store_reports_the_whole_window(tmp_path):
    plan = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END)

    assert plan.complete is False
    assert plan.missing_head is True
    assert plan.missing_tail is True
    assert plan.bars_present == 0
    assert len(plan.spans) == 1
    assert plan.spans[0].missing_bars == plan.bars_expected


def test_short_history_reports_a_head_gap(bars_factory, tmp_path):
    # Only the last 6 hours are stored.
    _fill(bars_factory, tmp_path, END - timedelta(hours=6), 361)

    plan = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END)

    assert plan.missing_head is True
    assert plan.missing_tail is False
    assert plan.complete is False
    assert plan.spans[0].start == plan.window_start


def test_interior_hole_is_detected(bars_factory, tmp_path):
    _fill(bars_factory, tmp_path, START, 2 * 1_440 + 1)
    # Punch out 2 hours in the middle.
    from quant.data.store import read_bars

    stored = read_bars("BTCUSDT", root=tmp_path)
    hole_start = START + timedelta(hours=12)
    hole_end = hole_start + timedelta(hours=2)
    kept = stored.filter((stored["open_time"] < hole_start) | (stored["open_time"] >= hole_end))
    # Rewrite from scratch so the hole really exists on disk.
    import shutil

    shutil.rmtree(tmp_path / "raw")
    write_bars(kept, "BTCUSDT", root=tmp_path)

    plan = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END)

    assert plan.missing_head is False
    assert plan.missing_tail is False
    assert len(plan.spans) == 1
    assert plan.spans[0].missing_bars == 120
    assert plan.spans[0].start == hole_start


def test_small_holes_are_tolerated(bars_factory, tmp_path):
    _fill(bars_factory, tmp_path, START, 2 * 1_440 + 1)
    from quant.data.store import read_bars

    stored = read_bars("BTCUSDT", root=tmp_path)
    # A single missing minute: repairing it is not worth a year of re-downloads.
    hole = START + timedelta(hours=12)
    kept = stored.filter(stored["open_time"] != hole)
    import shutil

    shutil.rmtree(tmp_path / "raw")
    write_bars(kept, "BTCUSDT", root=tmp_path)

    plan = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END)

    assert plan.complete is True


def test_plan_serialises_for_the_api(bars_factory, tmp_path):
    _fill(bars_factory, tmp_path, END - timedelta(hours=6), 361)

    payload = plan_backfill("BTCUSDT", days=2, root=tmp_path, end=END).as_dict()

    assert payload["symbol"] == "BTCUSDT"
    assert payload["complete"] is False
    assert payload["missing_bars"] > 0
    assert isinstance(payload["spans"], list)
    assert {"start", "end", "missing_bars"} <= set(payload["spans"][0])
