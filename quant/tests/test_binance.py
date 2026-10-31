from __future__ import annotations

import pytest

from quant.data.binance import BinanceMarketData, empty_bars


def _row(open_ms: int = 1767225600000) -> list:
    return [
        open_ms,
        "100.10000000",
        "101.20000000",
        "99.90000000",
        "100.90000000",
        "12.50000000",
        open_ms + 59_999,
        "1260.00000000",
        42,
        "6.00000000",
        "600.00000000",
        "0",
    ]


def test_to_frame_drops_ignore_field_and_casts_types():
    df = BinanceMarketData.to_frame([_row()])

    assert df.height == 1
    assert list(df.columns) == [
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
    ]
    assert df.schema["open"] == df.schema["close"]
    assert df["open"][0] == 100.1
    assert df["trades"][0] == 42
    assert str(df["open_time"][0]) == "2026-01-01 00:00:00+00:00"


def test_to_frame_empty():
    df = BinanceMarketData.to_frame([])
    assert df.is_empty()
    assert df.columns == empty_bars().columns


def test_invalid_interval_rejected():
    client = BinanceMarketData()
    try:
        with pytest.raises(ValueError, match="unsupported interval"):
            client.klines("BTCUSDT", interval="2m")
    finally:
        client.close()
