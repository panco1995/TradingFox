"""Binance public market data client.

Only public endpoints are used here (no API key needed):
  - /api/v3/ping
  - /api/v3/time
  - /api/v3/exchangeInfo
  - /api/v3/klines

Design notes:
  * Requests go through a single global throttle, because Binance rate limits
    are per IP, not per endpoint.
  * 429 / 418 are handled explicitly: honour Retry-After, then back off.
  * Only *closed* klines are returned, so downstream code never sees a bar
    that is still forming.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import polars as pl

from quant.config import BINANCE_MARKET_BASE

log = logging.getLogger(__name__)

INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}

# Normalised bar schema. The raw "ignore" field is dropped on purpose.
BAR_SCHEMA: dict[str, pl.DataType] = {
    "open_time": pl.Datetime("ms", "UTC"),
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "close_time": pl.Datetime("ms", "UTC"),
    "quote_volume": pl.Float64,
    "trades": pl.Int64,
    "taker_buy_base": pl.Float64,
    "taker_buy_quote": pl.Float64,
}

BAR_COLUMNS: list[str] = list(BAR_SCHEMA)

_RAW_SCHEMA: list[tuple[str, pl.DataType]] = [
    ("open_time", pl.Int64),
    ("open", pl.Utf8),
    ("high", pl.Utf8),
    ("low", pl.Utf8),
    ("close", pl.Utf8),
    ("volume", pl.Utf8),
    ("close_time", pl.Int64),
    ("quote_volume", pl.Utf8),
    ("trades", pl.Int64),
    ("taker_buy_base", pl.Utf8),
    ("taker_buy_quote", pl.Utf8),
]

_FLOAT_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "taker_buy_base",
    "taker_buy_quote",
)


def empty_bars() -> pl.DataFrame:
    return pl.DataFrame(schema=BAR_SCHEMA)


def to_ms(value: datetime | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value.timestamp() * 1000)


class BinanceError(RuntimeError):
    pass


class BinanceMarketData:
    """Thin, dependency-light wrapper over the public Binance REST API."""

    def __init__(
        self,
        base_url: str = BINANCE_MARKET_BASE,
        timeout: float = 15.0,
        min_interval: float = 0.12,
        max_retries: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_request = 0.0
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": "quant/0.1 (+https://github.com/)"},
        )

    # ---------------------------------------------------------------- plumbing

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BinanceMarketData:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, path: str, **params: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get(path, params=params)
            except httpx.HTTPError as exc:  # network hiccup, retry
                last_error = exc
                backoff = min(2.0**attempt, 30.0)
                log.warning("request failed (%s), retry in %.1fs", exc, backoff)
                time.sleep(backoff)
                continue

            if resp.status_code in (429, 418):
                retry_after = float(resp.headers.get("Retry-After", "5"))
                log.warning("rate limited (%s), sleeping %.0fs", resp.status_code, retry_after)
                time.sleep(retry_after)
                last_error = BinanceError(f"rate limited: {resp.status_code}")
                continue

            if resp.status_code >= 500:
                backoff = min(2.0**attempt, 30.0)
                log.warning("server error %s, retry in %.1fs", resp.status_code, backoff)
                time.sleep(backoff)
                last_error = BinanceError(f"server error: {resp.status_code}")
                continue

            if resp.status_code >= 400:
                raise BinanceError(f"{resp.status_code} {path}: {resp.text[:300]}")

            return resp.json()

        raise BinanceError(f"giving up on {path} after {self.max_retries} attempts: {last_error}")

    # ---------------------------------------------------------------- endpoints

    def ping(self) -> bool:
        self._get("/api/v3/ping")
        return True

    def server_time(self) -> int:
        return int(self._get("/api/v3/time")["serverTime"])

    def clock_drift_ms(self) -> int:
        """Local clock minus exchange clock. Keep this small (< 1000 ms)."""
        before = int(time.time() * 1000)
        server = self.server_time()
        after = int(time.time() * 1000)
        return (before + after) // 2 - server

    def exchange_info(self) -> dict[str, Any]:
        return self._get("/api/v3/exchangeInfo")

    def symbol_specs(self, symbols: list[str] | None = None) -> pl.DataFrame:
        """Trading rules needed to build valid orders (tick size, step size...)."""
        params = {}
        if symbols:
            params["symbols"] = "[" + ",".join(f'"{s}"' for s in symbols) + "]"

        rows = []
        for item in self._get("/api/v3/exchangeInfo", **params)["symbols"]:
            filters = {f["filterType"]: f for f in item.get("filters", [])}
            price_filter = filters.get("PRICE_FILTER", {})
            lot_size = filters.get("LOT_SIZE", {})
            notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
            rows.append(
                {
                    "symbol": item["symbol"],
                    "base_asset": item["baseAsset"],
                    "quote_asset": item["quoteAsset"],
                    "status": item["status"],
                    "tick_size": price_filter.get("tickSize"),
                    "min_price": price_filter.get("minPrice"),
                    "max_price": price_filter.get("maxPrice"),
                    "step_size": lot_size.get("stepSize"),
                    "min_qty": lot_size.get("minQty"),
                    "max_qty": lot_size.get("maxQty"),
                    "min_notional": notional.get("minNotional") or notional.get("notional"),
                }
            )
        return pl.DataFrame(rows)

    def klines(
        self,
        symbol: str,
        interval: str = "1m",
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list[Any]]:
        if interval not in INTERVAL_MS:
            raise ValueError(f"unsupported interval: {interval}")
        limit = max(1, min(limit, 1000))
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._get("/api/v3/klines", **params)

    # ------------------------------------------------------------------ frames

    @staticmethod
    def to_frame(rows: list[list[Any]]) -> pl.DataFrame:
        if not rows:
            return empty_bars()

        trimmed = [row[: len(_RAW_SCHEMA)] for row in rows]
        raw = pl.DataFrame(trimmed, schema=_RAW_SCHEMA, orient="row")
        return (
            raw.with_columns(
                pl.from_epoch("open_time", time_unit="ms")
                .dt.replace_time_zone("UTC")
                .alias("open_time"),
                pl.from_epoch("close_time", time_unit="ms")
                .dt.replace_time_zone("UTC")
                .alias("close_time"),
                *[pl.col(name).cast(pl.Float64) for name in _FLOAT_COLUMNS],
            )
            .select(BAR_COLUMNS)
            .sort("open_time")
            .cast(BAR_SCHEMA)  # type: ignore[arg-type]
        )

    def iter_klines(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | int | None = None,
        end: datetime | int | None = None,
        limit: int = 1000,
        progress: Callable[[int, pl.DataFrame], None] | None = None,
    ) -> Iterator[pl.DataFrame]:
        """Page through klines. Yields normalised, sorted, closed-only frames."""
        step = INTERVAL_MS[interval]
        cursor = to_ms(start)
        end_ms = to_ms(end)
        now_ms = int(time.time() * 1000)

        if cursor is None:
            # Default: walk backwards from "now" is not supported by the API,
            # so require an explicit start when no end is given.
            raise ValueError("start is required")

        seen_last = -1
        while True:
            rows = self.klines(symbol, interval, start_ms=cursor, end_ms=end_ms, limit=limit)
            if not rows:
                return

            frame = self.to_frame(rows)
            if frame.is_empty():
                return

            # Drop the bar that is still forming.
            frame = frame.filter(pl.col("close_time").dt.epoch("ms") < now_ms)
            if not frame.is_empty():
                if progress is not None:
                    progress(frame.height, frame)
                yield frame

            last_open = int(frame["open_time"].dt.epoch("ms").max() or 0)
            if last_open <= seen_last:
                return
            seen_last = last_open

            cursor = last_open + step
            if end_ms is not None and cursor > end_ms:
                return
            if cursor > now_ms:
                return
            if len(rows) < limit:
                return

    def fetch_klines(
        self,
        symbol: str,
        interval: str = "1m",
        start: datetime | int | None = None,
        end: datetime | int | None = None,
        limit: int = 1000,
        progress: Callable[[int, pl.DataFrame], None] | None = None,
    ) -> pl.DataFrame:
        frames = list(
            self.iter_klines(
                symbol, interval, start=start, end=end, limit=limit, progress=progress
            )
        )
        if not frames:
            return empty_bars()
        df = pl.concat(frames)
        return df.unique(subset=["open_time"], keep="last").sort("open_time")


def summarise_klines(df: pl.DataFrame) -> dict[str, Any]:
    """Small helper used by CLI output and logs."""
    if df.is_empty():
        return {"rows": 0}
    return {
        "rows": df.height,
        "start": df["open_time"].min(),
        "end": df["open_time"].max(),
        "last_close": Decimal(str(df["close"][-1])),
    }
