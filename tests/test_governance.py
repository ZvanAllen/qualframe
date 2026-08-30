from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualframe.governance import append_gate_action, append_release_action, load_gate_actions
from qualframe.io.export import export_run
from qualframe.pipeline.project_runner import ProjectRunner


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PROJECT = REPO_ROOT / "demo" / "project" / "project_demo.yaml"


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_enforced_gates_pause_resume_and_block_export_until_release(tmp_path: Path) -> None:
    runner = ProjectRunner(DEMO_PROJECT)
    runner.project.governance.enforce_review_gates = True
    runner.project.paths["artifacts"] = str(tmp_path / "artifacts")
    runner.project.paths["review_queue"] = str(tmp_path / "review_queue")
    runner.project.paths["exports"] = str(tmp_path / "exports")
    run_id = "governed_demo"
    plan = runner.build_run_plan()

    first = runner.execute_run_plan(plan, run_id)
    first_manifest = _manifest(first)
    assert first_manifest["status"] == "awaiting_review"
    assert first_manifest["pending_gate"] == "transcript_to_cfir"
    assert len(first_manifest["artifact_paths"]) == 2

    artifact_root = first.parent
    with pytest.raises(PermissionError):
        export_run(run_id, artifact_root, tmp_path / "exports", require_released=True)

    append_gate_action(
        artifact_root,
        run_id=run_id,
        stage_id="transcript_to_cfir",
        decision="approve",
        reviewer="synthetic-reviewer",
        rationale="Synthetic fixture passed the first review gate.",
    )
    second = runner.execute_run_plan(plan, run_id)
    second_manifest = _manifest(second)
    assert second_manifest["pending_gate"] == "participant_to_network_synthesis"
    assert len(second_manifest["artifact_paths"]) == 8

    append_gate_action(
        artifact_root,
        run_id=run_id,
        stage_id="participant_to_network_synthesis",
        decision="approve",
        reviewer="synthetic-reviewer",
        rationale="Synthetic network artifacts passed review.",
    )
    third = runner.execute_run_plan(plan, run_id)
    third_manifest = _manifest(third)
    assert third_manifest["pending_gate"] == "cross_network_synthesis"
    assert third_manifest["qa_failure_count"] == 1

    append_gate_action(
        artifact_root,
        run_id=run_id,
        stage_id="cross_network_synthesis",
        decision="approve",
        reviewer="synthetic-reviewer",
        rationale="The deliberately seeded QA item is understood for this test.",
    )
    completed = runner.execute_run_plan(plan, run_id)
    completed_manifest = _manifest(completed)
    assert completed_manifest["status"] == "completed"
    assert completed_manifest["pending_gate"] is None
    assert completed_manifest["qa_failure_count"] == 1
    assert completed_manifest["release_status"] == "unreleased"

    with pytest.raises(PermissionError):
        export_run(run_id, artifact_root, tmp_path / "exports", require_released=True)

    append_release_action(
        artifact_root,
        run_id=run_id,
        reviewer="synthetic-release-reviewer",
        rationale="Release the governed synthetic test run.",
    )
    written = export_run(run_id, artifact_root, tmp_path / "exports", require_released=True)
    assert len(written) == 9
    assert len(load_gate_actions(artifact_root)) == 3
    assert _manifest(completed)["release_status"] == "released"
