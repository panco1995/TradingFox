"""Binance websocket market streams: URL building and message parsing.

Kept separate from the collector so parsing can be unit tested without a socket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

WS_MARKET_BASE = "wss://data-stream.binance.vision"


@dataclass(frozen=True, slots=True)
class KlineBar:
    symbol: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int
    taker_buy_base: float
    taker_buy_quote: float
    is_final: bool

    def as_row(self) -> dict[str, object]:
        return {
            "open_time": self.open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "close_time": self.close_time,
            "quote_volume": self.quote_volume,
            "trades": self.trades,
            "taker_buy_base": self.taker_buy_base,
            "taker_buy_quote": self.taker_buy_quote,
        }


def stream_name(symbol: str, interval: str) -> str:
    return f"{symbol.lower()}@kline_{interval}"


def stream_url(symbols: list[str], interval: str, base: str = WS_MARKET_BASE) -> str:
    """Combined stream URL: one connection for all symbols."""
    names = "/".join(stream_name(s, interval) for s in symbols)
    return f"{base.rstrip('/')}/stream?streams={names}"


def _ms_to_datetime(ms: int) -> datetime:
    # exact conversion, avoids float drift on 13-digit timestamps
    return datetime.fromtimestamp(ms // 1000, tz=UTC).replace(microsecond=(ms % 1000) * 1000)


def parse_kline(message: dict) -> KlineBar | None:
    """Parse a websocket message into a bar.

    Accepts both the combined-stream envelope ({"stream": ..., "data": {...}})
    and a raw single-stream payload. Returns None for anything that is not a
    kline event (subscription acks, other stream types).
    """
    data = message.get("data", message)
    if not isinstance(data, dict) or data.get("e") != "kline":
        return None

    k = data.get("k")
    if not isinstance(k, dict):
        return None

    try:
        return KlineBar(
            symbol=str(k["s"]),
            open_time=_ms_to_datetime(int(k["t"])),
            close_time=_ms_to_datetime(int(k["T"])),
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            quote_volume=float(k["q"]),
            trades=int(k["n"]),
            taker_buy_base=float(k["V"]),
            taker_buy_quote=float(k["Q"]),
            is_final=bool(k["x"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
