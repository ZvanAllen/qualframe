"""Missing requested decisions remain distinct from proposals and explicit absences."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from qualframe.evidence_review import write_evidence_review_index
from qualframe.io.files import sha256_for_file
from qualframe.qualbench import build_qualbench, coding_profile, run_coding_set, write_qualbench
from qualframe.qualbench_ui import _report_html
from qualframe.run_comparison import raw_coding_payload
from test_evidence_review import _completed_synthetic_run
from test_qualbench import _set


def _bind_synthetic_inventory(run_root, manifest):
    """Freeze altered disposable fixtures just as a fresh runner output is frozen."""
    inventory_path = run_root / manifest["qa_inventory_path"]
    inventory = json.loads(inventory_path.read_text())
    inventory["artifact_hashes"] = {
        relative: sha256_for_file(run_root / relative) for relative in manifest["artifact_paths"]
    }
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    manifest["qa_inventory_sha256"] = sha256_for_file(inventory_path)
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_run_profile_reads_omissions_from_artifacts_without_counting_them_as_absence(tmp_path):
    project, run_id, run_root, _ = _completed_synthetic_run(tmp_path)
    manifest = json.loads((run_root / "run_manifest.json").read_text())
    artifact_rel = manifest["artifact_paths"][0]
    path = run_root / artifact_rel
    artifact = json.loads(path.read_text())
    artifact["no_decisions"] = {"part-one": ["experience_communication"]}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest["no_decision_count"] = 1
    _bind_synthetic_inventory(run_root, manifest)
    write_evidence_review_index(project_manifest_path=project, run_id=run_id)

    coding = run_coding_set(project.parents[2], run_root)
    assert coding["no_decisions"] == [dict(
        source=artifact["input_path"].replace("\\", "/"),
        code_id="experience_communication", partition="part-one",
        stage_id=artifact["stage_id"], artifact_path=artifact_rel,
        artifact_sha256=sha256_for_file(path),
    )]
    profile = coding_profile(coding)
    assert profile["no_decision_count"] == 1
    assert profile["no_evidence_rows"] == 0
    assert profile["coded_passages"] == 4

    # Omissions on subsequent synthesis stages must not inflate coding-stage counts.
    later = dict(artifact, stage_id="later-synthesis", no_decisions={"later": ["access_availability"]})
    later_rel = "later-synthetic-artifact.json"
    (run_root / later_rel).write_text(json.dumps(later), encoding="utf-8")
    manifest["artifact_paths"].append(later_rel)
    _bind_synthetic_inventory(run_root, manifest)
    assert raw_coding_payload(project.parents[2], run_root)["no_decisions"] == coding["no_decisions"]

    # An indexed artifact remains immutable, including its omission metadata.
    artifact["no_decisions"] = {}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact changed"):
        raw_coding_payload(project.parents[2], run_root)


def test_all_missing_artifact_is_counted_and_qa_bound_without_review_rows(tmp_path):
    project, run_id, run_root, _ = _completed_synthetic_run(tmp_path)
    manifest = json.loads((run_root / "run_manifest.json").read_text())
    first_rel = manifest["artifact_paths"][0]
    path = run_root / first_rel
    artifact = json.loads(path.read_text())
    artifact["parsed_output"] = {"Coding": []}
    artifact["response_text"] = (
        "## Sheet: Coding\n"
        "| Meaning Unit ID | Evidence Start | Evidence End | Exact Evidence | Code ID | Rationale |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )
    artifact["no_decisions"] = {"all": ["access_availability", "experience_communication"]}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest["no_decision_count"] = 2
    _bind_synthetic_inventory(run_root, manifest)
    write_evidence_review_index(project_manifest_path=project, run_id=run_id)

    payload = raw_coding_payload(project.parents[2], run_root)
    assert len(payload["no_decisions"]) == 2
    assert not payload["absences"]
    assert all(row["source"] != artifact["input_path"].replace("\\", "/") for row in payload["included"])
    # Removing every omitted entry must not evade the QA binding for an empty artifact.
    artifact["no_decisions"] = {}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match="No-decision artifact changed"):
        raw_coding_payload(project.parents[2], run_root)


def test_omissions_follow_content_matching_and_compared_cohort(tmp_path):
    model = _set("model", [("t/one.txt", "p", 0, 5)])
    model["no_decisions"] = [
        dict(source="t/one.txt", code_id="c", partition="one"),
        dict(source="t/two.txt", code_id="q", partition="two"),
    ]
    model["absences"] = [dict(source="t/one.txt", code_id="q")]
    reference = _set("reference", [], kind="reference")
    reference["statement"] = "Synthetic reference."
    reference["sources"] = {"other/one.txt": "h1"}
    before = deepcopy(model)

    # The first coding set controls content-matched path names.
    report = build_qualbench([reference, model])
    profile = report["coding_sets"][1]
    assert profile["transcripts"] == 1
    assert profile["no_decision_count"] == 1
    assert profile["no_evidence_rows"] == 1
    assert profile["coded_passages"] == profile["codes_present"] == 1
    assert model == before

    folder = write_qualbench(report, tmp_path / "report")
    assert "no_decision_count" in (folder / "coding_sets.csv").read_text()
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "separate from explicit absence" in readme
    assert "no observed application" in readme
    page = _report_html(SimpleNamespace(_file_link=lambda path, label: label), folder)
    assert "Code decisions" in page and "No decision recorded" in page
    assert "Explicit absences" in page and "not whether an absence was explicitly declared" in page


def test_legacy_missing_metadata_is_zero_and_does_not_infer_omissions(tmp_path):
    legacy = _set("legacy", [])
    assert coding_profile(legacy)["no_decision_count"] == 0
    assert coding_profile(legacy)["no_evidence_rows"] == 0
    report = build_qualbench([legacy, _set("other", [])])
    # Saved historical reports that predate this field can still be rendered.
    for profile in report["coding_sets"]:
        profile.pop("no_decision_count")
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    page = _report_html(SimpleNamespace(_file_link=lambda path, label: label), tmp_path)
    assert "Older runs without recorded omissions show zero" in page


def test_no_decisions_does_not_change_applied_code_presence_metrics():
    left = _set("left", [])
    right = _set("right", [])
    original = build_qualbench([left, right])
    left["no_decisions"] = [dict(source="t/one.txt", code_id="p", partition="all")]
    updated = build_qualbench([left, right])
    assert updated["presence"] == original["presence"]
    assert updated["units"] == original["units"]
    assert updated["coding_sets"][0]["no_decision_count"] == 1
