"""Strategy contract.

A strategy is a *code plugin* that lives in this package. The web UI can only
select a registered strategy and edit its parameters - it never uploads or
executes code. That is a deliberate security boundary.

The same class runs in backtest and live: the only difference is which Context
implementation is injected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from quant.backtest.engine import Context
    from quant.backtest.types import Bar


@dataclass(frozen=True)
class StrategySpec:
    name: str
    title: str
    description: str
    params_model: type[BaseModel]
    version: str = "0.1.0"
    tags: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class Strategy(Protocol):
    spec: ClassVar[StrategySpec]

    def on_start(self, ctx: Context) -> None: ...
    def on_bar(self, ctx: Context, bar: Bar) -> None: ...
    def on_stop(self, ctx: Context) -> None: ...


class BaseStrategy:
    """Convenience base class. Subclasses only implement `on_bar`."""

    spec: ClassVar[StrategySpec]

    def __init__(self, params: BaseModel) -> None:
        self.params = params

    def params_dict(self) -> dict:
        return self.params.model_dump()

    def on_start(self, ctx: Context) -> None:  # noqa: B027 - optional hook
        pass

    def on_bar(self, ctx: Context, bar: Bar) -> None:
        raise NotImplementedError

    def on_stop(self, ctx: Context) -> None:  # noqa: B027 - optional hook
        pass
