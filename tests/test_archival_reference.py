"""Synthetic archival evidence tests; no real source material or provider calls."""

import copy
import json

import pytest

from qualframe.archival_comparison import compare_archival_reference
from qualframe.archival_reference import (
    ANCHOR_POLICY,
    ORIGIN,
    build_parent_projection,
    load_archival_reference,
    strict_quote_candidates,
)
from qualframe.benchmark_inputs import build_source_mapping
from qualframe.io.files import sha256_for_file
from qualframe.reviewed_analysis import snapshot_identity


def catalog():
    def code(identifier, raw, domain="INNOVATION DOMAIN", parent=""):
        return dict(
            id=identifier,
            label=raw,
            raw_label=raw,
            domain=domain,
            parent_label=parent,
            definition="Synthetic definition.",
        )

    return dict(
        id="synthetic-cfir",
        codes=[
            code("parent", "A. Practice"),
            code("child", "1. Detail", parent="A. Practice"),
            code("other", "B. Resources"),
            code("outer", "A. Practice", "OUTER SETTING DOMAIN"),
            code("outer-child", "1. Detail", "OUTER SETTING DOMAIN", "A. Practice"),
            code("addendum", "A. Outcome", "OUTCOMES ADDENDUM"),
            code("note", "Note:"),
            dict(code("note", "Note:"), definition="Another footnote."),
        ],
    )


class ImportFixture:
    def __init__(self, root, text="Alpha beta gamma. Delta epsilon. Again again."):
        self.source_root = root / "sources"
        self.reference_root = root / "references"
        self.source_root.mkdir()
        self.reference_root.mkdir()
        for name in ("a.txt", "b.txt"):
            (self.source_root / name).write_text(text, encoding="utf-8")
        self.mapping = build_source_mapping(self.source_root, ["a.txt", "b.txt"])
        self.ids = {key[0]: value["source_id"] for key, value in self.mapping.items()}
        self.texts = {identifier: text for identifier in self.ids.values()}
        self.quotes, self.entries = [], []
        self.path = root / "import.json"
        book = catalog()
        self.manifest = dict(
            kind="qualframe_archival_reference_import_v1",
            reference_id="synthetic-archive",
            project_id="synthetic-study",
            origin=ORIGIN,
            review_provenance=dict(
                statement="Historical assisted outputs were reviewed.",
                basis="researcher_attestation",
                item_level_history_available=False,
                independent_human_coding=False,
            ),
            codebook=book,
            codebook_sha256=snapshot_identity(book),
            source_mapping=self.mapping,
            parent_projection=build_parent_projection(book),
            entries=self.entries,
            coverage=dict(extraction_complete=True, statement="Selected quotation inventory only."),
        )

    def add(
        self, body, *, source="a", code="parent", domain="Innovation", layer="network", **changes
    ):
        index = len(self.quotes)
        self.quotes.append('"' + body + '" - synthetic speaker')
        row = dict(
            record_id=f"archival-{index}",
            layer=layer,
            source=self.ids.get(source, source),
            code_id=code,
            domain=domain,
            original_code_label=code,
            reference_file="evidence",
            json_pointer=f"/quotes/{index}",
            body_start=1,
            body_end=len(body) + 1,
            issues=[],
        )
        row.update(changes)
        self.entries.append(row)
        return row

    def freeze(self):
        reference = self.reference_root / "evidence.json"
        reference.write_text(json.dumps(dict(quotes=self.quotes)), encoding="utf-8")
        self.manifest["reference_files"] = dict(
            evidence=dict(path="evidence.json", sha256=sha256_for_file(reference))
        )
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def load(self, **kwargs):
        return load_archival_reference(
            self.path,
            source_root=self.source_root,
            reference_root=self.reference_root,
            layer="network",
            **kwargs,
        )

    def new(self, *spans):
        rows = [
            dict(
                record_id=f"new-{i}",
                source=self.ids[source],
                code_id=code,
                start=start,
                end=end,
                exact_text=self.texts[self.ids[source]][start:end],
            )
            for i, (source, code, start, end) in enumerate(spans)
        ]
        return dict(
            kind="qualframe_raw_comparison_input_v1",
            run_id="new-run",
            project_id="synthetic-study",
            codebook=copy.deepcopy(self.manifest["codebook"]),
            sources={entry["source_id"]: entry["sha256"] for entry in self.mapping.values()},
            included=rows,
            excluded=[],
            absences=[],
            benchmark_provenance=dict(
                source_mapping=copy.deepcopy(self.mapping),
                source_mapping_sha256=snapshot_identity(self.mapping),
                quote_anchoring_policy=ANCHOR_POLICY,
            ),
        )


