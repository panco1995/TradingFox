"""The status view must explain why a configured symbol is not being collected.

A collector started with explicit --symbol flags ignores symbols.json. Without a
warning the admin UI merely shows those pairs as "not subscribed", which reads
like a bug rather than a stale process.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from quant.data.heartbeat import write_heartbeat
from quant.data.subscriptions import _write


def _beat(symbols: list[str], follows: bool, root) -> None:
    write_heartbeat(
        {
            "state": "running",
            "heartbeat_at": datetime.now(UTC).isoformat(),
            "symbols": symbols,
            "follows_config": follows,
            "pid": os.getpid(),
            "interval": "1m",
        },
        root=root,
    )


def test_warns_when_running_symbols_differ_from_config(tmp_path, monkeypatch):
    from quant import cli

    _write(["BTCUSDT", "ETHUSDT", "SOLUSDT"], tmp_path)
    _beat(["BTCUSDT", "ETHUSDT"], follows=False, root=tmp_path)

    captured = {}

    def fake_echo(text: str) -> None:
        captured["payload"] = json.loads(text)

    monkeypatch.setattr(cli.typer, "echo", fake_echo)
    monkeypatch.setattr(cli, "symbol_coverage", lambda **_: [])

    cli.status(data_dir=tmp_path, interval="1m", as_json=True)

    payload = captured["payload"]
    assert payload["configured_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert "SOLUSDT" in payload["warning"]
    assert payload["collector"]["follows_config"] is False


def test_no_warning_when_everything_matches(tmp_path, monkeypatch):
    from quant import cli

    _write(["BTCUSDT", "ETHUSDT"], tmp_path)
    _beat(["BTCUSDT", "ETHUSDT"], follows=True, root=tmp_path)

    captured = {}
    monkeypatch.setattr(cli.typer, "echo", lambda t: captured.update(payload=json.loads(t)))
    monkeypatch.setattr(cli, "symbol_coverage", lambda **_: [])

    cli.status(data_dir=tmp_path, interval="1m", as_json=True)

    assert "warning" not in captured["payload"]


def test_no_warning_when_collector_is_down(tmp_path, monkeypatch):
    from quant import cli

    _write(["BTCUSDT", "SOLUSDT"], tmp_path)
    # A stale heartbeat must be reported as "not running", not as a mismatch.
    write_heartbeat(
        {
            "state": "running",
            "heartbeat_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            "symbols": ["BTCUSDT"],
            "pid": 1,
            "interval": "1m",
        },
        root=tmp_path,
    )

    captured = {}
    monkeypatch.setattr(cli.typer, "echo", lambda t: captured.update(payload=json.loads(t)))
    monkeypatch.setattr(cli, "symbol_coverage", lambda **_: [])

    cli.status(data_dir=tmp_path, interval="1m", as_json=True)

    payload = captured["payload"]
    assert payload["collector"]["running"] is False
    assert "warning" not in payload
