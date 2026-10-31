"""Event-driven backtest engine.

Timing model (this is what prevents look-ahead bias):

    bar[i] closes -> strategy.on_bar() sees ONLY bars[0..i]
                  -> orders are queued
    bar[i+1] opens -> queued orders fill at the open (+slippage)

A strategy can therefore never trade on a price it has not observed yet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from quant.backtest.broker import BrokerConfig, SimBroker
from quant.backtest.market import MarketData
from quant.backtest.types import (
    BacktestResult,
    Bar,
    Fill,
    Order,
    Position,
    Side,
    TradeRecord,
)

log = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_rate: float = 0.0005
    slippage_bps: float = 2.0
    max_participation: float = 0.01
    min_notional: float = 5.0


@dataclass
class _State:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    pending: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)


class Context:
    """What a strategy is allowed to see and do. No direct data access."""

    def __init__(self, engine: BacktestEngine) -> None:
        self._engine = engine

    @property
    def cash(self) -> float:
        return self._engine.state.cash

    @property
    def equity(self) -> float:
        return self._engine.equity()

    @property
    def now(self) -> datetime:
        return self._engine.current_time()

    def position(self, symbol: str) -> Position:
        return self._engine.state.positions.setdefault(symbol, Position(symbol=symbol))

    def history(self, symbol: str, column: str = "close", n: int = 100) -> np.ndarray:
        """Bars up to and including the current one. Never returns future data."""
        array = getattr(self._engine.market, column)[symbol]
        end = self._engine.index + 1
        return array[max(0, end - n) : end]

    def price(self, symbol: str) -> float:
        return float(self._engine.market.close[symbol][self._engine.index])

    # ------------------------------------------------------------- order entry

    def buy(
        self, symbol: str, qty: float | None = None, notional: float | None = None, reason: str = ""
    ) -> None:
        if qty is None:
            if notional is None:
                raise ValueError("buy needs qty or notional")
            price = self.price(symbol)
            if not np.isfinite(price) or price <= 0:
                return
            qty = notional / price
        if qty <= 0:
            return
        self._engine.queue(Order(symbol=symbol, side=Side.BUY, qty=qty, reason=reason))

    def sell(self, symbol: str, qty: float | None = None, reason: str = "") -> None:
        position = self.position(symbol)
        if position.is_flat:
            return
        self._engine.queue(Order(symbol=symbol, side=Side.SELL, qty=qty, reason=reason))

    def close(self, symbol: str, reason: str = "close") -> None:
        self.sell(symbol, qty=None, reason=reason)

    def target_percent(self, symbol: str, pct: float, reason: str = "") -> None:
        """Rebalance to `pct` of equity (0..1). Handles both directions."""
        if not 0.0 <= pct <= 1.0:
            raise ValueError("target percent must be within [0, 1]")
        price = self.price(symbol)
        if not np.isfinite(price) or price <= 0:
            return

        position = self.position(symbol)
        target_value = self.equity * pct
        current_value = position.qty * price
        delta_value = target_value - current_value

        if abs(delta_value) < self.engine_min_notional:
            return
        if delta_value > 0:
            self.buy(symbol, notional=delta_value, reason=reason)
        else:
            qty = min(position.qty, -delta_value / price)
            if qty > 0:
                self.sell(symbol, qty=qty, reason=reason)

    @property
    def engine_min_notional(self) -> float:
        return self._engine.broker.config.min_notional

    def log(self, message: str) -> None:
        log.info("[%s] %s", self.now.isoformat(), message)


class BacktestEngine:
    def __init__(
        self,
        market: MarketData,
        strategy: object,
        config: BacktestConfig | None = None,
    ) -> None:
        self.market = market
        self.strategy = strategy
        self.config = config or BacktestConfig()
        self.broker = SimBroker(
            BrokerConfig(
                fee_rate=self.config.fee_rate,
                slippage_bps=self.config.slippage_bps,
                max_participation=self.config.max_participation,
                min_notional=self.config.min_notional,
            )
        )
        self.state = _State(cash=self.config.initial_cash)
        self.index = 0
        self._equity = self.config.initial_cash
        self._equity_path: list[float] = []
        self._exposure_path: list[float] = []
        self.ctx = Context(self)

    # ---------------------------------------------------------------- helpers

    def current_time(self) -> datetime:
        ms = int(self.market.times_ms[self.index])
        return datetime.fromtimestamp(ms // 1000, tz=UTC).replace(microsecond=(ms % 1000) * 1000)

    def queue(self, order: Order) -> None:
        """One pending order per symbol; the latest intent wins."""
        order.created_index = self.index
        self.state.pending = [o for o in self.state.pending if o.symbol != order.symbol]
        self.state.pending.append(order)

    def equity(self) -> float:
        value = self.state.cash
        for symbol, position in self.state.positions.items():
            if position.is_flat:
                continue
            price = self.market.close[symbol][self.index]
            if np.isfinite(price):
                value += position.qty * price
        return value

    # -------------------------------------------------------------- main loop

    def run(self) -> BacktestResult:
        market = self.market
        equity_path: list[float] = []
        exposure_path: list[float] = []

        self.strategy.on_start(self.ctx)

        for i in range(len(market)):
            self.index = i
            now = self.current_time()

            # 1) orders decided on the previous bar fill at this bar's open
            if self.state.pending:
                self._fill_pending(i, now)

            # 2) let the strategy see the closed bar
            for symbol in market.symbols:
                if not market.valid(symbol, i):
                    continue
                o, h, low, c, v = market.bar(symbol, i)
                self.strategy.on_bar(
                    self.ctx,
                    Bar(
                        symbol=symbol,
                        open_time=now,
                        open=float(o),
                        high=float(h),
                        low=float(low),
                        close=float(c),
                        volume=float(v),
                    ),
                )

            # 3) mark to market
            equity = self.equity()
            self._equity = equity
            invested = sum(
                p.qty * market.close[s][i]
                for s, p in self.state.positions.items()
                if not p.is_flat and np.isfinite(market.close[s][i])
            )
            equity_path.append(equity)
            exposure_path.append(invested / equity if equity > 0 else 0.0)

        self.strategy.on_stop(self.ctx)

        result = BacktestResult(
            strategy=getattr(getattr(self.strategy, "spec", None), "name", "unknown"),
            symbols=market.symbols,
            params=getattr(self.strategy, "params_dict", lambda: {})(),
            initial_cash=self.config.initial_cash,
            final_equity=float(equity_path[-1]) if equity_path else self.config.initial_cash,
            times=[
                datetime.fromtimestamp(int(ms) // 1000, tz=UTC).replace(
                    microsecond=(int(ms) % 1000) * 1000
                )
                for ms in market.times_ms
            ],
            equity=equity_path,
            trades=[
                TradeRecord(
                    symbol=f.symbol,
                    side=f.side,
                    qty=f.qty,
                    price=f.price,
                    fee=f.fee,
                    time=f.time,
                    realized_pnl=f.realized_pnl,
                    reason=f.reason,
                )
                for f in self.state.fills
            ],
            bars_processed=len(market),
            exposure=float(np.mean(exposure_path)) if exposure_path else 0.0,
        )
        return result

    def _fill_pending(self, i: int, now: datetime) -> None:
        market = self.market
        for order in self.state.pending:
            if not market.valid(order.symbol, i):
                continue
            position = self.state.positions.setdefault(order.symbol, Position(symbol=order.symbol))
            fill = self.broker.execute(
                order,
                open_price=float(market.open[order.symbol][i]),
                bar_volume=float(market.volume[order.symbol][i]),
                cash=self.state.cash,
                position=position,
                now=now,
            )
            if fill is None:
                continue
            self.state.cash = self._cash_after(fill, self.state.cash)
            self.state.fills.append(fill)

        self.state.pending.clear()

    @staticmethod
    def _cash_after(fill: Fill, cash: float) -> float:
        notional = fill.qty * fill.price
        if fill.side is Side.BUY:
            return cash - notional - fill.fee
        return cash + notional - fill.fee
