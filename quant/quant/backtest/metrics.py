"""Performance metrics.

Daily resampling is used for the risk ratios: 1-minute returns are mostly noise
and produce absurd annualisation factors.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import polars as pl

from quant.backtest.types import TradeRecord


def _daily_equity(times: list[datetime], equity: list[float]) -> pl.DataFrame:
    frame = pl.DataFrame({"ts": times, "equity": equity})
    return (
        frame.group_by(pl.col("ts").dt.date().alias("date"))
        .agg(pl.col("equity").last())
        .sort("date")
    )


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) < 2:
        return 0.0
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = (equity - peak) / peak
    return float(np.nanmin(drawdown))


def drawdown_series(equity: np.ndarray) -> np.ndarray:
    if len(equity) == 0:
        return equity
    peak = np.maximum.accumulate(equity)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (equity - peak) / peak


# Daily returns below this count produce meaningless annualised ratios;
# a 2-day backtest should report n/a instead of a scary Sharpe of -18.
MIN_RISK_SAMPLES = 5


def _ratio(values: np.ndarray) -> float:
    if len(values) < MIN_RISK_SAMPLES:
        return float("nan")
    std = float(np.std(values, ddof=1))
    if std == 0 or not math.isfinite(std):
        return 0.0
    return float(np.mean(values) / std * math.sqrt(365))


def compute_metrics(
    times: list[datetime],
    equity: list[float],
    trades: list[TradeRecord],
    initial_cash: float,
) -> dict[str, float]:
    eq = np.asarray(equity, dtype=float)
    if len(eq) == 0:
        return {}

    total_return = float(eq[-1] / initial_cash - 1)
    days = max((times[-1] - times[0]).total_seconds() / 86_400, 1e-9)
    years = days / 365
    # Annualising a few days of data produces numbers like -100%; report n/a.
    cagr = (
        float((eq[-1] / initial_cash) ** (1 / years) - 1)
        if years >= 30 / 365 and eq[-1] > 0
        else float("nan")
    )

    daily = _daily_equity(times, equity)
    d_eq = daily["equity"].to_numpy().astype(float)
    d_rets = np.diff(d_eq) / d_eq[:-1] if len(d_eq) > 1 else np.array([])

    downside = d_rets[d_rets < 0]
    sortino_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(np.mean(d_rets) / sortino_std * math.sqrt(365))
        if len(d_rets) >= MIN_RISK_SAMPLES and sortino_std > 0
        else float("nan")
    )

    mdd = max_drawdown(eq)
    calmar = cagr / abs(mdd) if mdd < 0 and math.isfinite(cagr) else float("nan")

    sells = [t for t in trades if t.side == "sell"]
    wins = [t.realized_pnl for t in sells if t.realized_pnl > 0]
    losses = [t.realized_pnl for t in sells if t.realized_pnl < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    turnover = sum(t.qty * t.price for t in trades) / float(np.mean(eq)) if len(eq) else 0.0
    fees = sum(t.fee for t in trades)

    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": _ratio(d_rets),
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": calmar,
        "volatility": (
            float(np.std(d_rets, ddof=1) * math.sqrt(365))
            if len(d_rets) >= MIN_RISK_SAMPLES
            else float("nan")
        ),
        "final_equity": float(eq[-1]),
        "days": days,
        "trades": float(len(trades)),
        "round_trips": float(len(sells)),
        "win_rate": len(wins) / len(sells) if sells else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else 0.0,
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
        "turnover": turnover,
        "fees_paid": fees,
    }


def monthly_returns(
    times: list[datetime],
    equity: list[float],
    initial_cash: float,
) -> dict[str, float]:
    if not times:
        return {}

    frame = pl.DataFrame({"ts": times, "equity": equity})
    monthly = (
        frame.group_by(pl.col("ts").dt.strftime("%Y-%m").alias("month"))
        .agg(pl.col("equity").last())
        .sort("month")
    )

    out: dict[str, float] = {}
    previous = initial_cash
    for month, value in monthly.iter_rows():
        if previous > 0:
            out[str(month)] = float(value / previous - 1)
        previous = value
    return out
