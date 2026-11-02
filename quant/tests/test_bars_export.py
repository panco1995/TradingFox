from datetime import UTC, datetime

from quant.cli import bars_document


def test_bars_document_keeps_ohlcv_and_utc(bars_factory):
    df = bars_factory(2, start=datetime(2026, 11, 1, tzinfo=UTC))
    doc = bars_document(df, symbol="BTCUSDT", interval="1m", start=None, end=None, limit=10)

    assert doc["count"] == 2
    assert doc["truncated"] is False
    assert doc["bars"][0]["t"] == "2026-11-01T00:00:00+00:00"
    assert doc["bars"][0]["o"] == 100.0
    assert doc["bars"][0]["h"] == 101.0
    assert doc["bars"][0]["l"] == 99.0
    assert doc["bars"][0]["c"] == 100.5
    assert doc["bars"][1]["t"] == "2026-11-01T00:01:00+00:00"


def test_bars_document_keeps_the_latest_rows(bars_factory):
    df = bars_factory(5)
    doc = bars_document(df, symbol="BTCUSDT", interval="1m", start=None, end=None, limit=2)

    assert doc["truncated"] is True
    assert doc["count"] == 2
    assert [bar["c"] for bar in doc["bars"]] == [103.5, 104.5]
