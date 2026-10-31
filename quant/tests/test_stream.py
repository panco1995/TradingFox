from __future__ import annotations

from datetime import UTC, datetime

from quant.data.stream import _ms_to_datetime, parse_kline, stream_name, stream_url


def _kline_event(
    symbol: str = "BTCUSDT",
    is_final: bool = True,
    open_ms: int = 1793427780000,
) -> dict:
    return {
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {
            "e": "kline",
            "E": open_ms + 1000,
            "s": symbol,
            "k": {
                "t": open_ms,
                "T": open_ms + 59_999,
                "s": symbol,
                "i": "1m",
                "f": 100,
                "L": 200,
                "o": "77000.00",
                "c": "77296.00",
                "h": "77350.00",
                "l": "76990.00",
                "v": "12.345",
                "n": 321,
                "x": is_final,
                "q": "951234.56",
                "V": "6.111",
                "Q": "471000.00",
                "B": "123456",
            },
        },
    }


def test_parse_combined_stream():
    bar = parse_kline(_kline_event())

    assert bar is not None
    assert bar.symbol == "BTCUSDT"
    assert bar.open == 77000.0
    assert bar.close == 77296.0
    assert bar.trades == 321
    assert bar.is_final is True
    assert bar.open_time == datetime(2026, 10, 31, 6, 23, tzinfo=UTC)
    assert (bar.close_time - bar.open_time).total_seconds() == 59.999


def test_parse_raw_payload():
    raw = _kline_event()["data"]
    bar = parse_kline(raw)
    assert bar is not None
    assert bar.symbol == "BTCUSDT"


def test_parse_not_final():
    bar = parse_kline(_kline_event(is_final=False))
    assert bar is not None
    assert bar.is_final is False


def test_parse_ignores_non_kline_messages():
    assert parse_kline({"result": None, "id": 1}) is None
    assert parse_kline({"e": "aggTrade", "s": "BTCUSDT"}) is None
    assert parse_kline({}) is None


def test_parse_malformed_returns_none():
    broken = _kline_event()
    del broken["data"]["k"]["c"]
    assert parse_kline(broken) is None


def test_ms_conversion_keeps_milliseconds():
    assert _ms_to_datetime(1793427780999) == datetime(
        2026, 10, 31, 6, 23, 0, 999_000, tzinfo=UTC
    )


def test_stream_names():
    assert stream_name("BTCUSDT", "1m") == "btcusdt@kline_1m"
    url = stream_url(["BTCUSDT", "ETHUSDT"], "1m")
    assert url.startswith("wss://")
    assert "btcusdt@kline_1m/ethusdt@kline_1m" in url
