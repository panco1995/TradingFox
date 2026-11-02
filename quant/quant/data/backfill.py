"""Work out which parts of a history window are missing.

The admin UI offers a "backfill one year" button, but re-downloading a year of
1m bars takes minutes and hammers the exchange for no reason. So the button
first asks this module what is actually missing, and only fetches the gaps.

A window counts as satisfied when every bar is present. Gaps inside the range
and missing head/tail segments are both reported as ``(start, end)`` spans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl

from quant.data.binance import INTERVAL_MS
from quant.data.store import read_bars

#: A window is "complete enough" when it has no gap wider than this many bars.
#: Exchange downtime produces the odd hourly hole; re-fetching a year to repair
#: a single missing minute is not worth it.
DEFAULT_TOLERANCE_BARS = 5


@dataclass
class GapSpan:
    start: datetime
    end: datetime
    missing_bars: int


@dataclass
class CoveragePlan:
    """What a backfill would need to do for one symbol."""

    symbol: str
    interval: str
    window_start: datetime
    window_end: datetime
    bars_present: int = 0
    bars_expected: int = 0
    spans: list[GapSpan] = field(default_factory=list)
    #: True when the stored range does not cover the whole window at all.
    missing_head: bool = False
    missing_tail: bool = False

    @property
    def complete(self) -> bool:
        return not self.spans

    @property
    def missing_bars(self) -> int:
        return sum(span.missing_bars for span in self.spans)

    @property
    def ratio(self) -> float:
        if self.bars_expected <= 0:
            return 0.0
        return min(1.0, self.bars_present / self.bars_expected)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "bars_present": self.bars_present,
            "bars_expected": self.bars_expected,
            "missing_bars": self.missing_bars,
            "ratio": round(self.ratio, 6),
            "complete": self.complete,
            "missing_head": self.missing_head,
            "missing_tail": self.missing_tail,
            "spans": [
                {
                    "start": span.start.isoformat(),
                    "end": span.end.isoformat(),
                    "missing_bars": span.missing_bars,
                }
                for span in self.spans
            ],
        }


def _expected_count(step_ms: int, start: datetime, end: datetime) -> int:
    span = int((end - start).total_seconds() * 1000)
    return max(0, span // step_ms + 1)


def plan_backfill(
    symbol: str,
    days: int = 365,
    interval: str = "1m",
    root: Path | None = None,
    end: datetime | None = None,
    tolerance_bars: int = DEFAULT_TOLERANCE_BARS,
    max_spans: int = 24,
) -> CoveragePlan:
    """Compare stored bars against the window we want them to cover."""
    step_ms = INTERVAL_MS[interval]
    step = timedelta(milliseconds=step_ms)
    window_end = (end or datetime.now(UTC)).astimezone(UTC)
    window_start = window_end - timedelta(days=days)

    plan = CoveragePlan(
        symbol=symbol,
        interval=interval,
        window_start=window_start,
        window_end=window_end,
        bars_expected=_expected_count(step_ms, window_start, window_end),
    )

    frame = read_bars(symbol, start=window_start, end=window_end, root=root, interval=interval)
    if frame.is_empty():
        plan.missing_head = True
        plan.missing_tail = True
        plan.spans = [GapSpan(window_start, window_end, plan.bars_expected)]
        return plan

    times = frame.select("open_time").sort("open_time")["open_time"]
    plan.bars_present = times.len()
    first = times[0]
    last = times[-1]

    # Head: everything before the earliest stored bar, but only report it when
    # the shortfall is real rather than a rounding artefact.
    if first > window_start + step * tolerance_bars:
        missing = _expected_count(step_ms, window_start, first) - 1
        if missing > tolerance_bars:
            plan.missing_head = True
            plan.spans.append(GapSpan(window_start, first - step, missing))

    # Tail: everything after the newest stored bar up to the window end.
    if last < window_end - step * tolerance_bars:
        missing = _expected_count(step_ms, last, window_end) - 1
        if missing > tolerance_bars:
            plan.missing_tail = True
            plan.spans.append(GapSpan(last + step, window_end, missing))

    # Interior holes, found without materialising a full expected grid.
    deltas = (
        frame.select(
            pl.col("open_time").shift(1).alias("prev"),
            pl.col("open_time").alias("cur"),
        )
        .with_columns(((pl.col("cur") - pl.col("prev")).dt.total_milliseconds()).alias("delta"))
        .filter(pl.col("delta") > step_ms * (tolerance_bars + 1))
    )
    for row in deltas.iter_rows(named=True):
        missing = int(row["delta"] // step_ms) - 1
        if missing <= tolerance_bars:
            continue
        plan.spans.append(GapSpan(row["prev"] + step, row["cur"] - step, missing))

    plan.spans.sort(key=lambda span: span.start)
    if len(plan.spans) > max_spans:
        merged: list[GapSpan] = []
        for span in plan.spans:
            if merged and (span.start - merged[-1].end) <= step * 2:
                merged[-1] = GapSpan(
                    merged[-1].start, span.end, merged[-1].missing_bars + span.missing_bars
                )
            else:
                merged.append(span)
        plan.spans = merged[:max_spans]

    return plan


def plans_for(
    symbols: list[str],
    days: int = 365,
    interval: str = "1m",
    root: Path | None = None,
    end: datetime | None = None,
) -> list[CoveragePlan]:
    return [
        plan_backfill(symbol, days=days, interval=interval, root=root, end=end)
        for symbol in symbols
    ]
