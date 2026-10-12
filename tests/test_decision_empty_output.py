
"""An omitted decision is completed coding with QA, never confirmed absence."""
import json

import pytest
from test_decision_style import capture_run, make_study

from qualframe.empty_output_review import append_empty_output_action
from qualframe.evidence_review import write_evidence_review_index
from qualframe.study_progress import transcript_progress


def _prepared(tmp_path, monkeypatch, split="full_codebook", omitted=tuple("ABCD")):
    project, method = make_study(tmp_path, "decide_each_code", split)
    runner, plan, manifest_path, calls = capture_run(monkeypatch, project, omitted=omitted)
    write_evidence_review_index(project_manifest_path=project, run_id="synthetic-run")
    run_root = manifest_path.parent
    review_root = tmp_path / runner.project.paths["review_queue"] / "synthetic-run"
    manifest = json.loads(manifest_path.read_text())
    artifact_path = run_root / manifest["artifact_paths"][0]
    return run_root, review_root, artifact_path, method


@pytest.mark.parametrize("split", ["full_codebook", "custom_groups", "per_top_level_category"])
def test_all_omitted_decisions_complete_coding_without_empty_review(tmp_path, monkeypatch, split):
    run_root, review_root, artifact_path, method = _prepared(tmp_path, monkeypatch, split)
    state, = transcript_progress(run_root, review_root, [], tmp_path)
    assert state["completed"] and state["coding"] == "Coding complete"
    assert state["no_decision_count"] == 4
    assert state["total"] == 0 and not state["reviewed"]
    assert state["empty_state"] == "not_applicable"
    assert state["empty_binding"] is None and not state["empty_eligible"]
    assert "No decision was returned for 4 requested codes" in state["empty_issue"]
    with pytest.raises(ValueError, match="No decision was returned"):
        append_empty_output_action(
            repo_root=tmp_path, run_root=run_root, review_root=review_root,
            source_path=state["path"], expected_binding="unused",
            decision="confirm_empty", reviewer="Synthetic researcher",
            rationale="Missing decisions cannot confirm absence.",
        )


def test_one_empty_part_does_not_invalidate_other_decisions(tmp_path, monkeypatch):
    run_root, review_root, artifact_path, method = _prepared(
        tmp_path, monkeypatch, "custom_groups", tuple("BD")
    )
    state, = transcript_progress(run_root, review_root, [], tmp_path)
    assert state["completed"] and state["no_decision_count"] == 2
    assert state["total"] == 2 and not state["empty_eligible"]


@pytest.mark.parametrize("raw", [
    "No applicable codes.",
    '{"codings": []}',
    '{"decisions": [',
    '{"decisions": [{"code_id":"A","present":false,"quote":"","rationale":"Synthetic"}]}',
])
def test_an_empty_parsed_list_still_requires_the_correct_raw_decision_object(tmp_path, monkeypatch, raw):
    run_root, review_root, artifact_path, method = _prepared(tmp_path, monkeypatch)
    artifact = json.loads(artifact_path.read_text())
    artifact["response_text"] = raw
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    state, = transcript_progress(run_root, review_root, [], tmp_path)
    assert not state["completed"] and not state["empty_eligible"]


def test_each_empty_partition_requires_its_omission_audit(tmp_path, monkeypatch):
    run_root, review_root, artifact_path, method = _prepared(tmp_path, monkeypatch, "custom_groups")
    artifact = json.loads(artifact_path.read_text())
    del artifact["no_decisions"]["second"]
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    state, = transcript_progress(run_root, review_root, [], tmp_path)
    assert not state["completed"]
    assert "missing-code audit" in state["empty_issue"]


def test_empty_decision_contract_is_bound_to_frozen_method(tmp_path, monkeypatch):
    run_root, review_root, artifact_path, method = _prepared(tmp_path, monkeypatch)
    method.write_text(method.read_text() + "\n# Changed synthetic method\n", encoding="utf-8")
    state, = transcript_progress(run_root, review_root, [], tmp_path)
    assert not state["completed"]
    assert "frozen method changed" in state["empty_issue"]
