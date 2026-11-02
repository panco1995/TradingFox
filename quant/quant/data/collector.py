"""Real-time kline collector.

Responsibilities:
  * keep one websocket connection for all subscribed symbols;
  * buffer *closed* bars and flush them to parquet periodically;
  * on start and on every reconnect, backfill the gap with REST;
  * detect a silently dead connection (no message for N seconds) and reconnect;
  * optionally run a daily data-quality check in the background.

The collector writes through the same idempotent store used by the CLI, so a
restart can never duplicate or corrupt bars.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import signal
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import websockets

from quant.config import BINANCE_MARKET_BASE
from quant.data.binance import BAR_SCHEMA, INTERVAL_MS, BinanceMarketData
from quant.data.heartbeat import DEFAULT_HEARTBEAT_SECONDS, write_heartbeat
from quant.data.quality import check_bars, describe
from quant.data.store import latest_open_time, read_bars, write_bars
from quant.data.stream import WS_MARKET_BASE, KlineBar, parse_kline, stream_url

log = logging.getLogger(__name__)


def compute_backfill_start(
    last: datetime | None,
    now: datetime,
    step: timedelta,
    backfill_days: float,
    repair_window: timedelta | None = None,
) -> datetime:
    """Where to start a REST catch-up.

    * No local data: go back `backfill_days`.
    * Local data: start right after the last stored bar.
    * With a repair window: also re-fetch the recent tail, which fixes holes
      behind the newest bar (e.g. a bar that closed while we were connecting).
    """
    if last is None:
        return now - timedelta(days=backfill_days)
    since = last + step
    if repair_window is not None:
        since = min(since, now - repair_window)
    return since


@dataclass
class CollectorStats:
    started_at: float = field(default_factory=time.time)
    connects: int = 0
    messages: int = 0
    bars_seen: int = 0
    bars_written: int = 0
    backfills: int = 0
    last_message_at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, object]:
        return {
            "uptime_s": int(time.time() - self.started_at),
            "connects": self.connects,
            "messages": self.messages,
            "bars_seen": self.bars_seen,
            "bars_written": self.bars_written,
            "backfills": self.backfills,
            "idle_s": round(time.monotonic() - self.last_message_at, 1),
        }


class Collector:
    def __init__(
        self,
        symbols: list[str],
        interval: str = "1m",
        root: Path | None = None,
        rest_base: str = BINANCE_MARKET_BASE,
        ws_base: str = WS_MARKET_BASE,
        flush_seconds: float = 2.0,
        idle_timeout: float = 90.0,
        backfill_days: float = 1.0,
        repair_window_minutes: float = 120.0,
        verify_every_hours: float = 0.0,
        verify_days: int = 1,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        if interval not in INTERVAL_MS:
            raise ValueError(f"unsupported interval: {interval}")
        self.symbols = [s.upper() for s in symbols]
        if not self.symbols:
            raise ValueError("at least one symbol is required")

        self.interval = interval
        self.root = root
        self.rest_base = rest_base
        self.ws_base = ws_base
        self.flush_seconds = flush_seconds
        self.idle_timeout = idle_timeout
        self.backfill_days = backfill_days
        self.repair_window_minutes = repair_window_minutes
        self.verify_every_hours = verify_every_hours
        self.verify_days = verify_days

        self.stats = CollectorStats()
        self._buffer: dict[str, list[dict[str, object]]] = {s: [] for s in self.symbols}
        self._last_flush = time.monotonic()
        self._last_stats_log = time.monotonic()
        self.heartbeat_seconds = heartbeat_seconds
        self._last_heartbeat = 0.0
        self._stop = False

    # ------------------------------------------------------------------ state

    @property
    def stopping(self) -> bool:
        return self._stop

    def request_stop(self) -> None:
        log.info("stop requested")
        self._stop = True

    # --------------------------------------------------------------- heartbeat

    def heartbeat_payload(self, state: str = "running") -> dict[str, object]:
        now = datetime.now(UTC)
        stats = self.stats.as_dict()
        return {
            "state": state,
            "heartbeat_at": now.isoformat(),
            "started_at": datetime.fromtimestamp(self.stats.started_at, tz=UTC).isoformat(),
            "pid": os.getpid(),
            "interval": self.interval,
            "symbols": self.symbols,
            "uptime_s": stats["uptime_s"],
            "connects": stats["connects"],
            "messages": stats["messages"],
            "bars_seen": stats["bars_seen"],
            "bars_written": stats["bars_written"],
            "backfills": stats["backfills"],
            "idle_s": stats["idle_s"],
            "pending_bars": self.pending(),
        }

    def write_heartbeat(self, state: str = "running") -> None:
        """Publish status for the admin UI. Never raises: a read-only data
        directory must not take the collector down."""
        try:
            write_heartbeat(self.heartbeat_payload(state), root=self.root)
        except OSError as exc:
            log.debug("heartbeat write failed: %s", exc)
        self._last_heartbeat = time.monotonic()

    def _maybe_heartbeat(self) -> None:
        if time.monotonic() - self._last_heartbeat >= self.heartbeat_seconds:
            self.write_heartbeat()

    # ------------------------------------------------------- message handling

    def handle_message(self, message: dict) -> KlineBar | None:
        """Buffer a closed bar. Returns the bar when it was accepted."""
        bar = parse_kline(message)
        if bar is None:
            return None
        self.stats.bars_seen += 1

        if not bar.is_final:
            return None
        if bar.symbol not in self._buffer:
            log.debug("ignoring bar for unsubscribed symbol %s", bar.symbol)
            return None

        self._buffer[bar.symbol].append(bar.as_row())
        return bar

    def pending(self) -> int:
        return sum(len(rows) for rows in self._buffer.values())

    def flush(self) -> int:
        """Persist buffered bars. Safe to call at any time, including shutdown."""
        written = 0
        for symbol, rows in self._buffer.items():
            if not rows:
                continue
            frame = pl.DataFrame(rows, schema=BAR_SCHEMA)
            result = write_bars(frame, symbol, root=self.root, interval=self.interval)
            written += result.rows_added + result.rows_updated
            self._buffer[symbol] = []
            log.info(
                "flushed %s: added=%d updated=%d",
                symbol,
                result.rows_added,
                result.rows_updated,
            )
        self.stats.bars_written += written
        self._last_flush = time.monotonic()
        return written

    async def _maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_seconds and self.pending():
            await asyncio.to_thread(self.flush)

    async def _sleep(self, seconds: float) -> None:
        """Indirection so tests can skip reconnect backoff."""
        await asyncio.sleep(seconds)

    # ---------------------------------------------------------------- backfill

    def backfill_symbol(self, symbol: str, repair_window: timedelta | None = None) -> int:
        """Fill the gap between the last stored bar and now using REST."""
        step = timedelta(milliseconds=INTERVAL_MS[self.interval])
        last = latest_open_time(symbol, root=self.root, interval=self.interval)
        now = datetime.now(UTC)
        since = compute_backfill_start(last, now, step, self.backfill_days, repair_window)

        if since >= now - step:
            return 0

        log.info("backfilling %s from %s", symbol, since)
        with BinanceMarketData(base_url=self.rest_base) as client:
            frame = client.fetch_klines(symbol, interval=self.interval, start=since)
        if frame.is_empty():
            return 0

        result = write_bars(frame, symbol, root=self.root, interval=self.interval)
        self.stats.backfills += 1
        log.info(
            "backfilled %s: %d bars (added=%d updated=%d)",
            symbol,
            frame.height,
            result.rows_added,
            result.rows_updated,
        )
        return frame.height

    async def _backfill_all(self, repair_window: timedelta | None = None) -> None:
        for symbol in self.symbols:
            try:
                await asyncio.to_thread(self.backfill_symbol, symbol, repair_window)
            except Exception as exc:  # a failed backfill must not stop the collector
                log.warning("backfill %s failed: %s", symbol, exc)

    # --------------------------------------------------------------- ws stream

    async def _stream_once(self, deadline: float | None) -> None:
        url = stream_url(self.symbols, self.interval, self.ws_base)
        async with websockets.connect(
            url,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_queue=2048,
        ) as ws:
            self.stats.connects += 1
            self.stats.last_message_at = time.monotonic()
            log.info("ws connected: symbols=%s interval=%s", ",".join(self.symbols), self.interval)

            # A bar that closed between the REST catch-up and this connection
            # never arrives as a final ws event, so repair the recent tail.
            if self.repair_window_minutes > 0:
                await self._backfill_all(
                    repair_window=timedelta(minutes=self.repair_window_minutes)
                )

            recv_task = asyncio.create_task(ws.recv())
            try:
                while True:
                    if self._stop:
                        return

                    timeout = 1.0
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return
                        timeout = min(timeout, remaining)

                    done, _ = await asyncio.wait({recv_task}, timeout=timeout)

                    if not done:
                        if time.monotonic() - self.stats.last_message_at > self.idle_timeout:
                            raise ConnectionError(
                                f"no ws message for {self.idle_timeout:.0f}s, reconnecting"
                            )
                        await self._maybe_flush()
                        await self._maybe_log_stats()
                        self._maybe_heartbeat()
                        continue

                    raw = recv_task.result()
                    recv_task = asyncio.create_task(ws.recv())

                    self.stats.messages += 1
                    self.stats.last_message_at = time.monotonic()

                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        log.warning("dropping non-json message")
                        continue

                    self.handle_message(message)
                    await self._maybe_flush()
                    await self._maybe_log_stats()
                    self._maybe_heartbeat()
            finally:
                recv_task.cancel()

    async def _maybe_log_stats(self) -> None:
        if time.monotonic() - self._last_stats_log < 60:
            return
        self._last_stats_log = time.monotonic()
        log.info("stats %s", self.stats.as_dict())

    # ------------------------------------------------------------------ verify

    def verify_all(self) -> bool:
        """Daily-ish data quality check used by the background task."""
        ok = True
        for symbol in self.symbols:
            frame = read_bars(
                symbol,
                root=self.root,
                interval=self.interval,
                start=datetime.now(UTC) - timedelta(days=self.verify_days),
            )
            report = check_bars(frame, interval=self.interval)
            if report.ok:
                log.info("verify %s: ok (%d bars)", symbol, report.rows)
            else:
                ok = False
                log.warning("verify %s: FAILED\n%s", symbol, "\n".join(describe(report)))
        return ok

    async def _verify_loop(self) -> None:
        while not self._stop:
            await asyncio.sleep(self.verify_every_hours * 3600)
            if self._stop:
                return
            try:
                await asyncio.to_thread(self.verify_all)
            except Exception as exc:
                log.warning("verify failed: %s", exc)

    # -------------------------------------------------------------------- run

    async def run(self, run_for: float | None = None) -> None:
        """Run until stopped (Ctrl-C / SIGTERM) or `run_for` seconds elapse."""
        self._install_signal_handlers()
        deadline = time.monotonic() + run_for if run_for else None
        backoff = 1.0

        verify_task: asyncio.Task | None = None
        if self.verify_every_hours > 0:
            verify_task = asyncio.create_task(self._verify_loop())

        self.write_heartbeat()
        try:
            while not self._stop:
                if deadline is not None and time.monotonic() >= deadline:
                    break

                await self._backfill_all()
                try:
                    await self._stream_once(deadline)
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    delay = min(backoff, 60.0) + random.uniform(0, 1.0)
                    log.warning("ws error: %s (reconnect in %.1fs)", exc, delay)
                    await self._sleep(delay)
                    backoff *= 2
        finally:
            if verify_task is not None:
                verify_task.cancel()
            await asyncio.to_thread(self.flush)
            self.write_heartbeat("stopped")
            log.info("collector stopped, stats %s", self.stats.as_dict())

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError):  # pragma: no cover
                loop.add_signal_handler(sig, self.request_stop)
