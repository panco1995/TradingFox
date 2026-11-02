from __future__ import annotations

import json

import pytest

from quant.data import subscriptions
from quant.data.subscriptions import (
    DEFAULT_SYMBOLS,
    add_symbol,
    normalize_symbol,
    read_subscriptions,
    remove_symbol,
    subscriptions_path,
)


@pytest.fixture
def fake_exchange(monkeypatch):
    """Pretend the exchange lists exactly these symbols as TRADING."""
    tradable = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "HALTEDUSDT"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def symbol_specs(self, symbols=None):
            import polars as pl

            from quant.data.binance import BinanceError

            wanted = [s.upper() for s in (symbols or [])]
            for symbol in wanted:
                if symbol not in tradable:
                    raise BinanceError(
                        '400 /api/v3/exchangeInfo: {"code":-1121,"msg":"Invalid symbol."}'
                    )
            return pl.DataFrame(
                [
                    {
                        "symbol": s,
                        "base_asset": s.replace("USDT", ""),
                        "quote_asset": "USDT",
                        "status": "BREAK" if s == "HALTEDUSDT" else "TRADING",
                    }
                    for s in wanted
                ]
            )

    monkeypatch.setattr(subscriptions, "BinanceMarketData", FakeClient)
    return tradable


def test_defaults_when_nothing_saved(tmp_path):
    assert read_subscriptions(tmp_path) == list(DEFAULT_SYMBOLS)
    assert not subscriptions_path(tmp_path).exists()


def test_add_persists_valid_symbol(tmp_path, fake_exchange):
    record = add_symbol("solusdt", root=tmp_path, updated_by="user_3")

    assert record["symbol"] == "SOLUSDT"
    assert record["status"] == "TRADING"
    assert read_subscriptions(tmp_path) == [*DEFAULT_SYMBOLS, "SOLUSDT"]

    saved = json.loads(subscriptions_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["updated_by"] == "user_3"
    assert saved["symbols"] == [*DEFAULT_SYMBOLS, "SOLUSDT"]


def test_unknown_symbol_is_rejected_and_nothing_is_written(tmp_path, fake_exchange):
    with pytest.raises(ValueError, match="交易所没有"):
        add_symbol("FOOBARUSDT", root=tmp_path)

    assert not subscriptions_path(tmp_path).exists()
    assert read_subscriptions(tmp_path) == list(DEFAULT_SYMBOLS)


def test_halted_symbol_is_rejected(tmp_path, fake_exchange):
    with pytest.raises(ValueError, match="不可交易"):
        add_symbol("HALTEDUSDT", root=tmp_path)

    assert not subscriptions_path(tmp_path).exists()


def test_duplicate_is_rejected(tmp_path, fake_exchange):
    with pytest.raises(ValueError, match="已经在采集列表"):
        add_symbol("BTCUSDT", root=tmp_path)


def test_bad_format_is_rejected_before_any_network_call(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not contact the exchange for a malformed symbol")

    monkeypatch.setattr(subscriptions, "BinanceMarketData", boom)

    with pytest.raises(ValueError, match="只能包含字母和数字"):
        add_symbol("BTC-USDT", root=tmp_path)
    with pytest.raises(ValueError, match="长度"):
        add_symbol("A", root=tmp_path)


def test_remove_keeps_history_and_drops_subscription(tmp_path, fake_exchange):
    add_symbol("SOLUSDT", root=tmp_path)

    remaining = remove_symbol("SOLUSDT", root=tmp_path)

    assert remaining == list(DEFAULT_SYMBOLS)
    assert read_subscriptions(tmp_path) == list(DEFAULT_SYMBOLS)


def test_remove_unknown_is_rejected(tmp_path, fake_exchange):
    with pytest.raises(ValueError, match="不在采集列表"):
        remove_symbol("SOLUSDT", root=tmp_path)


def test_cannot_remove_the_last_symbol(tmp_path, fake_exchange):
    subscriptions._write(["BTCUSDT"], tmp_path)

    with pytest.raises(ValueError, match="至少要保留一个"):
        remove_symbol("BTCUSDT", root=tmp_path)


def test_normalize_upcases_and_trims():
    assert normalize_symbol("  solusdt ") == "SOLUSDT"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = subscriptions_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert read_subscriptions(tmp_path) == list(DEFAULT_SYMBOLS)
