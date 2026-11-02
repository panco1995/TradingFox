"""Backfill only the missing parts of a symbol's history.

`quant fetch --days 365` always starts from the window start and re-downloads
everything. For a symbol that is already up to date that is minutes of useless
work, and for one with a single interior hole it is almost entirely waste. This
module drives the same idempotent store but walks the gaps found by
`plan_backfill`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant.data.backfill import CoveragePlan, GapSpan, plan_backfill
from quant.data.binance import INTERVAL_MS, BinanceError, BinanceMarketData
from quant.data.store import write_bars

log = logging.getLogger(__name__)

#: A single REST page is 1000 bars; keep spans a bit wider than that so the
#: pager does not round-trip for tiny holes.
_MIN_SPAN_BARS = 1_000


@dataclass
class BackfillResult:
    symbol: str
    interval: str
    fetched_bars: int = 0
    rows_added: int = 0
    rows_updated: int = 0
    spans_done: int = 0
    skipped: bool = False
    error: str | None = None
    plan: CoveragePlan | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "fetched_bars": self.fetched_bars,
            "rows_added": self.rows_added,
            "rows_updated": self.rows_updated,
            "spans_done": self.spans_done,
            "skipped": self.skipped,
            "error": self.error,
        }
        if self.plan is not None:
            payload["before"] = self.plan.as_dict()
        return payload


def _floor_to_bar(dt: datetime, interval: str) -> datetime:
    step_ms = INTERVAL_MS[interval]
    ms = int(dt.timestamp() * 1000)
    return datetime.fromtimestamp((ms // step_ms) * step_ms // 1000, tz=UTC)


def _widen(
    start: datetime, end: datetime, interval: str, min_bars: int = _MIN_SPAN_BARS
) -> tuple[datetime, datetime]:
    """Round a span outwards to at least `min_bars` and onto bar boundaries."""
    step = timedelta(milliseconds=INTERVAL_MS[interval])
    if (end - start) < step * min_bars:
        grow = (step * min_bars - (end - start)) / 2
        start -= grow
        end += grow
    return _floor_to_bar(start, interval), end


def backfill_symbol(
    symbol: str,
    days: int = 365,
    interval: str = "1m",
    root: Path | None = None,
    base_url: str | None = None,
    force: bool = False,
    end: datetime | None = None,
    max_spans: int = 24,
    progress=None,
) -> BackfillResult:
    """Fill only what is missing. Returns a result even when nothing was needed."""
    plan = plan_backfill(symbol, days=days, interval=interval, root=root, end=end)
    result = BackfillResult(symbol=symbol, interval=interval, plan=plan)

    if plan.complete and not force:
        result.skipped = True
        return result

    spans = list(plan.spans)
    if not spans and force:
        # Nothing is missing, but the caller insisted: treat the whole window
        # as one span so the re-download still happens.
        spans = [_span(plan.window_start, plan.window_end, plan.bars_expected)]
    if not spans:
        result.skipped = True
        return result

    kwargs = {"base_url": base_url} if base_url else {}
    try:
        with BinanceMarketData(**kwargs) as client:  # type: ignore[arg-type]
            for index, span in enumerate(spans[:max_spans], start=1):
                start, stop = _widen(span.start, span.end, interval)
                if progress is not None:
                    progress(index, min(len(spans), max_spans), start, stop)
                frame = client.fetch_klines(symbol, interval=interval, start=start, end=stop)
                if frame.is_empty():
                    continue
                written = write_bars(frame, symbol, root=root, interval=interval)
                result.fetched_bars += frame.height
                result.rows_added += written.rows_added
                result.rows_updated += written.rows_updated
                result.spans_done += 1
    except BinanceError as exc:
        result.error = str(exc)
    except Exception as exc:  # network/DNS/etc: report, do not crash the caller
        result.error = f"{type(exc).__name__}: {exc}"

    return result


def _span(start: datetime, end: datetime, missing: int) -> GapSpan:
    return GapSpan(start, end, missing)


@dataclass
class BackfillBatchResult:
    results: list[BackfillResult] = field(default_factory=list)

    @property
    def total_added(self) -> int:
        return sum(r.rows_added for r in self.results)

    def as_dict(self) -> dict[str, object]:
        return {
            "symbols": [r.as_dict() for r in self.results],
            "total_added": self.total_added,
            "any_skipped": any(r.skipped for r in self.results),
        }
