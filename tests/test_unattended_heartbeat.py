from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_unattended import _answer, _fake_provider, _study

import qualframe.unattended as unattended
from qualframe.cost_control import CostApprovalRequired
from qualframe.pipeline.project_runner import ProjectRunner


def _planned(project, run_id="synthetic-heartbeat"):
    runner = ProjectRunner(project)
    runner.save_run_plan(runner.build_run_plan(), run_id)
    return project.parent / "artifacts" / run_id


def _heartbeat(run_root, age=0):
    (run_root / "heartbeat.json").write_text(json.dumps({
        "pid": os.getpid(),
        "timestamp_utc": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
    }), encoding="utf-8")


def _execute(project, run_root):
    return unattended.execute(project, run_root.name, actor="Tester", rationale="Synthetic test",
                              say=lambda _: None, every_seconds=3600)


def _failed_request(project, run_root, monkeypatch):
    def fail(_):
        raise RuntimeError("Synthetic connection failure")
    _fake_provider(monkeypatch, fail)
    with pytest.raises(unattended.RunStopped) as caught:
        _execute(project, run_root)
    return caught.value


def test_live_request_is_in_flight_and_cannot_be_confirmed_or_run_twice(tmp_path, monkeypatch):
    project = _study(tmp_path)
    run_root = _planned(project)

    def inspect_live_request(n):
        heartbeat = json.loads((run_root / "heartbeat.json").read_text(encoding="utf-8"))
        assert heartbeat["pid"] == os.getpid()
        assert datetime.fromisoformat(heartbeat["timestamp_utc"]).utcoffset() == timedelta(0)
        status = unattended.run_status(project, run_root.name)
        assert status["status"] == "running"
        assert status["unresolved_requests"] == []
        [pending] = status["in_flight_requests"]
        assert pending["run_id"] == run_root.name
        with pytest.raises(ValueError, match="Cannot confirm.*running"):
            unattended.confirm_request(project, pending["request_id"], charged="no", actor="Tester")
        with pytest.raises(ValueError, match="already running"):
            _execute(project, run_root)
        assert unattended.run_status(project, run_root.name)["in_flight_requests"] == [pending]
        return _answer(n)

    calls = _fake_provider(monkeypatch, inspect_live_request)
    summary = _execute(project, run_root)
    assert len(calls) == 2
    assert summary["status"] in {"completed", "awaiting_review"}
    assert summary["in_flight_requests"] == summary["unresolved_requests"] == []
    assert not (run_root / "heartbeat.json").exists()
    assert not list(run_root.glob(".heartbeat-*.tmp"))
    assert len(list(run_root.glob("execution-approval-*.json"))) == 1


