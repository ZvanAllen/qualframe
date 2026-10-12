
"""Synthetic decision-contract parsing and evidence/absence normalization."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from qualframe.config import load_project_manifest, resolve_repo_path
from qualframe.evidence_review import append_evidence_review_action, build_evidence_review_records
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.response_parser import (
    decisions_response_schema,
    parse_decisions_json,
    parse_model_output,
)
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import RunManifest, StageArtifact, StudyCreationRequest
from qualframe.study_setup import StudyWorkspace


def _decision(code_id: str, present: bool, quote: str = "") -> dict:
    return dict(code_id=code_id, present=present, quote=quote, rationale="Synthetic reason.")


def _parse(decisions: list) -> dict:
    return parse_model_output(json.dumps({"decisions": decisions}), decision_style="decide_each_code")


def test_decisions_are_opt_in_and_preserve_quotations() -> None:
    text = json.dumps({"decisions": [
        _decision("present-code", True, "A &amp; B | C"),
        _decision("absent-code", False),
    ]})
    assert parse_model_output(text) == {}
    rows = parse_model_output(f"\x60\x60\x60json\n{text}\n\x60\x60\x60", decision_style="decide_each_code")["Directed Coding"]
    assert rows[0]["Exact Evidence"] == "A &amp;amp; B | C"
    assert rows[0]["Meaning Unit ID"].startswith("mu-")
    assert rows[0]["Record Kind"] == "evidence"
    assert rows[1]["Exact Evidence"] == ""
    assert rows[1]["Meaning Unit ID"] == ""
    assert rows[1]["Record Kind"] == "absence"
    assert rows[1]["Evidence Start"] == rows[1]["Evidence End"] == "auto"


def test_decision_schema_limits_ids_to_request_and_requires_boolean() -> None:
    schema = decisions_response_schema(["b", "a", "b"])
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["decisions"]
    item = schema["properties"]["decisions"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"code_id", "present", "quote", "rationale"}
    assert item["properties"]["code_id"]["enum"] == ["a", "b"]
    assert item["properties"]["present"] == {"type": "boolean"}


def test_omissions_and_multiple_present_quotes_are_allowed() -> None:
    assert _parse([]) == {"Directed Coding": []}
    rows = _parse([_decision("a", True, "First"), _decision("a", True, "Second")])["Directed Coding"]
    assert len(rows) == 2
    assert {row["Code ID"] for row in rows} == {"a"}
    assert rows[0]["Meaning Unit ID"] != rows[1]["Meaning Unit ID"]


def test_same_quote_with_different_codes_shares_a_meaning_unit() -> None:
    rows = _parse([_decision("a", True, "Same quote"), _decision("b", True, "Same quote")])["Directed Coding"]
    assert rows[0]["Meaning Unit ID"] == rows[1]["Meaning Unit ID"]
    other_partition = _parse([_decision("c", True, "Different quote")])["Directed Coding"]
    repeated_partition = _parse([_decision("d", True, "Same quote")])["Directed Coding"]
    assert rows[0]["Meaning Unit ID"] != other_partition[0]["Meaning Unit ID"]
    assert rows[0]["Meaning Unit ID"] == repeated_partition[0]["Meaning Unit ID"]


@pytest.mark.parametrize("decisions", [
    ["not an object"],
    [dict(code_id="a", present="false", quote="", rationale="reason")],
    [dict(code_id="a", present=0, quote="", rationale="reason")],
    [dict(code_id="a", present=False, quote=None, rationale="reason")],
    [dict(code_id="", present=False, quote="", rationale="reason")],
    [_decision("a", False, "A contradictory quotation")],
    [_decision("a", False), _decision("a", False)],
    [_decision("a", False), _decision("a", True, "Evidence")],
    [_decision("a", True, "Evidence"), _decision("a", False)],
])
def test_malformed_or_conflicting_decisions_cannot_become_absences(decisions: list) -> None:
    with pytest.raises(ValueError):
        _parse(decisions)


@pytest.mark.parametrize("response", [
    '{"decisions": [',
    '{"decisions": {}}',
    '{"codings": []}',
])
def test_decision_contract_does_not_silently_accept_another_json_shape(response: str) -> None:
    with pytest.raises(ValueError):
        parse_model_output(response, decision_style="decide_each_code")


def test_non_json_decision_response_is_not_a_coding_table() -> None:
    assert parse_decisions_json("no decisions supplied") is None
    for response in ("No relevant codes.", "| Code ID |\n|---|\n| a |"):
        with pytest.raises(ValueError, match="JSON decisions object"):
            parse_model_output(response, decision_style="decide_each_code")


def test_explicit_absences_normalize_to_the_existing_review_record_kind(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("config", "prompts"):
        shutil.copytree(root / name, tmp_path / name)
    shutil.copytree(root / "demo/fixtures", tmp_path / "demo/fixtures")
    created = StudyWorkspace(tmp_path).create(StudyCreationRequest(
        title="Synthetic decision records",
        data_classification="synthetic",
        include_synthetic_fixtures=True,
    ))
    project_path = tmp_path / created.project_manifest_path
    project = load_project_manifest(project_path)
    source = next(resolve_repo_path(tmp_path, project.paths["raw_transcripts"]).rglob("*.txt"))
    source_hash = sha256_for_file(source)
    source_text = transcript_to_text(source)
    run_id = "synthetic-decisions"
    run_root = resolve_repo_path(tmp_path, project.paths["artifacts"]) / run_id
    run_root.mkdir(parents=True)
    decisions = [
        _decision("access_availability", True, source_text),
        _decision("experience_communication", False),
    ]
    artifact = StageArtifact(
        run_id=run_id, stage_id="directed_coding",
        input_path=str(source.relative_to(tmp_path)), input_sha256=sha256_for_text(source_text),
        prompt_ref="synthetic", prompt_sha256="a" * 64,
        evidence_location="unique_exact_quote",
        response_text=json.dumps({"decisions": decisions}),
        parsed_output=_parse(decisions),
        model="offline", provider="mock", timestamp_utc="2026-01-01T00:00:00Z",
    )
    artifact_path = run_root / "artifact.json"
    artifact_path.write_text(artifact.model_dump_json(), encoding="utf-8")
    artifact_hash = sha256_for_file(artifact_path)
    manifest = RunManifest(
        run_id=run_id, project_id=project.project_id, framework_id="synthetic",
        pipeline_id="synthetic", completed_at_utc="2026-01-01T00:00:00Z",
        artifact_paths=["artifact.json"],
    )
    (run_root / "run_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    present, absent = build_evidence_review_records(project_manifest_path=project_path, run_id=run_id)
    assert present.record_kind == "evidence"
    assert present.evidence_span and present.evidence_span.exact_text == source_text
    assert present.assignment and present.assignment.code_id == "access_availability"
    assert not present.validation_issues
    assert absent.record_kind == "absence"
    assert absent.anchoring_method == "no_evidence"
    assert absent.proposed_code_id == "experience_communication"
    assert absent.proposed_rationale == "Synthetic reason."
    assert absent.proposed_exact_text == ""
    assert absent.proposed_start_offset == absent.proposed_end_offset == -1
    assert absent.evidence_span is absent.assignment is absent.context_text is None
    assert not absent.validation_issues
    action = append_evidence_review_action(
        record=absent, source_path=source,
        review_dir=resolve_repo_path(tmp_path, project.paths["review_queue"]) / run_id,
        artifact_root=run_root, decision="accept", reviewer="Synthetic researcher",
        rationale="Confirm the explicit absence.",
    )
    assert action.decision == "accept" and action.derived_artifact_path is None
    assert sha256_for_file(source) == source_hash
    assert sha256_for_file(artifact_path) == artifact_hash
