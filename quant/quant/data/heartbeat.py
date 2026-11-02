"""Collector heartbeat.

The admin UI runs in a different process (and may be on a different machine),
so it cannot ask the collector directly whether it is alive. Instead the
collector rewrites a small JSON file every few seconds, and readers treat a
stale file as "not running" — that also covers a process that was killed
without a chance to clean up.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant.config import data_root

HEARTBEAT_FILENAME = "collector-status.json"
DEFAULT_HEARTBEAT_SECONDS = 5.0
#: A heartbeat older than this is treated as a dead process.
STALE_AFTER_SECONDS = 20.0


def heartbeat_path(root: Path | None = None) -> Path:
    return (root or data_root()) / "meta" / HEARTBEAT_FILENAME


def write_heartbeat(payload: dict[str, Any], root: Path | None = None) -> Path:
    """Atomically replace the heartbeat so a reader never sees a partial file."""
    path = heartbeat_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_heartbeat(root: Path | None = None) -> dict[str, Any] | None:
    try:
        raw = heartbeat_path(root).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def heartbeat_age_seconds(
    payload: dict[str, Any] | None, now: datetime | None = None
) -> float | None:
    if not payload:
        return None
    beat = parse_iso(payload.get("heartbeat_at"))
    if beat is None:
        return None
    return max(0.0, ((now or datetime.now(UTC)) - beat).total_seconds())


def is_running(
    payload: dict[str, Any] | None,
    now: datetime | None = None,
    stale_after: float = STALE_AFTER_SECONDS,
) -> bool:
    if not payload or payload.get("state") != "running":
        return False
    age = heartbeat_age_seconds(payload, now)
    return age is not None and age <= stale_after
