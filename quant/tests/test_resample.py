from datetime import UTC, datetime, timedelta

import polars as pl

from quant.data.resample import (
    SUPPORTED_INTERVALS,
    bucket_start,
    expected_bars,
    resample,
)


def test_bucket_start_is_calendar_aligned():
    dt = datetime(2026, 1, 15, 13, 47, tzinfo=UTC)  # a Thursday

    assert bucket_start(dt, "15m") == datetime(2026, 1, 15, 13, 45, tzinfo=UTC)
    assert bucket_start(dt, "4h") == datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    assert bucket_start(dt, "1d") == datetime(2026, 1, 15, tzinfo=UTC)
    assert bucket_start(dt, "1w") == datetime(2026, 1, 12, tzinfo=UTC)  # Monday
    assert bucket_start(dt, "1M") == datetime(2026, 1, 1, tzinfo=UTC)


def test_multi_day_buckets_anchor_to_epoch_not_to_the_data():
    # 2026-01-15 is 55 days after 1970-01-01; 3-day buckets start at day 54.
    assert bucket_start(datetime(2026, 1, 15, tzinfo=UTC), "3d") == datetime(
        2026, 1, 13, tzinfo=UTC
    )


def test_expected_bars_follows_calendar():
    assert expected_bars(datetime(2026, 1, 1, tzinfo=UTC), "1M") == 31 * 1_440
    assert expected_bars(datetime(2026, 2, 1, tzinfo=UTC), "1M") == 28 * 1_440
    assert expected_bars(datetime(2026, 1, 5, tzinfo=UTC), "1w") == 7 * 1_440


def test_every_supported_interval_lines_up_with_bucket_start(bars_factory):
    start = datetime(2026, 3, 2, tzinfo=UTC)
    df = bars_factory(1_000, start=start)

    for interval in SUPPORTED_INTERVALS:
        grouped = resample(df, interval)
        starts = grouped["open_time"].to_list()
        assert starts, interval
        for value in starts:
            assert bucket_start(value, interval) == value, (interval, value)
        # the trailing bucket is incomplete, everything before it is whole
        assert grouped["closed"].to_list()[:-1] == [True] * (grouped.height - 1), interval


def test_resample_aggregates_ohlcv(bars_factory):
    df = bars_factory(60, start=datetime(2026, 1, 1, tzinfo=UTC))  # one hour
    hourly = resample(df, "1h")

    assert hourly.height == 1
    row = hourly.row(0, named=True)
    assert row["open"] == 100.0
    assert row["close"] == 159.5
    assert row["high"] == 160.0
    assert row["low"] == 99.0
    assert row["volume"] == 60 * 10.0
    assert row["trades"] == 60 * 5
    assert row["bars"] == 60
    assert row["closed"] is True


def test_partial_trailing_bucket_is_not_closed(bars_factory):
    df = bars_factory(90, start=datetime(2026, 1, 1, tzinfo=UTC))
    hourly = resample(df, "1h")

    assert hourly.height == 2
    assert hourly["closed"].to_list() == [True, False]


def test_missing_minutes_mark_the_bucket_open(bars_factory):
    df = bars_factory(60, start=datetime(2026, 1, 1, tzinfo=UTC))
    holed = df.filter(pl.col("open_time") != datetime(2026, 1, 1, 0, 30, tzinfo=UTC))
    hourly = resample(holed, "1h")

    assert hourly.height == 1
    assert hourly["bars"].to_list() == [59]
    assert hourly["closed"].to_list() == [False]


def test_resample_keeps_utc_dtype(bars_factory):
    df = bars_factory(120, start=datetime(2026, 1, 1, tzinfo=UTC))
    weekly = resample(df, "1w")

    assert weekly.schema["open_time"] == pl.Datetime("ms", "UTC")
    assert weekly["open_time"].to_list() == [datetime(2025, 12, 29, tzinfo=UTC)]


def test_empty_frame_keeps_the_schema():
    empty = pl.DataFrame(
        schema={
            "open_time": pl.Datetime("ms", "UTC"),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "close_time": pl.Datetime("ms", "UTC"),
            "quote_volume": pl.Float64,
            "trades": pl.Int64,
            "taker_buy_base": pl.Float64,
            "taker_buy_quote": pl.Float64,
        }
    )
    out = resample(empty, "1d")

    assert out.height == 0
    assert "closed" in out.columns


def test_week_bucket_spans_monday_to_sunday(bars_factory):
    monday = datetime(2026, 3, 2, tzinfo=UTC)
    df = bars_factory(7 * 1_440, start=monday, step_minutes=1)
    weekly = resample(df, "1w")

    assert weekly.height == 1
    assert weekly["open_time"].to_list() == [monday]
    assert weekly["bars"].to_list() == [7 * 1_440]
    assert weekly["closed"].to_list() == [True]
    assert weekly["close_time"].to_list() == [
        monday + timedelta(weeks=1) - timedelta(milliseconds=1)
    ]
