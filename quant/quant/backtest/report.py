"""Backtest reporting: console-friendly data and standalone SVG charts."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from quant.backtest.metrics import drawdown_series
from quant.backtest.types import BacktestResult, TradeRecord
from quant.reporting import line_svg


def _downsample(values: list[float], times: list, limit: int = 1200) -> tuple[list[float], list]:
    if len(values) <= limit:
        return values, times
    step = len(values) / limit
    idx = [int(i * step) for i in range(limit)]
    if idx[-1] != len(values) - 1:
        idx.append(len(values) - 1)
    return [values[i] for i in idx], [times[i] for i in idx]


def equity_svg(result: BacktestResult) -> str:
    values, times = _downsample(result.equity, result.times)
    return line_svg(values, times)


def drawdown_svg(result: BacktestResult) -> str:
    dd = (drawdown_series(np.asarray(result.equity, dtype=float)) * 100).tolist()
    values, times = _downsample(dd, result.times)
    return line_svg(values, times)


def _json_safe(value):
    """NaN/Infinity are not valid JSON; the web UI would choke on them."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _iso(moment) -> str | None:
    return moment.isoformat().replace("+00:00", "Z") if moment else None


def _curve(times: list, values: list[float], limit: int = 600) -> list[dict]:
    """Downsampled series for charting; keeps the last point exact."""
    n = min(len(times), len(values))
    if n == 0:
        return []
    step = max(1, n // limit)
    idx = list(range(0, n, step))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return [{"t": _iso(times[i]), "v": float(values[i])} for i in idx]


def trade_payload(trade: TradeRecord) -> dict:
    return {
        "time": _iso(trade.time),
        "symbol": trade.symbol,
        "side": str(trade.side),
        "qty": trade.qty,
        "price": trade.price,
        "fee": trade.fee,
        "realized_pnl": trade.realized_pnl,
        "reason": trade.reason,
    }


def result_payload(
    result: BacktestResult,
    report_dir: Path | None = None,
    trades_limit: int = 500,
) -> dict:
    """Single JSON contract shared by the CLI and the Go API."""
    trades = result.trades[-trades_limit:] if trades_limit > 0 else result.trades
    payload = {
        "strategy": result.strategy,
        "symbols": result.symbols,
        "params": result.params,
        "initial_cash": result.initial_cash,
        "final_equity": result.final_equity,
        "bars_processed": result.bars_processed,
        "start": _iso(result.times[0]) if result.times else None,
        "end": _iso(result.times[-1]) if result.times else None,
        "metrics": result.metrics,
        "monthly_returns": result.monthly_returns,
        "equity_curve": _curve(result.times, result.equity),
        "drawdown_curve": _curve(
            result.times,
            (drawdown_series(np.asarray(result.equity, dtype=float)) * 100).tolist(),
        ),
        "trades": [trade_payload(t) for t in trades],
        "trades_total": len(result.trades),
        "report_dir": str(report_dir) if report_dir else None,
    }
    return _json_safe(payload)


def save_report(result: BacktestResult, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    payload = result_payload(result, out_dir, trades_limit=0)
    paths["metrics"] = out_dir / "metrics.json"
    paths["metrics"].write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, allow_nan=False)
    )

    paths["equity"] = out_dir / "equity.svg"
    paths["equity"].write_text(equity_svg(result))

    paths["drawdown"] = out_dir / "drawdown.svg"
    paths["drawdown"].write_text(drawdown_svg(result))

    return paths
