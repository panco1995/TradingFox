"""Command line entry point.

    quant fetch   --symbol BTCUSDT --days 7
    quant inspect --symbol BTCUSDT --days 7 --svg data/chart.svg
    quant quality --symbol BTCUSDT --days 30
    quant symbols --symbol BTCUSDT
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from quant.config import BINANCE_MARKET_BASE, DEFAULT_INTERVAL, data_root
from quant.data.binance import INTERVAL_MS, BinanceError, BinanceMarketData
from quant.data.collector import Collector
from quant.data.quality import check_bars, describe
from quant.data.store import latest_open_time, read_bars, write_bars
from quant.data.stream import WS_MARKET_BASE
from quant.reporting import line_svg, sparkline

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Crypto quant CLI")
console = Console()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _resolve_range(
    days: int | None, start: str | None, end: str | None
) -> tuple[datetime | None, datetime | None]:
    if start:
        return _parse_time(start), _parse_time(end)
    if days is None:
        raise typer.BadParameter("provide --days or --start")
    end_dt = _parse_time(end) or datetime.now(UTC)
    return end_dt - timedelta(days=days), end_dt


def _align_to_interval(dt: datetime, interval: str) -> datetime:
    """Floor a timestamp onto the bar boundary, so the first fetched bar is whole."""
    step = INTERVAL_MS[interval]
    ms = int(dt.timestamp() * 1000)
    return datetime.fromtimestamp(ms - ms % step, tz=UTC)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("quant").setLevel(logging.DEBUG if verbose else logging.INFO)


@app.command()
def fetch(
    symbol: list[str] = typer.Option(["BTCUSDT"], "--symbol", "-s", help="repeatable"),
    days: int | None = typer.Option(None, "--days", "-d", help="how many days back"),
    start: str | None = typer.Option(None, help="ISO time, e.g. 2026-01-01"),
    end: str | None = typer.Option(None, help="ISO time, default now"),
    interval: str = typer.Option(DEFAULT_INTERVAL, "--interval", "-i"),
    incremental: bool = typer.Option(
        False, "--incremental", help="continue from the last stored bar"
    ),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    base_url: str = typer.Option(BINANCE_MARKET_BASE, "--base-url"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Download klines and merge them into Parquet storage (idempotent)."""
    _setup_logging(verbose)
    root = (data_dir or data_root()).expanduser().resolve()
    console.print(f"data root: [cyan]{root}[/cyan]  source: [dim]{base_url}[/dim]")

    if interval not in INTERVAL_MS:
        raise typer.BadParameter(f"unsupported interval: {interval}")

    start_dt, end_dt = _resolve_range(days, start, end)

    with BinanceMarketData(base_url=base_url) as client:
        drift = client.clock_drift_ms()
        if abs(drift) > 1000:
            console.print(f"[yellow]clock drift {drift} ms - check NTP[/yellow]")

        for sym in symbol:
            cursor = start_dt
            if incremental:
                last = latest_open_time(sym, root=root, interval=interval)
                if last is not None:
                    cursor = last + timedelta(milliseconds=INTERVAL_MS[interval])
                    console.print(f"{sym}: resuming from {cursor}")

            if cursor is None:
                raise typer.BadParameter("internal: start time unresolved")
            cursor = _align_to_interval(cursor, interval)

            console.print(f"[bold]{sym}[/bold] fetching from {cursor} ...")

            def _progress(n: int, frame, _sym: str = sym) -> None:
                last_open = frame["open_time"].max()
                console.print(f"  +{n} bars, last={last_open}", style="dim")

            df = client.fetch_klines(
                sym, interval=interval, start=cursor, end=end_dt, progress=_progress
            )
            if df.is_empty():
                console.print(f"[yellow]{sym}: no closed bars returned[/yellow]")
                continue

            result = write_bars(df, sym, root=root, interval=interval)
            console.print(
                f"[green]{sym}[/green] stored: added={result.rows_added} "
                f"updated={result.rows_updated} files={len(result.files)}"
            )


