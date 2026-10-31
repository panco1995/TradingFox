"""Strategy registry.

Any module in this package that calls `@register` becomes selectable from the
web UI. Import happens by directory scan, so adding a strategy = adding a file.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from quant.strategies.base import BaseStrategy, StrategySpec

_REGISTRY: dict[str, type[BaseStrategy]] = {}
_LOADED = False

_SKIP = {"base", "registry"}


def register(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    name = cls.spec.name
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"duplicate strategy name: {name}")
    _REGISTRY[name] = cls
    return cls


def load_all(force: bool = False) -> None:
    global _LOADED
    if _LOADED and not force:
        return
    import quant.strategies as package

    for module in pkgutil.iter_modules(package.__path__):
        if module.name.startswith("_") or module.name in _SKIP:
            continue
        importlib.import_module(f"{package.__name__}.{module.name}")
    _LOADED = True


def names() -> list[str]:
    load_all()
    return sorted(_REGISTRY)


def get(name: str) -> type[BaseStrategy]:
    load_all()
    if name not in _REGISTRY:
        raise KeyError(f"unknown strategy: {name} (available: {', '.join(names())})")
    return _REGISTRY[name]


def spec(name: str) -> StrategySpec:
    return get(name).spec


def describe_all() -> list[dict[str, Any]]:
    """Everything the backend needs to render a strategy picker + param form."""
    load_all()
    out = []
    for name in sorted(_REGISTRY):
        strategy_spec = _REGISTRY[name].spec
        schema = strategy_spec.params_model.model_json_schema()
        out.append(
            {
                "name": strategy_spec.name,
                "title": strategy_spec.title,
                "description": strategy_spec.description,
                "version": strategy_spec.version,
                "tags": list(strategy_spec.tags),
                "params_schema": schema,
                "defaults": strategy_spec.params_model().model_dump(),
            }
        )
    return out


def build(name: str, params: dict[str, Any] | None = None) -> BaseStrategy:
    cls = get(name)
    validated = cls.spec.params_model(**(params or {}))
    return cls(validated)