@pytest.fixture
def archive(tmp_path):
    return ImportFixture(tmp_path)


def test_import_preserves_origin_originals_and_deduplicates_only_scoring_inventory(archive):
    archive.add("Alpha beta", code="child")
    archive.add("Alpha beta", code="parent")
    archive.add("Alpha beta", code="parent")
    archive.freeze()
    before = {
        path: sha256_for_file(path) for path in archive.path.parent.rglob("*") if path.is_file()
    }
    result = archive.load()
    assert result["origin"] == ORIGIN
    assert result["benchmark_provenance"]["adjudication_actions_created"] == 0
    assert result["benchmark_provenance"]["independent_human_reference"] is False
    assert result["included"][0]["code_id"] == "child"
    assert result["included"][0]["original_quotation"] == archive.quotes[0]
    assert result["included"][0]["exact_text"] == "Alpha beta"
    assert result["inventory_counts"]["unique_parent_spans"] == 1
    assert result["inventory_counts"]["duplicate_entries"] == 2
    assert result["inventory_counts"]["eligibility_denominator"] == 3
    assert result["absences"] == []
    assert result["codebook"] == archive.manifest["codebook"]
    assert result["benchmark_provenance"]["ambiguous_catalog_code_ids"] == ["note"]
    assert all(sha256_for_file(path) == digest for path, digest in before.items())


def test_typography_is_case_sensitive_and_reverse_slice_preserves_original(tmp_path):
    fixture = ImportFixture(tmp_path, "The “plan”—works.\nNew  words.")
    fixture.add('The "plan"-works. New words.')
    fixture.freeze()
    item = fixture.load()["included"][0]
    assert item["anchoring_method"] == "typographic_whitespace"
    assert item["exact_text"] == fixture.texts[item["source"]]
    assert item["proposed_quotation"] != item["exact_text"]
    assert strict_quote_candidates("Alpha", "alpha") == (None, [])


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"body_start": -1}, "missing_or_invalid_quote_body"),
        ({"body_end": True}, "missing_or_invalid_quote_body"),
        ({"source": None}, "unresolved_source_attribution"),
        ({"code_id": "unknown"}, "unresolved_code_id"),
        ({"code_id": "note"}, "ambiguous_catalog_code_id"),
        ({"domain": "Outer Setting"}, "code_domain_mismatch"),
        ({"anchor": {"start": 0, "end": 5, "method": "casefold"}}, "anchor_outside_strict_policy"),
        (
            {"anchor": {"start": 1, "end": 6, "method": "exact"}},
            "audited_anchor_differs_from_verified_source_match",
        ),
        ({"issues": ["attribution_conflict"]}, "attribution_conflict"),
    ],
)
def test_unresolved_or_inconsistent_entries_stay_in_denominator(archive, changes, expected):
    archive.add("Alpha", **changes)
    archive.freeze()
    result = archive.load()
    assert result["included"] == []
    assert expected in result["excluded"][0]["issues"]
    assert result["inventory_counts"]["eligibility_denominator"] == 1
    assert result["inventory_counts"]["eligible_fraction"] == 0


def test_ambiguity_is_not_resolved_by_a_selected_candidate_and_casefold_is_excluded(tmp_path):
    fixture = ImportFixture(tmp_path, "Echo Echo ALPHA")
    fixture.add("Echo", anchor=dict(start=0, end=4, method="exact"))
    fixture.add("alpha", audit=dict(candidate_policy="casefold"))
    fixture.freeze()
    result = fixture.load()
    assert result["included"] == []
    assert "ambiguous_source_anchor" in result["excluded"][0]["issues"]
    assert len(result["excluded"][0]["derived_anchor_candidates"]) == 2
    assert "quote_not_found_under_strict_policy" in result["excluded"][1]["issues"]
    assert result["excluded"][1]["audit"] == dict(candidate_policy="casefold")


