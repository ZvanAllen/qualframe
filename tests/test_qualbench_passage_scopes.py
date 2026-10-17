"""Synthetic passage-scope checks; no saved study or provider access."""
from __future__ import annotations

import csv
import json

import pytest

from qualframe.qualbench import MATCH_THRESHOLDS, build_qualbench, passage_agreement, write_qualbench


def _item(source, code, start=None, end=None, *, alternatives=None):
    row = {"source": source, "code_id": code}
    if start is not None:
        row.update(start=start, end=end)
    if alternatives:
        row["alternative_spans"] = [{"start": a, "end": b} for a, b in alternatives]
    return row


def _set(set_id, included=(), *, excluded=(), presence_only=(), kind="model_proposals"):
    return {
        "set_id": set_id, "label": set_id, "set_kind": kind,
        "sources": {"fictional/one.txt": "hash-one", "fictional/two.txt": "hash-two"},
        "codebook": {"id": "synthetic", "codes": [
            {"id": code, "label": code, "domain": "Synthetic"} for code in ("p", "q")
        ]},
        "included": list(included), "excluded": list(excluded),
        "presence_only": list(presence_only), "absences": [],
    }


def _scopes(left, right, **kwargs):
    return {scope: passage_agreement(left, right, versus_reference=False, scope=scope, **kwargs)
            for scope in ("all pairs", "shared positives")}


def test_shared_pairs_use_both_document_and_code_and_preserve_pooled_values():
    one, two = "fictional/one.txt", "fictional/two.txt"
    left = _set("left", [_item(one, "p", 0, 10), _item(one, "q", 20, 30), _item(two, "p", 0, 5)])
    right = _set("right", [_item(one, "p", 0, 10), _item(one, "q", 25, 40)])
    rows = _scopes(left, right)
    pooled, shared = rows["all pairs"], rows["shared positives"]

    # All pre-existing numeric pooled columns retain their hand-calculated values.
    expected = {
        "left_passages": 3, "right_passages": 2,
        "matched_exact": 1, "f1_exact": 2 / 5,
        "matched_iou_quarter": 2, "f1_iou_quarter": 4 / 5,
        "matched_iou_half": 1, "f1_iou_half": 2 / 5,
        "matched_iou_three_quarters": 1, "f1_iou_three_quarters": 2 / 5,
        "matched_any_overlap": 2, "f1_any_overlap": 4 / 5,
        "left_coded_text_passages_excluded": 0, "right_coded_text_passages_excluded": 0,
        "coded_text_passages_excluded": 0, "coded_text_jaccard": 15 / 35,
        "left_text_also_coded_by_right": 15 / 25, "right_text_also_coded_by_left": 15 / 25,
    }
    assert {key: pooled[key] for key in expected} == pytest.approx(expected)
    assert pooled["shared_positive_pairs"] == shared["shared_positive_pairs"] == 2
    assert (shared["left_passages"], shared["right_passages"]) == (2, 2)
    assert shared["f1_exact"] == 0.5
    assert shared["f1_iou_quarter"] == shared["f1_any_overlap"] == 1
    assert shared["coded_text_jaccard"] == 0.5
    assert shared["left_text_also_coded_by_right"] == 0.75
    assert shared["right_text_also_coded_by_left"] == 0.6
    assert pooled["transcript"] == shared["transcript"] == "All"


@pytest.mark.parametrize(("span", "matched"), [
    ((0, 100), (1, 1, 1, 1, 1)),
    ((0, 75), (0, 1, 1, 1, 1)),
    ((0, 50), (0, 1, 1, 0, 1)),
    ((0, 25), (0, 1, 0, 0, 1)),
    ((99, 100), (0, 0, 0, 0, 1)),
    ((100, 110), (0, 0, 0, 0, 0)),
])
def test_shared_scope_uses_exact_existing_match_thresholds(span, matched):
    source = "fictional/one.txt"
    left = _set("left", [_item(source, "p", 0, 100)])
    right = _set("right", [_item(source, "p", *span)])
    rows = _scopes(left, right)
    for row in rows.values():
        assert row["shared_positive_pairs"] == 1
        assert (row["left_passages"], row["right_passages"]) == (1, 1)
        for (name, _), count in zip(MATCH_THRESHOLDS, matched):
            assert row[f"matched_{name}"] == row[f"f1_{name}"] == count
    # A located pair is shared-positive even when its two passages do not overlap.
    assert rows["shared positives"]["coded_text_jaccard"] == (
        span[1] / 100 if span[0] == 0 else 0.01 if span[0] == 99 else 0)