@app.command()
def watch(
    symbol: list[str] = typer.Option(["BTCUSDT"], "--symbol", "-s", help="repeatable"),
    interval: str = typer.Option(DEFAULT_INTERVAL, "--interval", "-i"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    base_url: str = typer.Option(BINANCE_MARKET_BASE, "--base-url"),
    ws_base: str = typer.Option(WS_MARKET_BASE, "--ws-base"),
    backfill_days: float = typer.Option(1.0, "--backfill-days", help="history when no local data"),
    repair_window_minutes: float = typer.Option(
        120.0, "--repair-window-minutes", help="re-fetch this recent tail on every (re)connect"
    ),
    flush_seconds: float = typer.Option(2.0, "--flush-seconds"),
    idle_timeout: float = typer.Option(90.0, "--idle-timeout", help="reconnect if silent"),
    verify_every_hours: float = typer.Option(
        24.0, "--verify-every-hours", help="0 disables the background quality check"
    ),
    verify_days: int = typer.Option(1, "--verify-days"),
    run_for: float = typer.Option(0.0, "--run-for", help="stop after N seconds, 0 = forever"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Stream live klines, backfill gaps and store closed bars."""
    _setup_logging(verbose)
    root = (data_dir or data_root()).expanduser().resolve()

    collector = Collector(
        symbols=symbol,
        interval=interval,
        root=root,
        rest_base=base_url,
        ws_base=ws_base,
        flush_seconds=flush_seconds,
        idle_timeout=idle_timeout,
        backfill_days=backfill_days,
        repair_window_minutes=repair_window_minutes,
        verify_every_hours=verify_every_hours,
        verify_days=verify_days,
    )

    console.print(
        f"collecting [bold]{', '.join(collector.symbols)}[/bold] {interval} "
        f"-> [cyan]{root}[/cyan] (ctrl-c to stop)"
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(collector.run(run_for=run_for or None))

    console.print(f"done: {collector.stats.as_dict()}")


@app.command()
def inspect(
    symbol: str = typer.Option("BTCUSDT", "--symbol", "-s"),
    days: int | None = typer.Option(7, "--days", "-d"),
    start: str | None = typer.Option(None),
    end: str | None = typer.Option(None),
    interval: str = typer.Option(DEFAULT_INTERVAL, "--interval", "-i"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    svg: Path | None = typer.Option(None, "--svg", help="write a line chart here"),
    rows: int = typer.Option(5, "--rows", help="head/tail rows to print"),
) -> None:
    """Read bars back from Parquet and print a summary."""
    root = (data_dir or data_root()).expanduser().resolve()
    start_dt, end_dt = _resolve_range(days, start, end)
    df = read_bars(symbol, start=start_dt, end=end_dt, root=root, interval=interval)

    if df.is_empty():
        console.print(f"[red]no data for {symbol}[/red] under {root}")
        raise typer.Exit(code=1)

    report = check_bars(df, interval=interval)
    for line in describe(report):
        console.print(line)

    closes = df["close"].to_list()
    console.print()
    console.print(sparkline(closes, width=console.width - 4))
    console.print(
        f"min={min(closes):,.2f}  max={max(closes):,.2f}  "
        f"last={closes[-1]:,.2f}  bars={len(closes)}"
    )

    table = Table(title=f"{symbol} last {rows} bars")
    for col in ("open_time", "open", "high", "low", "close", "volume"):
        table.add_column(col, justify="right")
    for row in df.tail(rows).iter_rows(named=True):
        table.add_row(
            str(row["open_time"]),
            f"{row['open']:,.2f}",
            f"{row['high']:,.2f}",
            f"{row['low']:,.2f}",
            f"{row['close']:,.2f}",
            f"{row['volume']:,.4f}",
        )
    console.print(table)

    if svg is not None:
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text(line_svg(closes, df["open_time"].to_list()))
        console.print(f"chart written to [cyan]{svg}[/cyan]")


@app.command()
def quality(
    symbol: list[str] = typer.Option(["BTCUSDT"], "--symbol", "-s"),
    days: int | None = typer.Option(30, "--days", "-d"),
    start: str | None = typer.Option(None),
    end: str | None = typer.Option(None),
    interval: str = typer.Option(DEFAULT_INTERVAL, "--interval", "-i"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
) -> None:
    """Check stored bars for gaps, duplicates and OHLC inconsistencies."""
    root = (data_dir or data_root()).expanduser().resolve()
    start_dt, end_dt = _resolve_range(days, start, end)

    failed = False
    for sym in symbol:
        df = read_bars(sym, start=start_dt, end=end_dt, root=root, interval=interval)
        if df.is_empty():
            console.print(f"[red]{sym}: no data[/red]")
            failed = True
            continue
        report = check_bars(df, interval=interval)
        colour = "green" if report.ok else "yellow"
        console.print(f"[{colour}]{sym}[/{colour}]")
        for line in describe(report):
            console.print(f"  {line}")
        failed = failed or not report.ok

    raise typer.Exit(code=1 if failed else 0)


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL over a `bars` view of the symbol's parquet files"),
    symbol: str = typer.Option("BTCUSDT", "--symbol", "-s"),
    interval: str = typer.Option(DEFAULT_INTERVAL, "--interval", "-i"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    limit: int = typer.Option(20, "--limit", help="rows to display"),
) -> None:
    """Ad-hoc research query with DuckDB over the stored parquet files."""
    import duckdb

    from quant.data.store import symbol_dir

    root = (data_dir or data_root()).expanduser().resolve()
    folder = symbol_dir(symbol, root, interval)
    if not any(folder.glob("*.parquet")):
        console.print(f"[red]no data for {symbol}[/red] under {folder}")
        raise typer.Exit(code=1)

    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    pattern = str(folder / "*.parquet").replace("'", "''")
    con.execute(f"CREATE VIEW bars AS SELECT * FROM read_parquet('{pattern}')")

    cursor = con.execute(sql)
    columns = [d[0] for d in (cursor.description or [])]
    rows = cursor.fetchall()

    table = Table(title=f"{len(rows)} rows")
    for col in columns:
        table.add_column(col)
    for row in rows[:limit]:
        table.add_row(*["" if v is None else str(v) for v in row])
    console.print(table)


@app.command()
def symbols(
    symbol: list[str] = typer.Option(["BTCUSDT"], "--symbol", "-s"),
    base_url: str = typer.Option(BINANCE_MARKET_BASE, "--base-url"),
    data_dir: Path | None = typer.Option(None, "--data-dir"),
    save: bool = typer.Option(False, "--save", help="write data/meta/symbols.parquet"),
) -> None:
    """Show trading rules (tick size, step size, min notional) for symbols."""
    root = (data_dir or data_root()).expanduser().resolve()
    with BinanceMarketData(base_url=base_url) as client:
        specs = client.symbol_specs(symbol)

    table = Table(title="symbol specs")
    for col in specs.columns:
        table.add_column(col)
    for row in specs.iter_rows():
        table.add_row(*["" if v is None else str(v) for v in row])
    console.print(table)

    if save:
        path = root / "meta" / "symbols.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        specs.write_parquet(path)
        console.print(f"saved to [cyan]{path}[/cyan]")


def main() -> None:
    try:
        app()
    except BinanceError as exc:
        console.print(f"[red]exchange error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    main()
