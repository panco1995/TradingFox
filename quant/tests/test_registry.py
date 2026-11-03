from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from quant.strategies import registry


def test_builtin_strategies_are_discovered():
    assert set(registry.names()) >= {"ma_cross", "donchian", "bollinger_rsi", "supertrend"}


def test_describe_all_contains_param_schema_for_the_ui():
    specs = {item["name"]: item for item in registry.describe_all()}
    ma = specs["ma_cross"]

    assert ma["title"]
    assert ma["params_schema"]["properties"]["fast"]["type"] == "integer"
    assert ma["defaults"]["fast"] == 20
    # must be serialisable: the Go API forwards this verbatim
    json.dumps(ma["params_schema"])


def test_build_validates_and_coerces_params():
    strategy = registry.build("ma_cross", {"fast": "10", "slow": "30"})
    assert strategy.params.fast == 10
    assert strategy.params.slow == 30
    assert strategy.params.model_dump()["fast"] == 10


def test_build_rejects_invalid_params():
    with pytest.raises(ValidationError):
        registry.build("ma_cross", {"fast": 100, "slow": 20})


def test_unknown_strategy_raises():
    with pytest.raises(KeyError, match="unknown strategy"):
        registry.build("does_not_exist", {})


def test_every_strategy_has_metadata():
    for item in registry.describe_all():
        assert item["name"]
        assert item["title"]
        assert item["description"]
        assert item["params_schema"]["type"] == "object"
