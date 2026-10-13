from __future__ import annotations

import json

import pytest
from test_evidence_review import _completed_synthetic_run

from qualframe.dashboard import DashboardApp
from qualframe.empty_output_review import (
    _digest,
    append_empty_output_action,
    empty_output_state,
    load_empty_output_actions,
)
from qualframe.empty_output_ui import handle_empty_output_action, render_empty_output_review
from qualframe.evidence_review import write_evidence_review_index
from qualframe.io.response_parser import parse_markdown_tables, strict_empty_tables
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.base import LLMResponse, LLMUsage
from qualframe.reviewed_analysis import freeze_reviewed_snapshot, load_snapshot, snapshot_freshness
from qualframe.study_progress import transcript_progress

EMPTY = """## Sheet: Coding
| Meaning Unit ID | Evidence Start | Evidence End | Exact Evidence | Code ID | Rationale |
| --- | --- | --- | --- | --- | --- |
"""


class EmptyProvider:
    def complete(self, **kwargs):
        return LLMResponse(
            text=EMPTY,
            provider="mock",
            model="mock-v1",
            usage=LLMUsage(input_tokens=10, output_tokens=10),
        )


def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qualframe.pipeline.project_runner.build_provider", lambda *args: EmptyProvider()
    )
    project, run_id, root, review = _completed_synthetic_run(tmp_path)
    write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    return project, run_id, root, review


def decide(project, root, review, state, decision="confirm_empty", **kwargs):
    return append_empty_output_action(
        repo_root=project.parents[2],
        run_root=root,
        review_root=review,
        source_path=state["path"],
        expected_binding=_digest(state["empty_binding"]),
        reviewer="Researcher",
        rationale="Reviewed the synthetic source with the codebook.",
        decision=decision,
        **kwargs,
    )


def test_valid_empty_table_is_parsed_but_prose_and_malformed_tables_are_not():
    assert parse_markdown_tables(EMPTY) == {"Coding": []}
    assert len(strict_empty_tables(EMPTY)) == 1
    for malformed in [
        "",
        "No relevant evidence.",
        EMPTY.replace("| --- |", "| not separator |", 1),
        EMPTY + "| | | | | | |",
        EMPTY + "Unfinished answer",
        "```markdown\n" + EMPTY,
        EMPTY.replace("Evidence Start", ""),
        EMPTY.replace("Evidence Start", "Code ID"),
    ]:
        assert strict_empty_tables(malformed) == []


def test_empty_checkpoint_is_explicit_append_only_and_snapshot_bound(tmp_path, monkeypatch):
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    rows = transcript_progress(root, review, [], project.parents[2])
    assert len(rows) == 2 and all(
        r["completed"] and r["empty_eligible"] and not r["reviewed"] for r in rows
    )
    with pytest.raises(ValueError, match="Complete coding and review"):
        freeze_reviewed_snapshot(project.parents[2], root, review, "Researcher")
    source = rows[0]["path"]
    dry = decide(project, root, review, rows[0], dry_run=True)
    assert dry["binding"]["artifacts"] and not load_empty_output_actions(review)
    decide(project, root, review, rows[0], "defer")
    assert not empty_output_state(project.parents[2], root, review, source)["reviewed"]
    decide(project, root, review, rows[0], "needs_recoding")
    assert not empty_output_state(project.parents[2], root, review, source)["reviewed"]
    final = decide(project, root, review, rows[0])
    path = freeze_reviewed_snapshot(
        project.parents[2], root, review, "Researcher", selected_sources=[source]
    )
    snapshot = load_snapshot(path)
    assert snapshot["payload"]["evidence"] == []
    assert snapshot["payload"]["absences"] == []
    assert snapshot["payload"]["empty_output_decisions"] == [final]
    assert len(snapshot["payload"]["empty_output_history"]) == 3
    assert len(snapshot["payload"]["excluded_source_paths"]) == 1
    assert snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    # Excluded-source review decisions cannot change the frozen cohort.
    decide(project, root, review, rows[1])
    assert snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    decide(project, root, review, rows[0], "defer")
    assert not snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    assert len(load_empty_output_actions(review)) == 5


def test_changed_artifact_source_and_stale_page_invalidate_empty_decision(tmp_path, monkeypatch):
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    state = transcript_progress(root, review, [], project.parents[2])[0]
    decide(project, root, review, state)
    path = freeze_reviewed_snapshot(
        project.parents[2], root, review, "Researcher", selected_sources=[state["path"]]
    )
    snapshot = load_snapshot(path)
    artifact = root / state["empty_binding"]["artifacts"][0]["path"]
    original = artifact.read_bytes()
    artifact.write_bytes(original + b" ")
    current = empty_output_state(project.parents[2], root, review, state["path"])
    assert current["empty_state"] == "stale" and not current["reviewed"]
    assert not snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    with pytest.raises(ValueError, match="changed after this page"):
        decide(project, root, review, state)
    artifact.write_bytes(original)
    source = project.parents[2] / state["path"]
    source.write_text("Changed synthetic input.", encoding="utf-8")
    assert not empty_output_state(project.parents[2], root, review, state["path"])["empty_eligible"]
    with pytest.raises(ValueError, match="source changed"):
        decide(project, root, review, state)


