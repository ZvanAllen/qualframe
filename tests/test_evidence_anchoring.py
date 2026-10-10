import json

import pytest
from test_evidence_review import _completed_synthetic_run

from qualframe.evidence_anchoring import anchor_exact_quote
from qualframe.evidence_review import load_evidence_review_records, write_evidence_review_index
from qualframe.io.transcript_io import transcript_to_text


@pytest.mark.parametrize(
    "source,quote,count",
    [
        ("A café 😀, here.", "café 😀", 1),
        ("repeat repeat", "repeat", 2),
        ("aaa", "aa", 2),
        ("hello", "Hello", 0),
        ("hello", " ", 0),
        ("a\nb", "a\nb", 1),
    ],
)
def test_unique_exact_quote_handles_unicode_and_ambiguity(source, quote, count):
    anchor = anchor_exact_quote(source, quote)
    assert anchor.match_count == count
    if count == 1:
        assert source[anchor.start : anchor.end] == quote
    else:
        assert anchor.start is None and anchor.end is None


def test_auto_locations_are_derived_and_original_model_values_retained(tmp_path):
    project, run_id, artifact_root, _ = _completed_synthetic_run(tmp_path)
    manifest = json.loads((artifact_root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact_path = artifact_root / manifest["artifact_paths"][0]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["evidence_location"] == "unique_exact_quote"
    row = next(iter(artifact["parsed_output"].values()))[0]
    row.update({"Evidence Start": "auto", "Evidence End": "auto"})
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    before = artifact_path.read_bytes()
    index = write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    record = load_evidence_review_records(index)[0]
    assert record.anchoring_method == "unique_exact_quote"
    assert record.evidence_span.creation_method == "automatic"
    assert record.raw_start_value == "auto"
    assert record.proposed_start_offset == -1
    source = transcript_to_text(project.parents[2] / record.source_path)
    span = record.evidence_span
    assert source[span.start_offset : span.end_offset] == record.proposed_exact_text
    assert not record.validation_issues
    assert artifact_path.read_bytes() == before
    # A legacy artifact must never gain automatic anchoring retroactively.
    artifact["evidence_location"] = "model_offsets"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    with pytest.raises(ValueError, match='Model artifact changed'):
        write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    assert load_evidence_review_records(index)[0].anchoring_method == 'unique_exact_quote'



def test_repeated_quote_requires_review(tmp_path):
    project, run_id, artifact_root, _ = _completed_synthetic_run(tmp_path)
    manifest = json.loads((artifact_root / "run_manifest.json").read_text(encoding="utf-8"))
    path = artifact_root / manifest["artifact_paths"][0]
    artifact = json.loads(path.read_text(encoding="utf-8"))
    row = next(iter(artifact["parsed_output"].values()))[0]
    row.update({"Evidence Start": "auto", "Evidence End": "auto", "Exact Evidence": "PARTICIPANT:"})
    path.write_text(json.dumps(artifact), encoding="utf-8")
    record = load_evidence_review_records(
        write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    )[0]
    assert record.anchor_match_count == 2
    assert record.anchoring_method == "unresolved_exact_quote"
    assert record.evidence_span is None and record.assignment is None
    assert record.validation_issues
