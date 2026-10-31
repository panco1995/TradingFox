from __future__ import annotations

import polars as pl

from quant.data.store import latest_open_time, list_symbols, read_bars, symbol_dir, write_bars


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


def test_missing_column_rejected(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="missing bar columns"):
        write_bars(pl.DataFrame({"open_time": []}), "BTCUSDT", root=tmp_path)
