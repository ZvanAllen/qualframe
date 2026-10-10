import copy
import pytest
from test_reviewed_analysis import prepared, decide
from qualframe.reviewed_analysis import freeze_reviewed_snapshot, load_snapshot
from qualframe.synthesis_plan import (
    build_synthesis_plan,
    write_synthesis_plan,
    validate_synthesis_response,
)
from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.analysis_ui import render_analysis


def reviewed(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    for record in records:
        decide(project, root, review, record)
    path = freeze_reviewed_snapshot(project.parents[2], root, review, "Researcher")
    return project, run_id, root, review, records, path


def test_synthesis_plan_freezes_grouping_and_only_retained_evidence(tmp_path):
    project, run_id, root, review, records, path = reviewed(tmp_path)
    decide(project, root, review, records[0], "reject")
    with pytest.raises(ValueError, match="Freeze current"):
        build_synthesis_plan(project.parents[2], root, review, path, "per_transcript")
    path = freeze_reviewed_snapshot(project.parents[2], root, review, "Researcher")
    plan = build_synthesis_plan(project.parents[2], root, review, path, "per_transcript")
    assert len(plan["calls"]) == 2
    assert sum(len(c["input"]["evidence"]) for c in plan["calls"]) == 3
    assert all(
        e["evidence_id"] != records[0].record_id
        for c in plan["calls"]
        for e in c["input"]["evidence"]
    )
    pooled = build_synthesis_plan(project.parents[2], root, review, path, "selected_cohort")
    assert len(pooled["calls"]) == 1 and pooled["status"] == "prepared_only"
    output = write_synthesis_plan(
        project.parents[2], root, review, path, "per_transcript", dry_run=True
    )
    assert not output.exists()
    assert write_synthesis_plan(project.parents[2], root, review, path, "per_transcript") == output
    saved = output.read_bytes()
    assert write_synthesis_plan(project.parents[2], root, review, path, "per_transcript") == output
    assert output.read_bytes() == saved
    assert "Prepare synthesis plan" in render_analysis(DashboardApp(ProjectRunner(project)), run_id)


def test_synthesis_citations_must_belong_to_reviewed_code_and_scope(tmp_path):
    project, _, root, review, _, path = reviewed(tmp_path)
    plan = build_synthesis_plan(project.parents[2], root, review, path, "per_transcript")
    first = plan["calls"][0]
    item = first["input"]["evidence"][0]
    response = {
        "summaries": [
            {
                "code_id": item["code_id"],
                "statements": [
                    {"text": "A descriptive test statement.", "evidence_ids": [item["evidence_id"]]}
                ],
            }
        ]
    }
    validate_synthesis_response(plan, first["group_id"], response)
    for identity in [
        "invented",
        plan["calls"][1]["input"]["evidence"][0]["evidence_id"],
        first["input"]["evidence"][1]["evidence_id"],
    ]:
        invalid = copy.deepcopy(response)
        invalid["summaries"][0]["statements"][0]["evidence_ids"] = [identity]
        with pytest.raises(ValueError, match="outside its reviewed"):
            validate_synthesis_response(plan, first["group_id"], invalid)
    invalid = copy.deepcopy(response)
    invalid["summaries"][0]["statements"][0]["evidence_ids"] = []
    with pytest.raises(ValueError):
        validate_synthesis_response(plan, first["group_id"], invalid)


def test_synthesis_rejects_empty_evidence_and_stale_or_cross_study_actions(tmp_path):
    project, run_id, root, review, records, path = reviewed(tmp_path)
    dashboard = DashboardApp(ProjectRunner(project))
    form = {
        "run_id": [run_id],
        "snapshot": [load_snapshot(path)["snapshot_id"]],
        "grouping": ["selected_cohort"],
        "study_identity": ["another"],
    }
    with pytest.raises(ValueError, match="another study"):
        dashboard.handle_action("/analysis/prepare-synthesis", form)
    form["study_identity"] = [dashboard.runner.project.project_id]
    dashboard.handle_action("/analysis/prepare-synthesis", form)
    assert len(list((root / "analysis").glob("synthesis-plan-*.json"))) == 1
    for record in records:
        decide(project, root, review, record, "reject")
    with pytest.raises(ValueError, match="Freeze current"):
        dashboard.handle_action("/analysis/prepare-synthesis", form)
    empty = freeze_reviewed_snapshot(project.parents[2], root, review, "Researcher")
    with pytest.raises(ValueError, match="retained evidence"):
        build_synthesis_plan(project.parents[2], root, review, empty, "per_transcript")
