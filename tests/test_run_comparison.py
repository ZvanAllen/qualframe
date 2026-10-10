import copy
import json
import pytest
from test_evidence_review import _completed_synthetic_run
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.evidence_review import (
    write_evidence_review_index,
    load_evidence_review_records,
    append_evidence_review_action,
)
from qualframe.run_comparison import (
    raw_coding_payload,
    compare_raw_payloads,
    interval_overlap,
    write_comparison,
)


def runs(tmp_path):
    project, run_id, root, review = _completed_synthetic_run(tmp_path)
    write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    runner = ProjectRunner(project)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, "repeat")
    runner.execute_run_plan(plan, "repeat")
    write_evidence_review_index(project_manifest_path=project, run_id="repeat")
    return project, root, root.parent / "repeat", review


def test_identical_raw_runs_ignore_review_edits_and_freeze_idempotently(tmp_path):
    project, left, right, review = runs(tmp_path)
    before = raw_coding_payload(project.parents[2], left)
    record = load_evidence_review_records(left / "evidence_review/index.json")[0]
    append_evidence_review_action(
        record=record,
        source_path=project.parents[2] / record.source_path,
        review_dir=review,
        artifact_root=left,
        decision="reject",
        reviewer="QA",
        rationale="Synthetic review",
    )
    assert raw_coding_payload(project.parents[2], left) == before
    report = compare_raw_payloads(before, raw_coding_payload(project.parents[2], right))
    assert report["summary"] == {
        "code_jaccard": 1.0,
        "exact_span_jaccard": 1.0,
        "coverage_jaccard": 1.0,
    }
    assert len(report["transcripts"]) == 2
    path = write_comparison(project.parents[2], left, right, dry_run=True)
    assert not path.exists()
    assert write_comparison(project.parents[2], left, right) == path
    saved = path.read_bytes()
    assert write_comparison(project.parents[2], left, right) == path and path.read_bytes() == saved


def test_boundary_shift_and_empty_outputs_have_explicit_denominators(tmp_path):
    project, left, right, _ = runs(tmp_path)
    a = raw_coding_payload(project.parents[2], left)
    b = copy.deepcopy(a)
    b["run_id"] = "repeat"
    first = b["included"][0]
    first["start"] += 1
    report = compare_raw_payloads(a, b)
    assert report["summary"]["code_jaccard"] == 1
    assert 0 < report["summary"]["exact_span_jaccard"] < 1
    assert report["summary"]["exact_span_jaccard"] < report["summary"]["coverage_jaccard"] < 1
    a["included"] = []
    b["included"] = []
    assert all(v is None for v in compare_raw_payloads(a, b)["summary"].values())
    assert interval_overlap(
        [{"start": 0, "end": 10}, {"start": 5, "end": 15}], [{"start": 10, "end": 20}]
    ) == (5, 20)


def test_comparison_rejects_cohort_or_codebook_mismatch_and_artifact_drift(tmp_path):
    project, left, right, _ = runs(tmp_path)
    a = raw_coding_payload(project.parents[2], left)
    b = raw_coding_payload(project.parents[2], right)
    altered = copy.deepcopy(b)
    altered["sources"].pop(next(iter(altered["sources"])))
    with pytest.raises(ValueError, match="same transcript"):
        compare_raw_payloads(a, altered)
    altered = copy.deepcopy(b)
    altered["codebook"]["version"] = "changed"
    with pytest.raises(ValueError, match="same frozen codebook"):
        compare_raw_payloads(a, altered)
    with pytest.raises(ValueError, match="distinct runs"):
        compare_raw_payloads(a, a)
    record = load_evidence_review_records(left / "evidence_review/index.json")[0]
    artifact = left / record.artifact_path
    artifact.write_bytes(artifact.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact changed"):
        raw_coding_payload(project.parents[2], left)


def test_invalid_and_absence_proposals_are_reported_separately(tmp_path):
    project, left, right, _ = runs(tmp_path)
    index = right / "evidence_review/index.json"
    payload = json.loads(index.read_text(encoding="utf-8"))
    key = next(
        k
        for k, v in payload.items()
        if isinstance(v, list) and v and isinstance(v[0], dict) and "record_id" in v[0]
    )
    payload[key][0]["evidence_span"] = None
    payload[key][1].update(
        record_kind="absence", evidence_span=None, assignment=None, proposed_code_id="unknown-code"
    )
    index.write_text(json.dumps(payload), encoding="utf-8")
    actual = raw_coding_payload(project.parents[2], right)
    assert len(actual["excluded"]) == 2 and len(actual["included"]) == 2
    assert any("Unknown code in absence proposal" in row["issues"] for row in actual["excluded"])
    assert not actual["absences"]
    from qualframe.dashboard import DashboardApp
    from qualframe.comparison_ui import render_comparison

    page = render_comparison(DashboardApp(ProjectRunner(project)), left.name, right.name)
    assert "2 proposals could not be located" in page and "left out of these figures" in page


def test_comparison_cli_and_study_boundaries(tmp_path):
    from typer.testing import CliRunner
    from qualframe_eval.cli import app as cli
    from qualframe.dashboard import DashboardApp

    project, left, right, _ = runs(tmp_path)
    result = CliRunner().invoke(
        cli, ["compare", str(project), "--left", left.name, "--right", right.name, "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert not (left / "comparisons").exists()
    result = CliRunner().invoke(
        cli, ["compare", str(project), "--left", "../escape", "--right", right.name]
    )
    assert result.exit_code != 0 and "Choose run IDs" in result.output
    dashboard = DashboardApp(ProjectRunner(project))
    with pytest.raises(ValueError, match="another study"):
        dashboard.handle_action(
            "/comparison/save",
            {"run_id": [left.name], "right_id": [right.name], "study_identity": ["other"]},
        )
    dashboard.handle_action(
        "/comparison/save",
        {
            "run_id": [left.name],
            "right_id": [right.name],
            "study_identity": [dashboard.runner.project.project_id],
        },
    )
    assert len(list((left / "comparisons").glob("*.json"))) == 1