def test_layers_cohort_and_addendum_are_explicit_separate_scope_exclusions(archive):
    archive.add("Alpha")
    archive.add("Alpha", source="b")
    archive.add("Alpha", layer="cross")
    archive.add("Alpha", code="addendum", domain="Outcomes Addendum")
    archive.add("not present", source=None)
    archive.freeze()
    result = archive.load(source_ids=[archive.ids["a"]])
    assert len(result["included"]) == 1 and len(result["excluded"]) == 1
    assert len(result["out_of_scope"]) == 3
    assert result["inventory_counts"]["total_entries"] == 5
    assert result["inventory_counts"]["eligible_fraction"] == 0.5
    assert result["benchmark_provenance"]["original_source_count"] == 2
    assert result["benchmark_provenance"]["selected_source_count"] == 1
    assert set(result["sources"]) == {archive.ids["a"]}


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("source", "Source file"),
        ("reference", "Reference file"),
        ("codebook", "codebook hash"),
        ("projection", "same-domain"),
        ("pointer", "pointer does not exist"),
        ("escape", "leaves its declared root"),
        ("duplicate-id", "record IDs"),
        ("independent", "independent human coding"),
    ],
)
def test_frozen_inputs_and_projection_fail_closed(archive, mutation, message):
    archive.add("Alpha")
    if mutation == "codebook":
        archive.manifest["codebook"]["codes"][0]["definition"] = "Changed."
    if mutation == "projection":
        archive.manifest["parent_projection"]["child"] = "outer"
    if mutation == "pointer":
        archive.entries[0]["json_pointer"] = "/quotes/99"
    if mutation == "escape":
        archive.mapping["../escape.txt"] = archive.mapping.pop("a.txt")
    if mutation == "duplicate-id":
        archive.add("beta", record_id="archival-0")
    if mutation == "independent":
        archive.manifest["review_provenance"]["independent_human_coding"] = True
    archive.freeze()
    if mutation == "source":
        (archive.source_root / "a.txt").write_text("Changed", encoding="utf-8")
    if mutation == "reference":
        (archive.reference_root / "evidence.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        archive.load()


def test_parent_projection_uses_exact_domain_and_omits_ambiguous_ids(archive):
    projection = archive.manifest["parent_projection"]
    assert projection["child"] == "parent" and projection["outer-child"] == "outer"
    assert "note" not in projection
    del projection["child"]
    archive.add("Alpha", code="child")
    archive.freeze()
    assert "unresolved_parent_projection" in archive.load()["excluded"][0]["issues"]


def test_retrieval_handles_expanded_context_and_separates_boundary_sensitivity(archive):
    archive.add("Alpha beta gamma.", code="child")
    archive.add("absent quote")
    archive.freeze()
    imported = archive.load()
    fresh = archive.new(("a", "parent", 6, 10))
    original = copy.deepcopy((fresh, imported))
    report = compare_archival_reference(
        fresh, imported, source_texts=archive.texts, include_boundary_sensitivity=True
    )
    assert report["primary"]["matched_pairs"] == 1
    assert report["primary"]["archival_annotation_recovery"] == 1
    assert report["primary"]["new_output_matched_fraction"] == 1
    assert report["boundary_sensitivity"]["report"]["summary"]["exact"]["f1_dice"] == 0
    assert report["boundary_sensitivity"]["report"]["summary"]["iou_0_50"]["f1_dice"] == 0
    assert report["eligibility"]["archival"]["eligible_fraction"] == 0.5
    assert report["policy"]["primary_threshold"] == 0.5
    assert "not a validated" in report["policy"]["threshold_status"]
    assert "not independent human accuracy" in report["interpretation"]
    assert report["policy"]["new_output_quote_anchoring_policy"] == ANCHOR_POLICY
    projected = report["archival_reference"]
    assert projected["kind"] == "qualframe_archival_parent_comparison_input_v1"
    assert projected["content_sha256"] == snapshot_identity(
        {k: v for k, v in projected.items() if k != "content_sha256"}
    )
    assert (
        projected["benchmark_provenance"]["original_content_sha256"] == imported["content_sha256"]
    )
    assert (fresh, imported) == original
    assert report == compare_archival_reference(
        fresh, imported, source_texts=archive.texts, include_boundary_sensitivity=True
    )


def test_parent_projection_duplicates_do_not_inflate_scores(archive):
    archive.add("Alpha", code="child")
    archive.add("Alpha", code="parent")
    archive.add("Alpha", code="note")
    archive.freeze()
    report = compare_archival_reference(
        archive.new(("a", "child", 0, 5), ("a", "parent", 0, 5)),
        archive.load(),
        source_texts=archive.texts,
    )
    assert report["primary"]["matched_pairs"] == 1
    assert report["primary"]["archival_items"] == report["primary"]["new_items"] == 1
    assert report["eligibility"]["archival"]["included_entries"] == 2
    assert report["eligibility"]["archival"]["duplicate_entries"] == 1
    assert report["eligibility"]["archival"]["excluded_entries"] == 1
    assert report["eligibility"]["new"]["duplicate_entries"] == 1
    match = report["primary"]["matches"][0]
    assert len(match["archival"]["record_ids"]) == 2
    assert (
        len(report["archival_reference"]["benchmark_provenance"]["original_codebook"]["codes"]) == 8
    )


def test_maximum_matching_recovers_pair_that_greedy_loses(tmp_path):
    fixture = ImportFixture(tmp_path, "abcdefghi")
    fixture.add("ab")
    fixture.add("ef")
    fixture.freeze()
    report = compare_archival_reference(
        fixture.new(("a", "parent", 0, 6), ("a", "parent", 1, 2)),
        fixture.load(),
        source_texts=fixture.texts,
    )
    assert report["primary"]["matched_pairs"] == 2
    assert report["primary"]["retrieval_dice"] == 1
    assert report["primary"]["matches"][0]["archival"]["record_ids"] == ["archival-1"]


def test_one_broad_archival_quote_cannot_match_two_new_quotes(archive):
    archive.add("Alpha beta gamma.")
    archive.freeze()
    report = compare_archival_reference(
        archive.new(("a", "parent", 0, 5), ("a", "parent", 6, 10)),
        archive.load(),
        source_texts=archive.texts,
    )
    assert report["primary"]["matched_pairs"] == 1
    assert report["primary"]["new_output_matched_fraction"] == 0.5
    assert report["primary"]["retrieval_dice"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("source, code", [("a", "other"), ("b", "parent"), ("a", "outer")])
def test_matches_require_same_source_and_same_parent(archive, source, code):
    archive.add("Alpha")
    archive.freeze()
    report = compare_archival_reference(
        archive.new((source, code, 0, 5)), archive.load(), source_texts=archive.texts
    )
    assert report["primary"]["matched_pairs"] == 0


def test_empty_denominators_are_null_and_absences_are_not_reconstructed(archive):
    archive.add("not in source")
    archive.freeze()
    fresh = archive.new()
    fresh["absences"].append(dict(record_id="negative", source=archive.ids["a"], code_id="parent"))
    result = compare_archival_reference(fresh, archive.load(), source_texts=archive.texts)
    assert result["primary"]["retrieval_dice"] is None
    assert result["primary"]["archival_annotation_recovery"] is None
    assert result["primary"]["new_output_matched_fraction"] is None
    assert result["equal_weight_source_summary"]["defined_sources"] == 0
    assert result["eligibility"]["new"]["absence_declarations"] == 1
    assert result["eligibility"]["archival"]["absence_declarations"] == 0
    result = compare_archival_reference(
        archive.new(("a", "parent", 0, 5)), archive.load(), source_texts=archive.texts
    )
    assert result["primary"]["retrieval_dice"] == 0
    assert result["primary"]["new_output_matched_fraction"] == 0
    assert result["primary"]["archival_annotation_recovery"] is None


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("archive", "content hash"),
        ("text", "Extracted source text"),
        ("span", "source slice"),
        ("offset", "offsets"),
        ("code", "unambiguous"),
        ("book", "same frozen original"),
        ("cohort", "same frozen cohort"),
        ("new-mapping", "mapping hash"),
    ],
)
def test_comparison_rejects_tampered_or_incompatible_inputs(archive, mutation, message):
    archive.add("Alpha")
    archive.freeze()
    imported, fresh, texts = (
        archive.load(),
        archive.new(("a", "parent", 0, 5)),
        copy.deepcopy(archive.texts),
    )
    if mutation == "archive":
        imported["included"][0]["start"] = 1
    if mutation == "text":
        texts[archive.ids["a"]] += "changed"
    if mutation == "span":
        fresh["included"][0]["exact_text"] = "other"
    if mutation == "offset":
        fresh["included"][0]["end"] = 999
    if mutation == "code":
        fresh["included"][0]["code_id"] = "note"
    if mutation == "book":
        fresh["codebook"]["codes"][0]["label"] = "Changed"
    if mutation == "cohort":
        fresh["sources"].pop(archive.ids["b"])
    if mutation == "new-mapping":
        fresh["benchmark_provenance"]["source_mapping"]["a.txt"]["extracted_text_sha256"] = (
            "changed"
        )
    with pytest.raises(ValueError, match=message):
        compare_archival_reference(fresh, imported, source_texts=texts)


