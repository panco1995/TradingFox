"""Failures must be readable by both a human and the Go API.

The API runs `python -m quant.cli ... --json` and uses the child's **stderr** as
the message it shows in the web UI. When the CLI printed errors with
`console.print` they went to stdout, stderr stayed empty, and the user saw the
useless "exit status 2" after changing a parameter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from quant import cli
from quant.data.store import write_bars

runner = CliRunner()


@pytest.fixture
def store(bars_factory, tmp_path):
    """Enough 1m history that the backtest can actually run."""
    write_bars(bars_factory(400, start=datetime(2026, 3, 1, tzinfo=UTC)), "BTCUSDT", root=tmp_path)
    return tmp_path


def _invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def test_cross_field_param_error_goes_to_stderr():
    result = _invoke(
        "backtest",
        "--strategy",
        "donchian",
        "--symbol",
        "BTCUSDT",
        "--days",
        "30",
        "--param",
        "entry_window=20",
        "--param",
        "exit_window=30",
        "--json",
    )

    assert result.exit_code == 2
    assert "退出周期必须小于突破周期" in result.stderr
    # stdout must stay a clean, parseable error envelope for the API.
    assert json.loads(result.stdout.strip())["error"]


def test_out_of_range_param_names_the_field():
    result = _invoke(
        "backtest",
        "--strategy",
        "ma_cross",
        "--symbol",
        "BTCUSDT",
        "--days",
        "30",
        "--param",
        "fast=9999",
        "--json",
    )

    assert result.exit_code == 2
    assert "fast" in result.stderr
    assert "不能大于 1000" in result.stderr


def test_unparsable_param_says_it_needs_a_number():
    result = _invoke(
        "backtest",
        "--strategy",
        "ma_cross",
        "--symbol",
        "BTCUSDT",
        "--days",
        "30",
        "--param",
        "fast=abc",
        "--json",
    )

    assert result.exit_code == 2
    assert "entry_window" not in result.stderr
    assert "需要整数" in result.stderr


def test_unknown_strategy_is_reported_without_python_noise():
    result = _invoke("backtest", "--strategy", "nope", "--days", "30", "--json")

    assert result.exit_code == 2
    assert "unknown strategy: nope" in result.stderr
    # The KeyError repr (quotes) would look like a bug rather than a typo.
    assert "'unknown strategy" not in result.stderr


def test_missing_market_data_is_an_actionable_message(store):
    result = _invoke(
        "backtest",
        "--strategy",
        "donchian",
        "--symbol",
        "NODATAUSDT",
        "--days",
        "30",
        "--data-dir",
        str(store),
        "--json",
    )

    assert result.exit_code == 1
    assert "no stored bars for NODATAUSDT" in result.stderr
    # No traceback: this is a data problem, not a crash.
    assert "Traceback" not in result.stderr


def test_valid_params_still_produce_a_report(store):
    result = _invoke(
        "backtest",
        "--strategy",
        "donchian",
        "--symbol",
        "BTCUSDT",
        "--days",
        "0",
        "--start",
        "2026-03-01",
        "--end",
        "2026-03-01T06:00",
        "--param",
        "entry_window=20",
        "--param",
        "exit_window=10",
        "--data-dir",
        str(store),
        "--json",
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert payload["strategy"] == "donchian"
