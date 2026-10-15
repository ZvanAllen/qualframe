"""Synthetic quotation normalization and human-confirmation checks."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from qualframe.cfir_review import cfir_records, locate_quote, normalized_words_with_offsets
from qualframe.dashboard import DashboardApp
from qualframe.evidence_review import (
    WORDS_NOTICE, append_evidence_review_action, blocking_review_issues,
    load_evidence_review_actions, load_evidence_review_records, write_evidence_review_index,
)
from qualframe.io.transcript_io import transcript_to_text
from qualframe.methods_record import build_methods_record
from qualframe.models import EvidenceReviewRecord
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.reference_coding import locate_reference_quote
from test_evidence_review import _completed_synthetic_run
from test_reference_repeated_quotes import _import


@pytest.mark.parametrize("source,quote,expected", [
    ("Start. WE met, every week! End.", "we met every week", "WE met, every week"),
    ("Before. We\n  MET: every\tweek. After.", "WE met every week", "We\n  MET: every\tweek"),
    ("😀 Before. We can’t attend; TODAY. After.", "we can't attend today", "We can’t attend; TODAY"),
    ("Before: CAFÉ (OPEN), today! After.", "café open today", "CAFÉ (OPEN), today"),
    ("Before: İN THE ROOM. After.", "i̇n the room", "İN THE ROOM"),
    ("Before: Our WELL-BEING improved. After.", "our wellbeing improved", "Our WELL-BEING improved"),
    ("Before: Hello—World. After.", "helloworld", "Hello—World"),
])
def test_words_candidate_keeps_original_character_offsets(source, quote, expected):
    start, end, method = locate_quote(source, quote)
    assert method == "normalized_words_candidate"
    assert source[start:end] == expected
    assert normalized_words_with_offsets(source[start:end])[0] == normalized_words_with_offsets(quote)[0]


@pytest.mark.parametrize("source,quote", [
    ("WE met. We MET!", "we met"),
    ("WE met every week; we MET every week!", "We met every week"),
    ("We can't attend.", "we cant attend"),  # Apostrophes remain significant.
    ("WE MET in a concatenate area.", "CAT"),  # No word fragments.
    ("We met Today.", "We met to"),
    ("Banana banana", "ANA"),
    ("Words only here.", "--- !!!"),
    ("Words only here.", "''"),
    ("Words only here.", "   "),
    ("We met every week.", "we met each week"),
    ("We met: every week.", "we every met week"),
])
def test_words_match_rejects_ambiguity_empty_fragments_and_changed_words(source, quote):
    assert locate_quote(source, quote) == (-1, -1, "unresolved_exact_quote")


def test_exact_and_typography_precede_word_matching():
    source = "We met. WE MET!"
    assert locate_quote(source, "We met.") == (0, 7, "unique_exact_quote")
    source = "We   met. WE MET!"
    assert locate_quote(source, "We met.") == (0, 9, "normalized_quote_candidate")
    # Existing repeated higher-tier matches cannot be narrowed using word boundaries.
    assert locate_quote("XWe met. We met.", "We met.") == (-1, -1, "unresolved_exact_quote")


def _word_proposal(tmp_path):
    project, run_id, root, review = _completed_synthetic_run(tmp_path)
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    artifact_path = root / manifest["artifact_paths"][0]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    row = next(iter(artifact["parsed_output"].values()))[0]
    proposed = row["Exact Evidence"].swapcase().replace(".", "").replace(",", "")
    row.update({"Evidence Start": "auto", "Evidence End": "auto", "Exact Evidence": proposed})
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    before = artifact_path.read_bytes()
    index = write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    record = load_evidence_review_records(index)[0]
    assert artifact_path.read_bytes() == before
    return project, run_id, root, review, index, record, proposed


def test_model_proposal_keeps_quote_and_requires_a_recorded_confirmation(tmp_path):
    project, run_id, root, review, index, record, proposed = _word_proposal(tmp_path)
    source_path = project.parents[2] / record.source_path
    original_source = source_path.read_bytes()
    source = transcript_to_text(source_path)
    assert record.anchoring_method == "normalized_words_candidate"
    assert record.proposed_exact_text == proposed
    assert record.proposed_start_offset == record.proposed_end_offset == -1
    assert record.validation_issues == [WORDS_NOTICE]
    assert record.evidence_span.exact_text != proposed
    assert record.evidence_span.exact_text == source[record.evidence_span.start_offset:record.evidence_span.end_offset]
    assert record.assignment.review_status == "unreviewed"
    assert load_evidence_review_actions(review) == []
    assert EvidenceReviewRecord.model_validate_json(record.model_dump_json()) == record
    assert blocking_review_issues(record, source) == []  # Accept is the confirmation action.
    app = DashboardApp(ProjectRunner(project))
    page = app.render_evidence(run_id=run_id, item_id=record.record_id)
    assert "differs in case or punctuation" in page
    assert "accepting confirms this match" in page
    assert build_methods_record(app, run_id)["review"]["needed_manual_location"] == 1
    before_index = index.read_bytes()
    action = append_evidence_review_action(
        record=record, source_path=source_path, review_dir=review, artifact_root=root,
        decision="accept", reviewer="Synthetic researcher", rationale="Confirmed the source passage.",
    )
    assert action.decision == "accept"
    assert len(load_evidence_review_actions(review)) == 1
    assert index.read_bytes() == before_index and source_path.read_bytes() == original_source


def test_words_confirmation_rechecks_location_and_never_drops_other_errors(tmp_path):
    project, _, root, review, _, record, _ = _word_proposal(tmp_path)
    source_path = project.parents[2] / record.source_path
    source = transcript_to_text(source_path)
    invalid = record.model_copy(update={"validation_issues": [WORDS_NOTICE, "Unknown construct"]})
    assert blocking_review_issues(invalid, source) == ["Unknown construct"]
    with pytest.raises(ValueError, match="Invalid evidence"):
        append_evidence_review_action(
            record=invalid, source_path=source_path, review_dir=review, artifact_root=root,
            decision="accept", reviewer="Synthetic researcher", rationale="Check failed.",
        )
    mismatched = record.model_copy(update={"evidence_span": record.evidence_span.model_copy(
        update={"start_offset": record.evidence_span.start_offset + 1})})
    assert WORDS_NOTICE in blocking_review_issues(mismatched, source)
    assert WORDS_NOTICE in blocking_review_issues(record, source + " " + record.evidence_span.exact_text)
    assert load_evidence_review_actions(review) == []


def test_cfir_model_proposals_get_the_same_candidate_label(tmp_path):
    source = tmp_path / "synthetic.txt"
    source.write_text("Participant: WE met, every week!", encoding="utf-8")
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text("{}", encoding="utf-8")
    artifact = SimpleNamespace(
        parsed_output={"Inner Setting": [{"CFIR Construct": "A. Structure", "Quote": "we met every week"}]},
        stage_id="transcript_to_cfir", model="offline", provider="mock", prompt_sha256="0" * 64,
    )
    [record] = cfir_records(
        artifact=artifact, artifact_rel="artifact.json", artifact_path=artifact_path, source_path=source,
        repo_root=tmp_path, manifest=SimpleNamespace(run_id="synthetic", configuration_fingerprint="f"),
        codes=[dict(id="structure", raw_label="A. Structure", label="Structure", parent_label="",
                    domain="Inner Setting", definition="Synthetic structure")], codebook_hash="h",
    )
    assert record.anchoring_method == "normalized_words_candidate"
    assert record.evidence_span.exact_text == "WE met, every week"
    assert record.proposed_exact_text == "we met every week"
    assert record.validation_issues == [WORDS_NOTICE]
    assert blocking_review_issues(record, source.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("kind", ["table", "cfir"])
def test_reference_import_retains_word_candidate_provenance(tmp_path, kind):
    source, quote = "Before. WE met, every week! After.", "we met every week"
    _, _, payload, _ = _import(tmp_path, kind, source, quote)
    [item] = payload["included"]
    assert payload["excluded"] == []
    assert item["quote"] == quote
    assert item["anchoring_method"] == "normalized_words_candidate"
    assert item["requires_confirmation"] is True
    assert any("requiring researcher confirmation" in note for note in payload["notices"])
    assert item["exact_text"] == source[item["start"]:item["end"]] == "WE met, every week"
    assert locate_reference_quote(source, quote) == (item["start"], item["end"], "normalized_words_candidate")
    assert "alternative_spans" not in item


@pytest.mark.parametrize("kind", ["table", "cfir"])
def test_reference_repeated_words_remain_unlocated(tmp_path, kind):
    _, _, payload, _ = _import(tmp_path, kind, "WE met every week. We MET every week!", "we met every week")
    assert payload["included"] == []
    [item] = payload["excluded"]
    assert item["anchoring_method"] == "unresolved_exact_quote"
    assert payload["counts"]["quotations_not_found"] == 1


def test_frozen_locator_opt_out_keeps_exact_and_typography_but_not_words():
    assert locate_quote("A clear quote.", "A clear quote.", allow_word_normalization=False)[2] == "unique_exact_quote"
    assert locate_quote("We  met.", "We met.", allow_word_normalization=False)[2] == "normalized_quote_candidate"
    assert locate_quote("A clear quote.", "a clear quote!", allow_word_normalization=False) == (-1, -1, "unresolved_exact_quote")
    assert locate_quote("A clear quote.", "a clear quote!")[2] == "normalized_words_candidate"


@pytest.mark.parametrize("policy", ["legacy_v1", "qualified_delimiters_v2"])
def test_frozen_historical_adapter_keeps_words_candidates_unlocated(tmp_path, policy):
    from test_benchmark_inputs import fixture, payload
    root, run, book = fixture(tmp_path)
    path = run / "coding.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["parsed_output"]["Innovation"][0]["Quote"] = "a clear quote!"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    before = path.read_bytes()
    result = payload(root, run, book, code_label_policy=policy)
    assert len(result["included"]) == 1  # Existing typography candidate only.
    item = next(i for i in result["excluded"] if i.get("proposed_quotation") == "a clear quote!")
    assert item["anchoring_method"] == "unresolved_exact_quote"
    assert item["issues"] == ["Missing source span", "Select the evidence in the transcript; the quotation is missing or ambiguous."]
    assert path.read_bytes() == before
