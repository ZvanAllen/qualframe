from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualframe.config import load_stage_output_spec
from qualframe.io.export import export_run
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.structured_output import validate_stage_output


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PROJECT = REPO_ROOT / "demo/project/project_demo.yaml"
SPEC_PATH = REPO_ROOT / "config/schemas/cfir_stage_outputs_v1.yaml"


def test_stage_specific_validation_reports_missing_columns() -> None:
    spec = load_stage_output_spec(SPEC_PATH)
    issues = validate_stage_output(
        "cross_network_synthesis",
        {"Implementation Process": [{"CFIR Domain": "Implementation Process"}]},
        spec,
    )
    assert len(issues) == 1
    assert "CFIR Construct" in issues[0]
    assert "Neutral/Unclear Networks" in issues[0]


def test_enforced_structured_output_stops_invalid_mock_run_and_blocks_export(
    tmp_path: Path,
) -> None:
    runner = ProjectRunner(DEMO_PROJECT)
    runner.project.provider.name = "mock"
    runner.project.structured_output.enforce = True
    runner.structured_output_spec = load_stage_output_spec(SPEC_PATH)
    runner.project.paths["artifacts"] = str(tmp_path / "artifacts")
    runner.project.paths["review_queue"] = str(tmp_path / "review_queue")
    runner.project.paths["exports"] = str(tmp_path / "exports")
    run_id = "invalid-structured-output"
    plan = runner.build_run_plan()

    manifest_path = runner.execute_run_plan(plan, run_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "blocked_validation"
    assert manifest["structured_output_failure_count"] == 2
    assert len(manifest["artifact_paths"]) == 2
    assert not (manifest_path.parent / "participant_parent_construct_rollup").exists()

    for rel_path in manifest["artifact_paths"]:
        artifact = json.loads((manifest_path.parent / rel_path).read_text(encoding="utf-8"))
        assert artifact["structured_output_valid"] is False
        assert "MOCK RESPONSE" in artifact["response_text"]
        assert artifact["structured_output_issues"]

    review_items = list((tmp_path / "review_queue" / run_id).glob("*.json"))
    assert len(review_items) == 2
    with pytest.raises(PermissionError, match="structured-output"):
        export_run(
            run_id,
            manifest_path.parent,
            tmp_path / "exports",
            require_validated=True,
        )