def test_alternative_locations_count_as_one_passage_and_keep_text_exclusions():
    source = "fictional/one.txt"
    left = _set("left", [
        _item(source, "p", alternatives=[(0, 10), (20, 30)]),
        _item(source, "p", 40, 50),
        _item(source, "q", alternatives=[(60, 70), (80, 90)]),
    ])
    right = _set("right", [_item(source, "p", a, a + 10) for a in (0, 20, 40)])
    pooled, shared = _scopes(left, right).values()
    assert shared["shared_positive_pairs"] == 1
    assert (shared["left_passages"], shared["right_passages"]) == (2, 3)
    for name, _ in MATCH_THRESHOLDS:
        assert shared[f"matched_{name}"] == 2  # One alternative-bearing annotation cannot match twice.
        assert shared[f"f1_{name}"] == 4 / 5
    assert pooled["left_coded_text_passages_excluded"] == 2
    assert shared["left_coded_text_passages_excluded"] == shared["coded_text_passages_excluded"] == 1
    assert shared["right_coded_text_passages_excluded"] == 0
    assert shared["coded_text_jaccard"] == pytest.approx(1 / 3)
    assert shared["left_text_also_coded_by_right"] == 1
    assert shared["right_text_also_coded_by_left"] == pytest.approx(1 / 3)


def test_unlocated_or_presence_only_proposals_do_not_create_shared_positive_pairs():
    source = "fictional/one.txt"
    left = _set("left", [_item(source, "p", 0, 10), _item(source, "q", 20, 30)])
    right = _set("right", excluded=[_item(source, "p")], presence_only=[_item(source, "q")])
    shared = _scopes(left, right)["shared positives"]
    assert shared["shared_positive_pairs"] == shared["left_passages"] == shared["right_passages"] == 0
    for name, _ in MATCH_THRESHOLDS:
        assert shared[f"matched_{name}"] == 0
        assert shared[f"f1_{name}"] is None
    for key in ("coded_text_jaccard", "left_text_also_coded_by_right", "right_text_also_coded_by_left"):
        assert shared[key] is None


def test_individual_document_and_code_presence_is_not_a_shared_pair():
    one, two = "fictional/one.txt", "fictional/two.txt"
    left = _set("left", [_item(one, "p", 0, 10), _item(two, "q", 0, 10)])
    right = _set("right", [_item(one, "q", 0, 10), _item(two, "p", 0, 10)])
    rows = _scopes(left, right)
    assert rows["all pairs"]["left_passages"] == rows["all pairs"]["right_passages"] == 2
    assert rows["shared positives"]["shared_positive_pairs"] == 0
    assert rows["shared positives"]["left_passages"] == rows["shared positives"]["right_passages"] == 0


def test_shared_scope_builds_overall_and_per_document_rows_and_exports(tmp_path):
    one, two = "fictional/one.txt", "fictional/two.txt"
    left = _set("left", [_item(one, "p", 0, 10), _item(two, "q", 0, 10)])
    right = _set("right", [_item(one, "p", 0, 10)])
    reference = _set("reference:synthetic", [_item(one, "p", 0, 10)], kind="reference")
    report = build_qualbench([left, right], reference=reference)
    rows = [row for row in report["passages"] if row["left"] == "left" and row["right"] == "right"]
    assert [(row["scope"], row["transcript"]) for row in rows] == [
        (scope, transcript) for scope in ("all pairs", "shared positives")
        for transcript in ("All", "one.txt", "two.txt")
    ]
    by_scope = {(row["scope"], row["transcript"]): row for row in rows}
    assert by_scope[("shared positives", "All")]["shared_positive_pairs"] == 1
    assert by_scope[("shared positives", "one.txt")]["shared_positive_pairs"] == 1
    assert by_scope[("shared positives", "two.txt")]["shared_positive_pairs"] == 0
    assert by_scope[("shared positives", "two.txt")]["f1_exact"] is None
    assert by_scope[("all pairs", "two.txt")]["f1_exact"] == 0
    reference_rows = [row for row in report["passages"] if row["right"] == "reference:synthetic"]
    assert {row["scope"] for row in reference_rows} == {"all pairs", "shared positives"}
    assert all(row["comparison"] == "versus reference" for row in reference_rows)
    folder = write_qualbench(report, tmp_path / "synthetic-report")
    saved = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert saved["passages"] == report["passages"]
    with (folder / "passages.csv").open(newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert len(exported) == len(report["passages"])
    assert {row["scope"] for row in exported} == {"all pairs", "shared positives"}
    assert {row["transcript"] for row in exported} == {"All", "one.txt", "two.txt"}


def test_passage_scope_rejects_unknown_scope():
    with pytest.raises(ValueError, match="Passage scope"):
        passage_agreement(_set("left"), _set("right"), versus_reference=False, scope="unknown")
