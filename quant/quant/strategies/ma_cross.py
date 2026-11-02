"""Moving-average cross with an ATR trailing stop.

Long only (spot). Entry on a golden cross, exit on a death cross or when price
falls more than `atr_mult` ATRs below the highest price since entry.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field, model_validator

from quant.strategies.base import BaseStrategy, StrategySpec
from quant.strategies.registry import register


class MACrossParams(BaseModel):
    fast: int = Field(20, ge=2, le=1000, title="快线周期")
    slow: int = Field(60, ge=3, le=5000, title="慢线周期")
    atr_window: int = Field(14, ge=2, le=200, title="ATR 周期")
    atr_mult: float = Field(3.0, ge=0.5, le=20, title="ATR 止损倍数")
    target: float = Field(0.95, ge=0.05, le=1.0, title="目标仓位比例")

    @model_validator(mode="after")
    def _check_windows(self) -> MACrossParams:
        if self.fast >= self.slow:
            raise ValueError("快线周期必须小于慢线周期")
        return self


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
class MACross(BaseStrategy):
    spec = StrategySpec(
        name="ma_cross",
        title="双均线 + ATR 止损",
        description="快慢均线金叉开仓，死叉或回撤超过 ATR 倍数止损。仅做多。",
        params_model=MACrossParams,
        tags=("trend", "spot"),
    )

    def __init__(self, params: MACrossParams) -> None:
        super().__init__(params)
        self._high_since_entry: dict[str, float] = {}

    def on_start(self, ctx) -> None:
        self._high_since_entry.clear()

    def on_bar(self, ctx, bar) -> None:
        p = self.params
        need = max(p.slow, p.atr_window) + 2
        closes = ctx.history(bar.symbol, "close", need)
        if len(closes) < need:
            return

        fast = float(closes[-p.fast :].mean())
        slow = float(closes[-p.slow :].mean())
        prev_fast = float(closes[-p.fast - 1 : -1].mean())
        prev_slow = float(closes[-p.slow - 1 : -1].mean())

        position = ctx.position(bar.symbol)

        if position.is_flat:
            if prev_fast <= prev_slow and fast > slow:
                ctx.target_percent(bar.symbol, p.target, reason="golden_cross")
                self._high_since_entry[bar.symbol] = bar.high
            return

        highest = max(self._high_since_entry.get(bar.symbol, bar.high), bar.high)
        self._high_since_entry[bar.symbol] = highest

        atr = _atr(ctx, bar.symbol, p.atr_window)
        stop = highest - p.atr_mult * atr if atr > 0 else 0.0

        if fast < slow:
            ctx.close(bar.symbol, reason="death_cross")
            self._high_since_entry.pop(bar.symbol, None)
        elif stop > 0 and bar.close < stop:
            ctx.close(bar.symbol, reason="atr_stop")
            self._high_since_entry.pop(bar.symbol, None)
