"""Bollinger + RSI mean reversion, tuned for 15-minute crypto bars.

The idea is simple and deliberately transparent: in a quiet or gently trending
market, a 15m candle that pokes below the lower Bollinger band while RSI is
oversold tends to snap back toward the middle band. We buy that snapback and
exit on the middle band, RSI normalisation, a fixed ATR stop, or a time stop.

Why a mean-reversion strategy for 15m: intraday crypto noise is large relative
to the move a trend follower can capture in a few hours, while round-trip costs
(5 bps fee + 2 bps slippage ≈ 14 bps) are not. Mean reversion targets the part
of the move that is most repeatable at this timeframe, and the time stop keeps
a failed trade from turning into a multi-day position.

Long only (spot). All indicators use only bars up to and including the current
one, so there is no look-ahead.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field, model_validator

from quant.strategies.base import BaseStrategy, StrategySpec
from quant.strategies.registry import register


class BollingerRSIParams(BaseModel):
    bb_window: int = Field(20, ge=5, le=200, title="布林带周期")
    bb_std: float = Field(2.0, ge=1.0, le=4.0, title="布林带标准差倍数")
    rsi_window: int = Field(14, ge=2, le=100, title="RSI 周期")
    rsi_entry: float = Field(30.0, ge=5.0, le=50.0, title="RSI 超卖阈值")
    rsi_exit: float = Field(55.0, ge=45.0, le=90.0, title="RSI 离场阈值")
    atr_window: int = Field(14, ge=2, le=100, title="ATR 周期")
    atr_mult: float = Field(2.0, ge=0.5, le=10.0, title="ATR 止损倍数")
    max_hold_bars: int = Field(
        16,
        ge=1,
        le=500,
        title="最长持仓 K 线数",
        description="默认 16 根 15m = 4 小时",
    )
    trend_window: int = Field(
        100,
        ge=0,
        le=1000,
        title="趋势过滤 EMA（0 = 关闭）",
        description="只做多的前提下，价格需在 EMA 之上",
    )
    target: float = Field(0.95, ge=0.05, le=1.0, title="目标仓位比例")

    @model_validator(mode="after")
    def _check_thresholds(self) -> BollingerRSIParams:
        if self.rsi_entry >= self.rsi_exit:
            raise ValueError("RSI 超卖阈值必须小于离场阈值")
        return self


def _rsi(closes: np.ndarray, window: int) -> float | None:
    """Simple-average RSI over the last `window` changes."""
    if len(closes) < window + 1:
        return None
    diff = np.diff(closes[-(window + 1) :])
    gains = float(np.clip(diff, 0.0, None).mean())
    losses = float(-np.clip(diff, None, 0.0).mean())
    if losses == 0.0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def _ema(values: np.ndarray, period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = float(values[0])
    for raw in values[1:]:
        value = alpha * float(raw) + (1.0 - alpha) * value
    return value


def _atr(ctx, symbol: str, window: int) -> float:
    high = ctx.history(symbol, "high", window + 1)
    low = ctx.history(symbol, "low", window + 1)
    close = ctx.history(symbol, "close", window + 1)
    if len(close) < window + 1:
        return 0.0
    prev_close = close[:-1]
    true_range = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )
    return float(true_range[-window:].mean())


@register
class BollingerRSI(BaseStrategy):
    spec = StrategySpec(
        name="bollinger_rsi",
        title="布林带 + RSI 均值回归",
        description=(
            "价格跌破布林下轨且 RSI 超卖时买入，回到中轨、RSI 修复、ATR 止损或超时离场。"
            "为 15 分钟短线设计，仅做多。"
        ),
        params_model=BollingerRSIParams,
        tags=("mean_reversion", "intraday", "spot"),
    )

    def __init__(self, params: BollingerRSIParams) -> None:
        super().__init__(params)
        self._bars_held: dict[str, int] = {}

    def on_start(self, ctx) -> None:
        self._bars_held.clear()

    def on_bar(self, ctx, bar) -> None:
        p = self.params
        rsi_need = p.rsi_window + 1
        atr_need = p.atr_window + 1
        need = max(p.bb_window, rsi_need, atr_need)
        if p.trend_window > 0:
            need = max(need, p.trend_window)

        closes = ctx.history(bar.symbol, "close", need)
        if len(closes) < need:
            return

        rsi = _rsi(closes, p.rsi_window)
        if rsi is None:
            return

        position = ctx.position(bar.symbol)

        if position.is_flat:
            window = closes[-p.bb_window :]
            middle = float(window.mean())
            deviation = float(window.std())
            lower = middle - p.bb_std * deviation

            trend_ok = True
            if p.trend_window > 0:
                ema_bars = max(p.trend_window, p.trend_window * 3)
                ema_source = ctx.history(bar.symbol, "close", ema_bars)
                ema = _ema(ema_source, p.trend_window)
                trend_ok = ema is not None and bar.close > ema

            if bar.close <= lower and rsi <= p.rsi_entry and trend_ok:
                ctx.target_percent(bar.symbol, p.target, reason="bb_rsi_entry")
                self._bars_held[bar.symbol] = 0
            return

        held = self._bars_held.get(bar.symbol, 0) + 1
        self._bars_held[bar.symbol] = held

        window = closes[-p.bb_window :]
        middle = float(window.mean())
        atr = _atr(ctx, bar.symbol, p.atr_window)
        stop = position.avg_price - p.atr_mult * atr if atr > 0 else 0.0

        if stop > 0 and bar.close < stop:
            ctx.close(bar.symbol, reason="atr_stop")
        elif bar.close >= middle:
            ctx.close(bar.symbol, reason="band_exit")
        elif rsi >= p.rsi_exit:
            ctx.close(bar.symbol, reason="rsi_exit")
        elif held >= p.max_hold_bars:
            ctx.close(bar.symbol, reason="time_exit")
        else:
            return
        self._bars_held.pop(bar.symbol, None)
