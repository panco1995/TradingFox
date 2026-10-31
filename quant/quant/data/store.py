"""Parquet-backed bar storage.

Layout (hive-style partitions, one file per symbol-month):

    data/raw/klines/exchange=BINANCE/type=spot/interval=1m/symbol=BTCUSDT/2026-10.parquet

Why this shape:
  * one file per month keeps file counts low while still allowing pruning;
  * symbols are separate directories, so we never rewrite other symbols' data;
  * writes are atomic (tmp file + rename) and serialised per symbol with a
    file lock, so a crash mid-write cannot corrupt an existing month.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import polars as pl

from quant.config import DEFAULT_EXCHANGE, DEFAULT_INTERVAL, DEFAULT_MARKET_TYPE, data_root
from quant.data.binance import BAR_COLUMNS, BAR_SCHEMA, to_ms


@dataclass
class WriteResult:
    symbol: str
    rows_in: int = 0
    rows_added: int = 0
    rows_updated: int = 0
    files: list[Path] = field(default_factory=list)

    @property
    def rows_total(self) -> int:
        return self.rows_added + self.rows_updated


def symbol_dir(
    symbol: str,
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> Path:
    root = root or data_root()
    return (
        root
        / "raw"
        / "klines"
        / f"exchange={exchange}"
        / f"type={market_type}"
        / f"interval={interval}"
        / f"symbol={symbol}"
    )


def bar_path(
    symbol: str,
    month: str,
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> Path:
    return symbol_dir(symbol, root, interval, exchange, market_type) / f"{month}.parquet"


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _normalise(df: pl.DataFrame) -> pl.DataFrame:
    missing = [c for c in BAR_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing bar columns: {missing}")
    return df.select(BAR_COLUMNS).cast(BAR_SCHEMA)  # type: ignore[arg-type]


def _read_month(path: Path) -> pl.DataFrame:
    df = pl.read_parquet(path)
    return _normalise(df)


def _atomic_write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    try:
        df.write_parquet(tmp, compression="zstd")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def write_bars(
    df: pl.DataFrame,
    symbol: str,
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> WriteResult:
    """Merge bars into storage. Idempotent: re-running with overlapping data
    keeps the newest version of each bar and never duplicates rows.
    """
    root = root or data_root()
    result = WriteResult(symbol=symbol, rows_in=df.height)
    df = _normalise(df)
    if df.is_empty():
        return result

    with _file_lock(root / ".locks" / f"{exchange}_{market_type}_{interval}_{symbol}.lock"):
        for (month,), chunk in df.group_by(
            pl.col("open_time").dt.strftime("%Y-%m").alias("_month"), maintain_order=True
        ):
            path = bar_path(symbol, month, root, interval, exchange, market_type)
            existing = _read_month(path) if path.exists() else None

            if existing is None or existing.is_empty():
                merged = chunk.select(BAR_COLUMNS)
                result.rows_added += merged.height
            else:
                before = set(existing["open_time"].to_list())
                merged = pl.concat([existing, chunk.select(BAR_COLUMNS)], how="vertical")
                merged = (
                    merged.unique(subset=["open_time"], keep="last")
                    .sort("open_time")
                    .cast(BAR_SCHEMA)  # type: ignore[arg-type]
                )
                new_keys = set(merged["open_time"].to_list()) - before
                result.rows_added += len(new_keys)
                result.rows_updated += chunk.height - len(new_keys)

            _atomic_write(merged, path)
            result.files.append(path)

    return result


def read_bars(
    symbol: str,
    start: datetime | int | None = None,
    end: datetime | int | None = None,
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> pl.DataFrame:
    folder = symbol_dir(symbol, root, interval, exchange, market_type)
    files = sorted(folder.glob("*.parquet"))
    if not files:
        return pl.DataFrame(schema=BAR_SCHEMA)

    lazy = pl.scan_parquet([str(p) for p in files])
    start_ms, end_ms = to_ms(start), to_ms(end)
    if start_ms is not None:
        lazy = lazy.filter(pl.col("open_time").dt.epoch("ms") >= start_ms)
    if end_ms is not None:
        lazy = lazy.filter(pl.col("open_time").dt.epoch("ms") <= end_ms)
    return lazy.collect().sort("open_time")


def latest_open_time(
    symbol: str,
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> datetime | None:
    """Last stored bar timestamp - used for incremental backfill."""
    folder = symbol_dir(symbol, root, interval, exchange, market_type)
    files = sorted(folder.glob("*.parquet"))
    if not files:
        return None
    df = pl.read_parquet(files[-1], columns=["open_time"])
    if df.is_empty():
        return None
    return df["open_time"].max()


def list_symbols(
    root: Path | None = None,
    interval: str = DEFAULT_INTERVAL,
    exchange: str = DEFAULT_EXCHANGE,
    market_type: str = DEFAULT_MARKET_TYPE,
) -> list[str]:
    folder = (
        (root or data_root())
        / "raw"
        / "klines"
        / f"exchange={exchange}"
        / f"type={market_type}"
        / f"interval={interval}"
    )
    if not folder.exists():
        return []
    return sorted(p.name.split("=", 1)[1] for p in folder.glob("symbol=*") if p.is_dir())
