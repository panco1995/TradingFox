"""Domain types shared by backtest and live trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


@dataclass(slots=True)
class Bar:
    symbol: str
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0

    @property
    def is_flat(self) -> bool:
        return abs(self.qty) < 1e-12


@dataclass
class Order:
    symbol: str
    side: Side
    qty: float | None = None  # None means "all" for sells
    reason: str = ""
    created_index: int = 0


@dataclass
class Fill:
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    time: datetime
    realized_pnl: float = 0.0
    reason: str = ""


@dataclass
class TradeRecord:
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    time: datetime
    realized_pnl: float
    reason: str


@dataclass
class BacktestResult:
    strategy: str
    symbols: list[str]
    params: dict
    initial_cash: float
    final_equity: float
    times: list[datetime]
    equity: list[float]
    trades: list[TradeRecord] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    monthly_returns: dict[str, float] = field(default_factory=dict)
    bars_processed: int = 0
    exposure: float = 0.0
