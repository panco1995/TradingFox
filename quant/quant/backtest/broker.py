"""Simulated broker: fees, slippage, volume participation and min notional.

Every rule here exists because ignoring it inflates backtest returns:
  * fees: 5 bps taker is the difference between profit and loss at 1m;
  * slippage: you never get the open price exactly;
  * participation cap: you cannot buy more than a fraction of one bar's volume;
  * min notional: orders below the exchange minimum are rejected, not filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from quant.backtest.types import Fill, Order, Position, Side


@dataclass
class BrokerConfig:
    fee_rate: float = 0.0005  # taker, conservative
    slippage_bps: float = 2.0  # 0.02%
    max_participation: float = 0.01  # max 1% of bar volume
    min_notional: float = 5.0


class SimBroker:
    def __init__(self, config: BrokerConfig | None = None) -> None:
        self.config = config or BrokerConfig()

    def _slip(self, price: float, side: Side) -> float:
        adj = self.config.slippage_bps / 10_000
        return price * (1 + adj) if side is Side.BUY else price * (1 - adj)

    def execute(
        self,
        order: Order,
        open_price: float,
        bar_volume: float,
        cash: float,
        position: Position,
        now: datetime,
    ) -> Fill | None:
        if not np.isfinite(open_price) or open_price <= 0:
            return None

        price = self._slip(open_price, order.side)
        cap = max(bar_volume * self.config.max_participation, 0.0)

        if order.side is Side.BUY:
            affordable = cash / (price * (1 + self.config.fee_rate))
            qty = min(cap, affordable)
            if order.qty is not None:
                qty = min(qty, order.qty)
        else:
            # Exits are not participation-capped: refusing to sell because a bar
            # was thin would create fake "stuck in position" results.
            qty = position.qty if order.qty is None else min(order.qty, position.qty)

        if qty <= 0:
            return None

        notional = qty * price
        if notional < self.config.min_notional:
            return None

        fee = notional * self.config.fee_rate
        realized = 0.0

        if order.side is Side.BUY:
            new_qty = position.qty + qty
            position.avg_price = (position.avg_price * position.qty + notional) / new_qty
            position.qty = new_qty
            cash -= notional + fee
        else:
            realized = (price - position.avg_price) * qty - fee
            position.qty -= qty
            position.realized_pnl += realized
            if position.qty <= 1e-12:
                position.qty = 0.0
                position.avg_price = 0.0
            cash += notional - fee

        position.fees_paid += fee

        return Fill(
            symbol=order.symbol,
            side=order.side,
            qty=qty,
            price=price,
            fee=fee,
            time=now,
            realized_pnl=realized,
            reason=order.reason,
        )