def test_threshold_sensitivities_are_inclusive_and_distinct(tmp_path):
    fixture = ImportFixture(tmp_path, "abcdefghijkl")
    fixture.add("abcd")
    fixture.freeze()
    fresh, imported = fixture.new(("a", "parent", 2, 6)), fixture.load()
    report = compare_archival_reference(fresh, imported, source_texts=fixture.texts)
    assert report["threshold_sensitivities"]["0.50"]["matched_pairs"] == 1
    assert report["threshold_sensitivities"]["0.75"]["matched_pairs"] == 0
    report = compare_archival_reference(
        fresh, imported, source_texts=fixture.texts, minimum_shorter_span_overlap=0.501
    )
    assert report["primary"]["matched_pairs"] == 0
    assert len(report["threshold_sensitivities"]) == 4
    for value in (0, -1, 1.1, True, float("nan")):
        with pytest.raises(ValueError, match="threshold"):
            compare_archival_reference(
                fresh, imported, source_texts=fixture.texts, minimum_shorter_span_overlap=value
            )


def test_different_or_undeclared_anchoring_is_only_an_explicit_sensitivity(archive):
    archive.add("Alpha")
    archive.freeze()
    fresh, imported = archive.new(("a", "parent", 0, 5)), archive.load()
    common = compare_archival_reference(fresh, imported, source_texts=archive.texts)
    assert common["policy"]["comparison_status"] == "common_declared_anchoring_policy"
    for declared in ("whitespace_and_quotes_without_dash_conversion", None):
        fresh["benchmark_provenance"]["quote_anchoring_policy"] = declared
        with pytest.raises(ValueError, match="anchoring policies"):
            compare_archival_reference(fresh, imported, source_texts=archive.texts)
        sensitivity = compare_archival_reference(
            fresh, imported, source_texts=archive.texts, allow_asymmetric_anchoring=True
        )
        assert sensitivity["policy"]["comparison_status"] == "asymmetric_anchoring_sensitivity_only"
        assert sensitivity["policy"]["common_declared_anchoring_policy"] is False
        assert sensitivity["report_id"] != common["report_id"]


