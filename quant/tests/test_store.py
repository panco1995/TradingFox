from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from quant.data.store import (
    latest_open_time,
    list_symbols,
    read_bars,
    symbol_coverage,
    symbol_dir,
    write_bars,
)


def test_roundtrip(bars_factory, tmp_path):
    df = bars_factory(3)

    result = write_bars(df, "BTCUSDT", root=tmp_path)
    assert result.rows_added == 3
    assert result.rows_updated == 0
    assert len(result.files) == 1

    back = read_bars("BTCUSDT", root=tmp_path)
    assert back.height == 3
    assert back["close"].to_list() == df["close"].to_list()
    assert back.schema["open_time"] == df.schema["open_time"]


def test_rewrite_is_idempotent(bars_factory, tmp_path):
    df = bars_factory(3)
    write_bars(df, "BTCUSDT", root=tmp_path)
    result = write_bars(df, "BTCUSDT", root=tmp_path)

    assert result.rows_added == 0
    assert result.rows_updated == 3
    assert read_bars("BTCUSDT", root=tmp_path).height == 3


def test_new_values_win(bars_factory, tmp_path):
    df = bars_factory(3)
    write_bars(df, "BTCUSDT", root=tmp_path)

    corrected = df.with_columns(pl.lit(999.0).alias("close"))
    write_bars(corrected, "BTCUSDT", root=tmp_path)

    back = read_bars("BTCUSDT", root=tmp_path)
    assert back.height == 3
    assert back["close"].to_list() == [999.0, 999.0, 999.0]


def test_partial_overlap(bars_factory, tmp_path):
    write_bars(bars_factory(2), "BTCUSDT", root=tmp_path)
    # starts at the 2nd existing bar and adds one new bar
    df = bars_factory(3)[1:]
    result = write_bars(df, "BTCUSDT", root=tmp_path)

    assert result.rows_added == 1
    assert result.rows_updated == 1
    assert read_bars("BTCUSDT", root=tmp_path).height == 3


def test_month_partitioning(bars_factory, tmp_path):
    df = bars_factory(60 * 24 * 40)  # 40 days -> two calendar months
    result = write_bars(df, "BTCUSDT", root=tmp_path)

    assert len(result.files) == 2
    assert all(p.suffix == ".parquet" for p in result.files)
    assert read_bars("BTCUSDT", root=tmp_path).height == df.height


def test_read_range(bars_factory, tmp_path):
    df = bars_factory(10)
    write_bars(df, "BTCUSDT", root=tmp_path)

    start = df["open_time"][3]
    back = read_bars("BTCUSDT", start=start, root=tmp_path)
    assert back.height == 7
    assert back["open_time"].min() == start


def test_latest_and_listing(bars_factory, tmp_path):
    assert latest_open_time("BTCUSDT", root=tmp_path) is None
    assert list_symbols(root=tmp_path) == []

    df = bars_factory(2)
    write_bars(df, "BTCUSDT", root=tmp_path)
    write_bars(df, "ETHUSDT", root=tmp_path)

    assert latest_open_time("BTCUSDT", root=tmp_path) == df["open_time"].max()
    assert list_symbols(root=tmp_path) == ["BTCUSDT", "ETHUSDT"]
    assert symbol_dir("BTCUSDT", root=tmp_path).exists()


def test_symbol_coverage_reports_freshness(bars_factory, tmp_path):
    write_bars(bars_factory(3), "BTCUSDT", root=tmp_path)
    write_bars(bars_factory(5), "ETHUSDT", root=tmp_path)

    rows = {row["symbol"]: row for row in symbol_coverage(root=tmp_path)}

    assert set(rows) == {"BTCUSDT", "ETHUSDT"}
    assert rows["BTCUSDT"]["bars"] == 3
    assert rows["ETHUSDT"]["bars"] == 5
    assert rows["BTCUSDT"]["first"] == datetime(2026, 1, 1, tzinfo=UTC)
    assert rows["BTCUSDT"]["last"] == datetime(2026, 1, 1, 0, 2, tzinfo=UTC)
    assert rows["BTCUSDT"]["bytes"] > 0
    assert rows["BTCUSDT"]["files"] == 1


def test_symbol_coverage_reports_latest_close(bars_factory, tmp_path):
    df = bars_factory(4)
    write_bars(df, "BTCUSDT", root=tmp_path)

    row = symbol_coverage(root=tmp_path)[0]

    # The newest bar is the last row, not the first one in the file.
    assert row["close"] == pytest.approx(float(df["close"][-1]))
    assert row["last"] == df["open_time"].max()


def test_symbol_coverage_is_empty_without_data(tmp_path):
    assert symbol_coverage(root=tmp_path) == []


def test_missing_column_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="missing bar columns"):
        write_bars(pl.DataFrame({"open_time": []}), "BTCUSDT", root=tmp_path)