def test_heartbeat_refreshes_independently_of_infrequent_progress(tmp_path, monkeypatch):
    project = _study(tmp_path)
    run_root = _planned(project)
    refreshed = threading.Event()
    stamps = []
    real_write = unattended._write_heartbeat

    def track_write(root):
        real_write(root)
        stamps.append(json.loads((root / "heartbeat.json").read_text())["timestamp_utc"])
        if len(stamps) >= 2:
            refreshed.set()

    monkeypatch.setattr(unattended, "_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(unattended, "_write_heartbeat", track_write)

    def wait_for_refresh(n):
        assert refreshed.wait(5), "Heartbeat did not refresh while the provider was busy"
        return _answer(n)

    _fake_provider(monkeypatch, wait_for_refresh)
    lines = []
    unattended.execute(project, run_root.name, actor="Tester", rationale="Synthetic test",
                       say=lines.append, every_seconds=3600)
    assert stamps[1] > stamps[0]
    assert lines == []
    assert not (run_root / "heartbeat.json").exists()


@pytest.mark.parametrize("payload", [
    "{broken", "[]", "null", "{}",
    json.dumps({"pid": True, "timestamp_utc": "2026-01-01T00:00:00+00:00"}),
    json.dumps({"pid": 0, "timestamp_utc": "2026-01-01T00:00:00+00:00"}),
    json.dumps({"pid": "123", "timestamp_utc": "2026-01-01T00:00:00+00:00"}),
    json.dumps({"pid": 123, "timestamp_utc": None}),
    json.dumps({"pid": 123, "timestamp_utc": "bad-date"}),
    json.dumps({"pid": 123, "timestamp_utc": "2026-01-01T00:00:00"}),
])
def test_malformed_heartbeat_never_establishes_a_live_run(tmp_path, payload):
    (tmp_path / "heartbeat.json").write_text(payload, encoding="utf-8")
    assert not unattended._heartbeat_is_fresh(tmp_path)


@pytest.mark.parametrize("age, expected", [(0, True), (119.999, True), (120, False), (121, False), (-1, False)])
def test_freshness_boundary_is_strictly_under_two_minutes(tmp_path, monkeypatch, age, expected):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(unattended, "datetime", FixedDateTime)
    (tmp_path / "heartbeat.json").write_text(json.dumps({
        "pid": 123, "timestamp_utc": (now - timedelta(seconds=age)).isoformat(),
    }), encoding="utf-8")
    assert unattended._heartbeat_is_fresh(tmp_path) is expected


def test_dead_run_requires_confirmation_and_other_runs_do_not_inherit_its_requests(tmp_path, monkeypatch):
    project = _study(tmp_path)
    failed_root = _planned(project, "synthetic-failed")
    stopped = _failed_request(project, failed_root, monkeypatch)
    assert stopped.status == stopped.summary["status"] == "failed_request_needs_confirmation"
    assert stopped.summary["in_flight_requests"] == []
    assert not (failed_root / "heartbeat.json").exists()
    [pending] = stopped.summary["unresolved_requests"]
    other_root = _planned(project, "synthetic-other")
    other_status = unattended.run_status(project, other_root.name)
    assert other_status["status"] == "stopped"
    assert other_status["in_flight_requests"] == other_status["unresolved_requests"] == []
    _heartbeat(other_root)
    assert unattended.run_status(project, other_root.name)["in_flight_requests"] == []
    # A different active run does not prevent confirmation of this stopped request.
    _heartbeat(failed_root, age=121)
    assert unattended.run_status(project, failed_root.name)["status"] == "failed_request_needs_confirmation"
    unattended.confirm_request(project, pending["request_id"], charged="no", actor="Tester")
    assert unattended.run_status(project, failed_root.name)["unresolved_requests"] == []


def test_fresh_heartbeat_refuses_confirmation_even_without_a_lock(tmp_path, monkeypatch):
    project = _study(tmp_path)
    run_root = _planned(project)
    stopped = _failed_request(project, run_root, monkeypatch)
    [pending] = stopped.summary["unresolved_requests"]
    _heartbeat(run_root)
    status = unattended.run_status(project, run_root.name)
    assert status["status"] == "running" and status["in_flight_requests"] == [pending]
    with pytest.raises(ValueError, match="Cannot confirm.*running"):
        unattended.confirm_request(project, pending["request_id"], charged="maximum", actor="Tester")
    # A malformed heartbeat left after a crash does not block reconciliation.
    (run_root / "heartbeat.json").write_text("broken", encoding="utf-8")
    unattended.confirm_request(project, pending["request_id"], charged="no", actor="Tester")


def test_os_lock_blocks_start_and_confirmation_when_heartbeat_is_missing(tmp_path, monkeypatch):
    project = _study(tmp_path)
    run_root = _planned(project)
    stopped = _failed_request(project, run_root, monkeypatch)
    [pending] = stopped.summary["unresolved_requests"]
    with unattended._run_lock(run_root, "busy"):
        assert not (run_root / "heartbeat.json").exists()
        with pytest.raises(ValueError, match="already running"):
            _execute(project, run_root)
        with pytest.raises(ValueError, match="Cannot confirm.*running"):
            unattended.confirm_request(project, pending["request_id"], charged="no", actor="Tester")
    unattended.confirm_request(project, pending["request_id"], charged="no", actor="Tester")


@pytest.mark.parametrize("failure", ["ordinary", "pause", "interrupt"])
def test_cleanup_precedes_error_summaries_and_releases_lock(tmp_path, monkeypatch, failure):
    project = _study(tmp_path)
    run_root = _planned(project)

    def fail(self, plan, run_id):
        assert unattended.run_status(project, run_id)["status"] == "running"
        if failure == "pause":
            pause = run_root / "cost_pause.json"
            pause.write_text(json.dumps({"threshold_usd": 20}), encoding="utf-8")
            raise CostApprovalRequired(SimpleNamespace(threshold_usd=20), pause)
        if failure == "interrupt":
            raise KeyboardInterrupt()
        raise RuntimeError("Synthetic failure before a request")

    monkeypatch.setattr(ProjectRunner, "execute_run_plan", fail)
    expected = KeyboardInterrupt if failure == "interrupt" else unattended.RunStopped
    with pytest.raises(expected) as caught:
        _execute(project, run_root)
    if failure != "interrupt":
        expected_status = "paused_for_spending_check" if failure == "pause" else "failed"
        assert caught.value.status == caught.value.summary["status"] == expected_status
        assert caught.value.summary["in_flight_requests"] == []
    assert not (run_root / "heartbeat.json").exists()
    with unattended._run_lock(run_root, "not released"):
        pass


def test_status_prioritizes_fresh_heartbeat_and_approved_pause_is_stopped(tmp_path):
    project = _study(tmp_path)
    run_root = _planned(project)
    (run_root / "cost_pause.json").write_text(json.dumps({"threshold_usd": 20}), encoding="utf-8")
    assert unattended.run_status(project, run_root.name)["status"] == "paused_for_spending_check"
    unattended.preapprove_spending(project, up_to=20, actor="Tester", rationale="Synthetic test", run_id=run_root.name)
    assert unattended.run_status(project, run_root.name)["status"] == "stopped"
    (run_root / "run_manifest.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    _heartbeat(run_root)
    assert unattended.run_status(project, run_root.name)["status"] == "running"
    _heartbeat(run_root, age=121)
    assert unattended.run_status(project, run_root.name)["status"] == "completed"


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_invalid_progress_interval_does_not_start_a_run(tmp_path, interval):
    project = _study(tmp_path)
    run_root = _planned(project)
    with pytest.raises(ValueError, match="positive, finite"):
        unattended.execute(project, run_root.name, actor="Tester", rationale="Synthetic test", every_seconds=interval)
    assert not (run_root / "heartbeat.json").exists()
    assert not list(run_root.glob("execution-approval-*.json"))


def test_new_starts_with_the_same_clock_id_preserve_existing_run_files(tmp_path, monkeypatch):
    project = _study(tmp_path)
    _fake_provider(monkeypatch, _answer)
    monkeypatch.setattr(ProjectRunner, "_make_run_id", lambda self: "synthetic-same-second")
    first = unattended.start(project, actor="Tester", rationale="Synthetic first run", say=lambda _: None)
    first_root = project.parent / "artifacts" / first["run_id"]
    original = {name: (first_root / name).read_bytes() for name in ("run_plan.json", "run_manifest.json")}
    second = unattended.start(project, actor="Tester", rationale="Synthetic second run", say=lambda _: None)
    assert first["run_id"] == "synthetic-same-second"
    assert second["run_id"].startswith("synthetic-same-second-")
    assert all((first_root / name).read_bytes() == contents for name, contents in original.items())
    assert second["transcripts_done"] == 2
