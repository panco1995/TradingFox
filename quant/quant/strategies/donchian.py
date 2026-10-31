"""Donchian channel breakout (turtle-style, long only)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from quant.strategies.base import BaseStrategy, StrategySpec
from quant.strategies.registry import register


class DonchianParams(BaseModel):
    entry_window: int = Field(55, ge=5, le=500, title="突破周期")
    exit_window: int = Field(20, ge=2, le=500, title="退出周期")
    target: float = Field(0.95, ge=0.05, le=1.0, title="目标仓位比例")

    @model_validator(mode="after")
    def _check_windows(self) -> DonchianParams:
        if self.exit_window >= self.entry_window:
            raise ValueError("exit_window must be smaller than entry_window")
        return self


@register
class Donchian(BaseStrategy):
    spec = StrategySpec(
        name="donchian",
        title="唐奇安通道突破",
        description="收盘突破 N 周期高点开仓，跌破 M 周期低点平仓。仅做多。",
        params_model=DonchianParams,
        tags=("trend", "breakout", "spot"),
    )

    def on_bar(self, ctx, bar) -> None:
        p = self.params
        highs = ctx.history(bar.symbol, "high", p.entry_window + 1)
        lows = ctx.history(bar.symbol, "low", p.exit_window + 1)
        if len(highs) < p.entry_window + 1 or len(lows) < p.exit_window + 1:
            return

        # exclude the current bar: the breakout must be measured against history
        upper = float(highs[:-1][-p.entry_window :].max())
        lower = float(lows[:-1][-p.exit_window :].min())

        position = ctx.position(bar.symbol)

        if position.is_flat:
            if bar.close > upper:
                ctx.target_percent(bar.symbol, p.target, reason="breakout")
        elif bar.close < lower:
            ctx.close(bar.symbol, reason="channel_exit")