def test_normalization_is_cached_per_source(tmp_path, monkeypatch):
    import qualframe.archival_reference as module

    fixture = ImportFixture(tmp_path, "The “plan”—works. Several other words follow.")
    for _ in range(8):
        fixture.add('The "plan"-works.')
    fixture.freeze()
    original, seen = module._normalized, []

    def track(text):
        seen.append(text)
        return original(text)

    monkeypatch.setattr(module, "_normalized", track)
    assert len(fixture.load()["included"]) == 8
    assert seen.count(next(iter(fixture.texts.values()))) == 2


def test_unselected_sources_remain_hash_verified_and_addendum_unknown_codes_keep_scope(archive):
    archive.add("Alpha")
    archive.add("unknown", code=None, domain="Outcomes Addendum")
    archive.freeze()
    result = archive.load()
    fresh = archive.new()
    fresh["excluded"].append(
        dict(
            record_id="new-addendum",
            code_id=None,
            original_domain="OUTCOMES ADDENDUM",
            source=archive.ids["a"],
            issues=["Unknown code"],
        )
    )
    report = compare_archival_reference(fresh, result, source_texts=archive.texts)
    assert report["eligibility"]["new"]["out_of_scope_entries"] == 1
    assert report["eligibility"]["new"]["excluded_entries"] == 0
    assert report["eligibility"]["archival"]["out_of_scope_entries"] == 1
    (archive.source_root / "b.txt").write_text("Changed.", encoding="utf-8")
    with pytest.raises(ValueError, match="Source file"):
        archive.load(source_ids=[archive.ids["a"]])
