from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from quant.data.quality import check_bars


def test_clean_series(bars_factory):
    report = check_bars(bars_factory(10), interval="1m")
    assert report.rows == 10
    assert report.ok
    assert report.duplicates == 0
    assert report.gaps == []
    assert report.ohlc_violations == 0


def test_detects_gap(bars_factory):
    df = bars_factory(6)
    holed = pl.concat([df.head(2), df.tail(3)])  # remove bar index 2

    report = check_bars(holed, interval="1m")
    assert not report.ok
    assert len(report.gaps) == 1
    assert report.missing_bars == 1
    assert report.gaps[0].after == df["open_time"][1]
    assert report.gaps[0].before == df["open_time"][3]


def test_detects_large_gap_in_bars(bars_factory):
    df = bars_factory(2)
    tail = bars_factory(2, start=datetime(2026, 1, 1, 1, tzinfo=UTC))
    report = check_bars(pl.concat([df, tail]), interval="1m")
    assert report.missing_bars == 58


def test_detects_duplicates(bars_factory):
    df = bars_factory(3)
    dup = pl.concat([df, df.head(1)])
    report = check_bars(dup, interval="1m")
    assert report.duplicates == 1


def test_detects_ohlc_violation(bars_factory):
    df = bars_factory(3).with_columns(pl.lit(1.0).alias("high"))
    report = check_bars(df, interval="1m")
    assert report.ohlc_violations == 3


def test_empty():
    report = check_bars(pl.DataFrame())
    assert report.rows == 0
    assert report.ok
