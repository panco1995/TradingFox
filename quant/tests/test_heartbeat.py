from datetime import UTC, datetime, timedelta

from quant.data.heartbeat import (
    STALE_AFTER_SECONDS,
    heartbeat_age_seconds,
    is_running,
    read_heartbeat,
    write_heartbeat,
)


def _payload(age_seconds: float, state: str = "running") -> dict:
    beat = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return {"state": state, "heartbeat_at": beat.isoformat()}


def test_write_and_read_roundtrip(tmp_path):
    path = write_heartbeat({"state": "running", "pid": 1234}, root=tmp_path)

    assert path == tmp_path / "meta" / "collector-status.json"
    assert read_heartbeat(tmp_path) == {"state": "running", "pid": 1234}


def test_missing_heartbeat_reads_as_none(tmp_path):
    assert read_heartbeat(tmp_path) is None
    assert is_running(None) is False


def test_corrupt_heartbeat_reads_as_none(tmp_path):
    path = tmp_path / "meta" / "collector-status.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert read_heartbeat(tmp_path) is None


def test_fresh_heartbeat_is_running():
    payload = _payload(1)
    assert heartbeat_age_seconds(payload) < 5
    assert is_running(payload) is True


def test_stale_heartbeat_is_not_running():
    # A process killed with SIGKILL leaves the file behind; age is the only
    # signal that it is gone.
    payload = _payload(STALE_AFTER_SECONDS + 5)
    assert is_running(payload) is False


def test_stopped_state_is_not_running():
    assert is_running(_payload(1, state="stopped")) is False


def test_heartbeat_without_timestamp_is_not_running():
    assert is_running({"state": "running"}) is False
    assert heartbeat_age_seconds({"state": "running"}) is None
