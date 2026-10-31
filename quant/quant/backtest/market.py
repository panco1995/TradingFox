"""Aligned multi-symbol market data for the backtest loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl

from quant.data.store import read_bars

_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


@dataclass
class MarketData:
    """Column-oriented bars, one row per timestamp, all symbols aligned.

    Crypto 1m bars are aligned in practice; symbols with missing bars at a
    timestamp are simply NaN there and the engine skips them.
    """

    symbols: list[str]
    times_ms: np.ndarray
    open: dict[str, np.ndarray]
    high: dict[str, np.ndarray]
    low: dict[str, np.ndarray]
    close: dict[str, np.ndarray]
    volume: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.times_ms)

    def bar(self, symbol: str, i: int):
        return (
            self.open[symbol][i],
            self.high[symbol][i],
            self.low[symbol][i],
            self.close[symbol][i],
            self.volume[symbol][i],
        )

    def valid(self, symbol: str, i: int) -> bool:
        return not np.isnan(self.close[symbol][i])


def load_market(
    symbols: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
    root: Path | None = None,
    interval: str = "1m",
) -> MarketData:
    if not symbols:
        raise ValueError("no symbols")

    frames: dict[str, pl.DataFrame] = {}
    for symbol in symbols:
        frame = read_bars(symbol, start=start, end=end, root=root, interval=interval)
        if frame.is_empty():
            raise ValueError(f"no stored bars for {symbol}, run `quant fetch` first")
        frames[symbol] = frame.select(["open_time", *_PRICE_COLUMNS])

    base = frames[symbols[0]].rename({c: f"{symbols[0]}|{c}" for c in _PRICE_COLUMNS})
    for symbol in symbols[1:]:
        other = frames[symbol].rename({c: f"{symbol}|{c}" for c in _PRICE_COLUMNS})
        base = base.join(other, on="open_time", how="inner")
    base = base.sort("open_time")

    if base.is_empty():
        raise ValueError("symbols share no common timestamps")

    data = MarketData(
        symbols=symbols,
        times_ms=base["open_time"].dt.epoch("ms").to_numpy(),
        open={s: base[f"{s}|open"].to_numpy().astype(float) for s in symbols},
        high={s: base[f"{s}|high"].to_numpy().astype(float) for s in symbols},
        low={s: base[f"{s}|low"].to_numpy().astype(float) for s in symbols},
        close={s: base[f"{s}|close"].to_numpy().astype(float) for s in symbols},
        volume={s: base[f"{s}|volume"].to_numpy().astype(float) for s in symbols},
    )
    return data