@pytest.mark.parametrize(
    "response",
    ["No relevant evidence.", EMPTY.replace("Code ID", "Wrong Header"), EMPTY + "| | | | | | |"],
)
def test_legacy_empty_lists_do_not_turn_failed_parsing_into_empty_review(
    tmp_path, monkeypatch, response
):
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact = root / manifest["artifact_paths"][0]
    value = json.loads(artifact.read_text(encoding="utf-8"))
    # Simulate the older CFIR-style fallback: empty rows regardless of raw parsing.
    value["parsed_output"] = {"Coding": []}
    value["response_text"] = response
    artifact.write_text(json.dumps(value), encoding="utf-8")
    state = empty_output_state(project.parents[2], root, review, value["input_path"])
    assert not state["completed"] and not state["empty_eligible"] and not state["reviewed"]


def test_empty_ui_enforces_study_binding_and_source_confirmation(tmp_path, monkeypatch):
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    app = DashboardApp(ProjectRunner(project))
    state = transcript_progress(root, review, [], project.parents[2])[0]
    page = render_empty_output_review(app, run_id, state["path"])
    assert (
        "Confirm zero proposals" in page
        and "Needs new coding" in page
        and "Original model output" in page
    )
    form = {
        k: [v]
        for k, v in dict(
            run_id=run_id,
            source=state["path"],
            binding=_digest(state["empty_binding"]),
            reviewer="Researcher",
            rationale="Synthetic review.",
            decision="confirm_empty",
            study_identity=app.runner.project.project_id,
        ).items()
    }
    with pytest.raises(ValueError, match="Confirm that you reviewed"):
        handle_empty_output_action(app, form)
    form["source_checked"] = ["yes"]
    form["study_identity"] = ["other"]
    with pytest.raises(ValueError, match="another study"):
        handle_empty_output_action(app, form)
    form["study_identity"] = [app.runner.project.project_id]
    assert handle_empty_output_action(app, form)[0] == run_id
    assert (
        json.loads((app.review_dir / "reviewer.json").read_text(encoding="utf-8"))["name"]
        == "Researcher"
    )
    assert "Decision history (1)" in render_empty_output_review(app, run_id, state["path"])


def test_each_declared_partition_needs_a_valid_response(tmp_path, monkeypatch):
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    plan_path = root / "run_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    first = plan["planned_stage_runs"][0]
    source = first["input_path"]
    plan["planned_stage_runs"] = [dict(first, domain="A"), dict(first, domain="B")] + [
        call for call in plan["planned_stage_runs"] if call["input_path"] != source
    ]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact_path = next(
        root / rel
        for rel in manifest["artifact_paths"]
        if json.loads((root / rel).read_text(encoding="utf-8"))["input_path"] == source
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["parsed_output"] = {"A: Coding": [], "B: Coding": []}
    artifact["response_text"] = f"## Partition: A\n\n{EMPTY}\n\n## Partition: B\n\n{EMPTY}"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert empty_output_state(project.parents[2], root, review, source)["empty_eligible"]
    artifact["response_text"] = f"## Partition: A\n\n{EMPTY}\n\n## Partition: B\n\nNo rows found."
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    assert not empty_output_state(project.parents[2], root, review, source)["completed"]


def test_an_empty_json_answer_for_one_partition_counts_as_complete(tmp_path, monkeypatch):
    # A partitioned run in which one part found nothing ({"codings": []}) is still complete.
    project, run_id, root, review = prepared(tmp_path, monkeypatch)
    plan_path = root / "run_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    first = plan["planned_stage_runs"][0]
    source = first["input_path"]
    plan["planned_stage_runs"] = [dict(first, domain="A"), dict(first, domain="B")] + [
        call for call in plan["planned_stage_runs"] if call["input_path"] != source
    ]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact_path = next(
        root / rel
        for rel in manifest["artifact_paths"]
        if json.loads((root / rel).read_text(encoding="utf-8"))["input_path"] == source
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    row = {"Meaning Unit ID": "mu-1", "Exact Evidence": "x", "Code ID": "a", "Rationale": "r"}
    artifact["parsed_output"] = {"A: Directed Coding": [], "B: Directed Coding": [row]}
    artifact["response_text"] = (
        '## Partition: A\n\n{"codings": []}\n\n## Partition: B\n\n'
        '{"codings": [{"meaning_unit": "mu-1", "quote": "x", "code_id": "a", "rationale": "r"}]}'
    )
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    progress = {row["path"]: row for row in transcript_progress(root, review, [], project.parents[2])}
    assert "cannot be confirmed empty" not in progress[source]["empty_issue"]
    # Unparsed text for a part is still not accepted as empty.
    artifact["response_text"] = artifact["response_text"].replace('{"codings": []}', "Nothing relevant.")
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    progress = {row["path"]: row for row in transcript_progress(root, review, [], project.parents[2])}
    assert "cannot be confirmed empty" in progress[source]["empty_issue"] and not progress[source]["completed"]
