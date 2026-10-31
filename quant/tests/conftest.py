from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from quant.data.binance import BAR_SCHEMA


def make_bars(
    count: int,
    start: datetime | None = None,
    step_minutes: int = 1,
    base_price: float = 100.0,
) -> pl.DataFrame:
    start = start or datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(count):
        ts = start + timedelta(minutes=i * step_minutes)
        price = base_price + i
        rows.append(
            {
                "open_time": ts,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + 0.5,
                "volume": 10.0,
                "close_time": ts + timedelta(minutes=step_minutes) - timedelta(milliseconds=1),
                "quote_volume": price * 10,
                "trades": 5,
                "taker_buy_base": 5.0,
                "taker_buy_quote": price * 5,
            }
        )
    return pl.DataFrame(rows, schema=BAR_SCHEMA)


@pytest.fixture
def bars_factory():
    return make_bars
