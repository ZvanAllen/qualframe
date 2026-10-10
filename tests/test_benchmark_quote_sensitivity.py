from copy import deepcopy

import pytest

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.benchmark_quote_sensitivity import CASEFOLD_POLICY, casefold_quote_sensitivity
from qualframe.io.files import sha256_for_text
from qualframe.reviewed_analysis import snapshot_identity

QUOTE_ISSUES = [
    "Missing source span",
    "Select the evidence in the transcript; the quotation is missing or ambiguous.",
]


def fixture(source="We CAN’T\tattend. A literal span.", quotation='"we can\'t attend."'):
    file_hash = sha256_for_text("Synthetic file bytes")
    identity = (
        "benchmark-source-"
        + snapshot_identity({"original_path": "synthetic.txt", "sha256": file_hash})[:24]
    )
    mapping = {
        "synthetic.txt": dict(
            source_id=identity,
            original_path="synthetic.txt",
            sha256=file_hash,
            extracted_text_sha256=sha256_for_text(source),
        )
    }
    item = dict(
        record_id="case-proposal",
        source=identity,
        code_id="a",
        proposed_quotation=quotation,
        anchoring_method="unresolved_exact_quote",
        issues=list(QUOTE_ISSUES),
        rationale="Synthetic rationale remains unchanged.",
        artifact_sha256="frozen-artifact",
    )
    payload = dict(
        kind="qualframe_raw_comparison_input_v1",
        run_id="left",
        project_id="synthetic-benchmark",
        codebook=dict(id="codebook", version="frozen", codes=[dict(id="a", label="Code A")]),
        sources={identity: file_hash},
        included=[],
        excluded=[item],
        absences=[],
        benchmark_provenance=dict(
            normalization_version="historical_cfir_benchmark_v1",
            source_mapping=mapping,
            source_mapping_sha256=snapshot_identity(mapping),
            human_reference=False,
        ),
    )
    return payload, {identity: source}


def test_recovers_only_case_with_original_source_quote_and_strict_audit_preserved():
    payload, texts = fixture()
    source_id = next(iter(texts))
    payload["included"].append(
        dict(
            record_id="strict",
            source=source_id,
            code_id="a",
            start=17,
            end=32,
            exact_text=texts[source_id][17:32],
        )
    )
    before = deepcopy(payload)
    result = casefold_quote_sensitivity(payload, texts)
    assert payload == before
    assert result["included"][0] == payload["included"][0]
    recovered = result["included"][1]
    assert recovered["exact_text"] == "We CAN’T\tattend."
    assert texts[source_id][recovered["start"] : recovered["end"]] == recovered["exact_text"]
    assert recovered["proposed_quotation"] == payload["excluded"][0]["proposed_quotation"]
    assert recovered["rationale"] == payload["excluded"][0]["rationale"]
    assert recovered["anchoring_method"] == CASEFOLD_POLICY
    assert not result["excluded"]
    audit = result["benchmark_provenance"]["quote_anchoring_sensitivity"]
    assert audit["original_strict_input_sha256"] == snapshot_identity(payload)
    assert audit["strict_counts"] == dict(included=1, excluded=1, absences=0)
    assert audit["sensitivity_counts"] == dict(included=2, excluded=0, absences=0)
    assert audit["attempts"][0]["strict_issues"] == QUOTE_ISSUES
    assert audit["attempts"][0]["original_exclusion_sha256"] == snapshot_identity(
        payload["excluded"][0]
    )
    assert casefold_quote_sensitivity(payload, texts) == result
    with pytest.raises(ValueError, match="once"):
        casefold_quote_sensitivity(result, texts)


@pytest.mark.parametrize(
    "source,quotation,outcome,exact",
    [
        ("Straße.", "STRASSE.", "recovered_casefold_only", "Straße."),
        ("\u0130", "i", "source_slice_roundtrip_mismatch", None),
        ("Echo. ECHO.", "echo.", "ambiguous_casefold_matches", None),
        ("A clear quote.", "a clear quote!", "no_casefold_match", None),
        ("A clear quote.", "a lucid quote.", "no_casefold_match", None),
        ("Exact.", "Exact.", "already_strictly_anchorable", None),
        ("Exact.", '" "', "empty_quotation", None),
        ("No. A. B.", "a. ... b.", "no_casefold_match", None),
    ],
)
def test_unicode_ambiguity_punctuation_and_word_changes_fail_closed(
    source, quotation, outcome, exact
):
    payload, texts = fixture(source, quotation)
    result = casefold_quote_sensitivity(payload, texts)
    audit = result["benchmark_provenance"]["quote_anchoring_sensitivity"]
    assert audit["attempts"][0]["outcome"] == outcome
    if exact:
        assert result["included"][0]["exact_text"] == exact
    else:
        assert not result["included"]
        assert result["excluded"] == payload["excluded"]


