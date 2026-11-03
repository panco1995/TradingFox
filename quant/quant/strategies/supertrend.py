"""Supertrend: an ATR trailing-stop trend follower built for 15-minute bars.

Supertrend draws a band that sits ``multiplier x ATR`` away from the midpoint of
each bar and ratchets in the direction of the trend: it only moves up while the
trend is up, and only moves down while the trend is down. A close through the
band flips the trend. That makes it a compact "trend plus trailing stop" system
with no separate exit rule - the band *is* the stop.

It suits intraday crypto because a 15m ATR scales the stop to current
volatility, so a quiet market does not get stopped by noise while a violent one
gives the trade room. It is a trend follower, so it accepts many small losses in
choppy markets and relies on a few large winners; an optional long-horizon EMA
filter is provided to skip trades against the dominant trend.

The band is stateful: it carries the previous bar's band forward, so the
strategy keeps one ``SupertrendState`` per symbol instead of recomputing a
rolling window. Recomputing a short window would restart the band every bar and
produce fake flips at the window boundary.

Long only (spot). Every indicator uses bars up to and including the current one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field

from quant.strategies.base import BaseStrategy, StrategySpec
from quant.strategies.registry import register


class SupertrendParams(BaseModel):
    atr_period: int = Field(10, ge=2, le=100, title="ATR 周期")
    atr_mult: float = Field(3.0, ge=0.5, le=10.0, title="ATR 倍数（带宽）")
    trend_window: int = Field(
        0,
        ge=0,
        le=1000,
        title="趋势过滤 EMA（0 = 关闭）",
        description="只做多的前提下，价格需在 EMA 之上；0 表示不做方向过滤",
    )
    target: float = Field(0.95, ge=0.05, le=1.0, title="目标仓位比例")


@dataclass
class SupertrendState:
    """Incremental Supertrend for one symbol.

    Fed one closed bar at a time, it returns ``(direction, band)`` where
    direction is +1 up, -1 down or 0 while the ATR is still warming up.
    """

    period: int
    multiplier: float
    prev_close: float | None = None
    atr: float | None = None
    final_upper: float = float("nan")
    final_lower: float = float("nan")
    direction: int = 0
    _true_ranges: list[float] = field(default_factory=list)

    def update(self, high: float, low: float, close: float) -> tuple[int, float]:
        if self.prev_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - self.prev_close),
                abs(low - self.prev_close),
            )

        if self.atr is None:
            self._true_ranges.append(true_range)
            if len(self._true_ranges) < self.period:
                self.prev_close = close
                return 0, float("nan")
            self.atr = sum(self._true_ranges) / self.period
            self._true_ranges.clear()
            midpoint = (high + low) / 2.0
            self.final_upper = midpoint + self.multiplier * self.atr
            self.final_lower = midpoint - self.multiplier * self.atr
            self.direction = 1 if close >= midpoint else -1
        else:
            self.atr = (self.atr * (self.period - 1) + true_range) / self.period
            midpoint = (high + low) / 2.0
            upper = midpoint + self.multiplier * self.atr
            lower = midpoint - self.multiplier * self.atr

            prev_upper = self.final_upper
            prev_lower = self.final_lower
            prev_close = self.prev_close

            self.final_upper = (
                upper if (upper < prev_upper or prev_close > prev_upper) else prev_upper
            )
            self.final_lower = (
                lower if (lower > prev_lower or prev_close < prev_lower) else prev_lower
            )

            if close > prev_upper:
                self.direction = 1
            elif close < prev_lower:
                self.direction = -1

        self.prev_close = close
        band = self.final_lower if self.direction > 0 else self.final_upper
        return self.direction, band


def _supertrend(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int, mult: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vector-friendly wrapper around :class:`SupertrendState` for tests."""
    state = SupertrendState(period, mult)
    direction = np.zeros(len(close), dtype=np.int8)
    band = np.full(len(close), np.nan)
    for i in range(len(close)):
        direction[i], band[i] = state.update(float(high[i]), float(low[i]), float(close[i]))
    return direction, band


def _ema_last(values: np.ndarray, period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = float(values[0])
    for raw in values[1:]:
        value = alpha * float(raw) + (1.0 - alpha) * value
    return value


@register
class Supertrend(BaseStrategy):
    spec = StrategySpec(
        name="supertrend",
        title="Supertrend 趋势跟踪",
        description=(
            "用 ATR 带宽构建跟踪止损线，收盘站上翻转做多，跌破翻转离场。"
            "适合 15 分钟趋势行情，仅做多。"
        ),
        params_model=SupertrendParams,
        tags=("trend", "atr", "intraday", "spot"),
    )

    def on_start(self, ctx) -> None:
        self._states: dict[str, SupertrendState] = {}

    def on_bar(self, ctx, bar) -> None:
        p = self.params
        state = self._states.get(bar.symbol)
        if state is None:
            state = SupertrendState(p.atr_period, p.atr_mult)
            self._states[bar.symbol] = state

        direction, _ = state.update(bar.high, bar.low, bar.close)
        if direction == 0:
            return

        position = ctx.position(bar.symbol)

        # The band is the stop, so the rule is simply "be long while the
        # Supertrend points up". Entering on the first up-bar also means a
        # backtest that starts mid-trend does not sit out the move.
        if position.is_flat:
            if direction > 0:
                if p.trend_window > 0:
                    ema_bars = max(p.trend_window * 3, p.trend_window + 1)
                    source = ctx.history(bar.symbol, "close", ema_bars)
                    ema = _ema_last(source, p.trend_window)
                    if ema is None or bar.close <= ema:
                        return
                ctx.target_percent(bar.symbol, p.target, reason="supertrend_long")
        elif direction < 0:
            ctx.close(bar.symbol, reason="supertrend_exit")
