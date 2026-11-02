"""Which symbols the collector should stream.

The list lives in a small JSON file under the data root so the admin UI,
the CLI and a running collector all see the same thing. A collector can watch
the file and pick up additions without a restart.

Only symbols the exchange actually offers in `TRADING` state are stored: a typo
must fail at add time rather than silently producing an empty chart later.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from quant.config import DEFAULT_INTERVAL, data_root
from quant.data.binance import BinanceError, BinanceMarketData

SUBSCRIPTIONS_FILENAME = "symbols.json"
#: Trading pairs the collector watches out of the box.
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")


def subscriptions_path(root: Path | None = None) -> Path:
    return (root or data_root()) / "meta" / SUBSCRIPTIONS_FILENAME


def normalize_symbol(value: str) -> str:
    """Reject anything that is not a plausible exchange symbol."""
    symbol = value.strip().upper()
    if not symbol:
        raise ValueError("交易对不能为空")
    if not symbol.isalnum() or not symbol.isascii():
        raise ValueError("交易对只能包含字母和数字，例如 BTCUSDT")
    if not 5 <= len(symbol) <= 24:
        raise ValueError("交易对长度需要在 5 到 24 个字符之间")
    return symbol


def validate_symbol(symbol: str, base_url: str | None = None) -> dict[str, object]:
    """Ask the exchange whether `symbol` is tradable.

    Raises ValueError with a user-facing message when it is not.
    """
    symbol = normalize_symbol(symbol)
    kwargs = {"base_url": base_url} if base_url else {}
    try:
        with BinanceMarketData(**kwargs) as client:  # type: ignore[arg-type]
            specs = client.symbol_specs([symbol])
    except BinanceError as exc:
        if "-1121" in str(exc):
            raise ValueError(f"交易所没有 {symbol} 这个交易对") from exc
        raise ValueError(f"无法验证 {symbol}: {exc}") from exc

    if specs.is_empty():
        raise ValueError(f"交易所没有 {symbol} 这个交易对")

    row = specs.row(0, named=True)
    status = str(row.get("status") or "")
    if status != "TRADING":
        raise ValueError(f"{symbol} 当前状态是 {status}，不可交易")
    return row


def read_subscriptions(root: Path | None = None) -> list[str]:
    """Stored symbols, falling back to the defaults when nothing is saved."""
    path = subscriptions_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(DEFAULT_SYMBOLS)

    symbols = payload.get("symbols") if isinstance(payload, dict) else payload
    if not isinstance(symbols, list):
        return list(DEFAULT_SYMBOLS)
    cleaned: list[str] = []
    for item in symbols:
        try:
            cleaned.append(normalize_symbol(str(item)))
        except ValueError:
            continue
    return cleaned or list(DEFAULT_SYMBOLS)


def _write(symbols: list[str], root: Path | None, updated_by: str | None = None) -> Path:
    path = subscriptions_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "symbols": symbols,
        "interval": DEFAULT_INTERVAL,
        "updated_at": datetime.now(UTC).isoformat(),
        "updated_by": updated_by,
    }
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def add_symbol(
    symbol: str,
    root: Path | None = None,
    base_url: str | None = None,
    updated_by: str | None = None,
) -> dict[str, object]:
    """Validate with the exchange, then persist. Returns the stored record."""
    symbol = normalize_symbol(symbol)
    specs = validate_symbol(symbol, base_url=base_url)

    current = read_subscriptions(root)
    if symbol in current:
        raise ValueError(f"{symbol} 已经在采集列表里")
    current.append(symbol)
    _write(current, root, updated_by)

    return {
        "symbol": symbol,
        "base_asset": specs.get("base_asset"),
        "quote_asset": specs.get("quote_asset"),
        "status": specs.get("status"),
        "symbols": current,
    }


def remove_symbol(
    symbol: str, root: Path | None = None, updated_by: str | None = None
) -> list[str]:
    """Stop collecting a symbol. Historical Parquet files are left in place."""
    symbol = normalize_symbol(symbol)
    current = read_subscriptions(root)
    if symbol not in current:
        raise ValueError(f"{symbol} 不在采集列表里")
    if len(current) == 1:
        raise ValueError("至少要保留一个交易对")
    remaining = [item for item in current if item != symbol]
    _write(remaining, root, updated_by)
    return remaining