def test_unresolved_duplicate_codes_other_issues_and_absences_never_recovered():
    payload, texts = fixture()
    original = payload["excluded"][0]
    payload["codebook"]["codes"] += [dict(id="duplicate", label="X")] * 2
    payload["excluded"] = [
        dict(original, record_id="unknown", code_id="missing"),
        dict(original, record_id="duplicated", code_id="duplicate"),
        dict(original, record_id="other", issues=QUOTE_ISSUES + ["A separate QA error"]),
        dict(original, record_id="unrecognized", issues=["Missing source span"]),
        dict(
            original,
            record_id="absence",
            anchoring_method="no_evidence",
            proposed_quotation="No relevant quote found",
        ),
    ]
    payload["absences"] = [dict(record_id="valid-absence", source=next(iter(texts)), code_id="a")]
    result = casefold_quote_sensitivity(payload, texts)
    assert result["excluded"] == payload["excluded"]
    assert result["absences"] == payload["absences"]
    assert not result["included"]


@pytest.mark.parametrize(
    "change", ["text", "missing", "extra", "mapping", "file_hash", "duplicate_source"]
)
def test_changed_source_or_mapping_aborts_without_mutation(change):
    payload, texts = fixture()
    source_id = next(iter(texts))
    provenance = payload["benchmark_provenance"]
    if change == "text":
        texts[source_id] += " Changed"
    elif change == "missing":
        texts.clear()
    elif change == "extra":
        texts["undeclared"] = "Extra"
    elif change == "mapping":
        provenance["source_mapping"]["synthetic.txt"]["original_path"] = "different.txt"
    elif change == "file_hash":
        payload["sources"][source_id] = "different"
    else:
        provenance["source_mapping"]["another.txt"] = deepcopy(
            provenance["source_mapping"]["synthetic.txt"]
        )
        provenance["source_mapping_sha256"] = snapshot_identity(provenance["source_mapping"])
    before = deepcopy(payload)
    with pytest.raises(ValueError):
        casefold_quote_sensitivity(payload, texts)
    assert payload == before


def test_original_included_spans_and_record_identities_are_validated():
    payload, texts = fixture()
    payload["included"] = [
        dict(
            record_id="strict",
            source=next(iter(texts)),
            code_id="a",
            start=0,
            end=3,
            exact_text="Not that source",
        )
    ]
    with pytest.raises(ValueError, match="Original included"):
        casefold_quote_sensitivity(payload, texts)
    payload["included"] = []
    payload["excluded"].append(deepcopy(payload["excluded"][0]))
    with pytest.raises(ValueError, match="unique"):
        casefold_quote_sensitivity(payload, texts)


def test_report_identity_and_code_label_policy_remain_explicitly_separate():
    left, texts = fixture()
    left["benchmark_provenance"].update(
        normalization_version="historical_cfir_benchmark_qualified_delimiters_v2",
        code_label_policy="qualified_delimiters_v2",
        code_label_aliases=[dict(record_id="case-proposal", canonical_code_id="a")],
    )
    right = deepcopy(left)
    right["run_id"] = "right"
    original = build_benchmark_report(left, right)
    revised_left = casefold_quote_sensitivity(left, texts)
    revised_right = casefold_quote_sensitivity(right, texts)
    revised = build_benchmark_report(revised_left, revised_right)
    assert snapshot_identity(revised) != snapshot_identity(original)
    assert revised["input_hashes"] != original["input_hashes"]
    assert build_benchmark_report(left, right) == original
    provenance = revised_left["benchmark_provenance"]
    assert provenance["code_label_policy"] == "qualified_delimiters_v2"
    assert provenance["quote_anchoring_sensitivity"]["original_normalization_version"].endswith(
        "qualified_delimiters_v2"
    )
    assert provenance["code_label_aliases"] == left["benchmark_provenance"]["code_label_aliases"]
    assert revised["summary"]["exact"]["f1_dice"] == 1
    assert original["summary"]["exact"]["f1_dice"] is None
