"""Derive higher-timeframe klines from the stored 1-minute bars.

Only 1m data is collected from the exchange; every other interval is computed
here so there is a single source of truth and no chance of the two sets
disagreeing. Two rules matter:

  * bucket boundaries are deterministic and calendar-correct: fixed intervals
    count from the Unix epoch, a week starts Monday 00:00 UTC, a month starts
    on the 1st. They never depend on where the loaded slice happens to begin;
  * a bucket that does not contain a full complement of 1m bars is marked
    ``closed = False``, so a still-forming bar is not presented as finished.
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta

import polars as pl

from quant.data.binance import BAR_SCHEMA
from quant.data.store import read_bars

BASE_INTERVAL = "1m"
EPOCH_ORDINAL = datetime(1970, 1, 1, tzinfo=UTC).toordinal()

#: minutes per bucket; "1M" is absent because its length varies by month
FIXED_MINUTES: dict[str, int] = {
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1_440,
    "3d": 4_320,
    "1w": 10_080,
}

SUPPORTED_INTERVALS: tuple[str, ...] = (*FIXED_MINUTES, "1M")

AGG_OUTPUT_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "bars",
    "closed",
]

_AGGREGATIONS = (
    pl.col("open").first(),
    pl.col("high").max(),
    pl.col("low").min(),
    pl.col("close").last(),
    pl.col("volume").sum(),
    pl.col("close_time").last(),
    pl.col("quote_volume").sum(),
    pl.col("trades").sum(),
    pl.col("taker_buy_base").sum(),
    pl.col("taker_buy_quote").sum(),
    pl.len().cast(pl.UInt32).alias("bars"),
)


def is_aggregate(interval: str) -> bool:
    return interval in SUPPORTED_INTERVALS


def next_month(dt: datetime) -> datetime:
    """First instant of the following calendar month, UTC."""
    year, month = (dt.year + 1, 1) if dt.month == 12 else (dt.year, dt.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)


def expected_bars(bucket: datetime, interval: str) -> int:
    """How many 1m bars a complete bucket must hold."""
    if interval == "1M":
        days = calendar.monthrange(bucket.year, bucket.month)[1]
        return days * 1_440
    return FIXED_MINUTES[interval]


def bucket_start(dt: datetime, interval: str) -> datetime:
    """Floor `dt` onto the bucket that contains it."""
    dt = dt.astimezone(UTC).replace(second=0, microsecond=0)
    if interval == "1M":
        return datetime(dt.year, dt.month, 1, tzinfo=UTC)
    if interval == "1w":
        monday = dt - timedelta(days=dt.weekday())
        return monday.replace(hour=0, minute=0)
    minutes = FIXED_MINUTES[interval]
    if minutes < 1_440:
        midnight = dt.replace(hour=0, minute=0)
        return midnight + timedelta(minutes=(dt.hour * 60 + dt.minute) // minutes * minutes)
    # Multi-day buckets count from 1970-01-01, so they are stable regardless of
    # which rows are loaded.
    days = minutes // 1_440
    offset = (dt.toordinal() - EPOCH_ORDINAL) % days
    midnight = dt.replace(hour=0, minute=0)
    return midnight - timedelta(days=offset)


def _bucket_key(interval: str) -> pl.Expr:
    """A grouping expression whose keys equal `bucket_start` exactly."""
    if interval == "1M":
        return pl.col("open_time").dt.truncate("1mo")
    if interval == "1w":
        return pl.col("open_time").dt.truncate("1w")
    width = FIXED_MINUTES[interval] * 60_000
    epoch_ms = pl.col("open_time").dt.epoch("ms")
    return pl.from_epoch((epoch_ms // width) * width, time_unit="ms").dt.replace_time_zone("UTC")


def resample(df: pl.DataFrame, interval: str) -> pl.DataFrame:
    """Collapse 1m bars into `interval` buckets.

    The result keeps the normal bar columns plus ``bars`` (how many 1m bars
    landed in the bucket) and ``closed`` (whether that is the full count).
    """
    if not is_aggregate(interval):
        raise ValueError(f"unsupported aggregation interval: {interval}")
    if df.is_empty():
        return pl.DataFrame(
            schema={**BAR_SCHEMA, "bars": pl.UInt32, "closed": pl.Boolean}  # type: ignore[arg-type]
        )

    grouped = (
        df.sort("open_time")
        .group_by(_bucket_key(interval).alias("open_time"), maintain_order=True)
        .agg(*_AGGREGATIONS)
    )
    expected = pl.Series(
        "expected",
        [expected_bars(row["open_time"], interval) for row in grouped.iter_rows(named=True)],
        dtype=pl.Int64,
    )
    return grouped.with_columns((pl.col("bars").cast(pl.Int64) >= expected).alias("closed")).select(
        AGG_OUTPUT_COLUMNS
    )


def load_bars(
    symbol: str,
    interval: str = BASE_INTERVAL,
    start: datetime | None = None,
    end: datetime | None = None,
    root=None,
) -> pl.DataFrame:
    """Read bars at any supported interval, aggregating 1m data when needed."""
    if not is_aggregate(interval):
        return read_bars(symbol, start=start, end=end, root=root, interval=interval)
    # A bucket that starts before `start` still belongs to the answer, otherwise
    # the first bar would silently look partial.
    if start is not None:
        start = bucket_start(start, interval)
    base = read_bars(symbol, start=start, end=end, root=root, interval=BASE_INTERVAL)
    return resample(base, interval)
