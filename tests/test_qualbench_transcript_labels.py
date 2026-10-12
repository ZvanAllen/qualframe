import pytest

from qualframe.qualbench import build_qualbench, passage_agreement
from test_qualbench import _set


def _duplicates():
    left = _set("left", [("a/shared.txt", "p", 0, 5), ("b/shared.txt", "p", 0, 5)])
    right = _set("right", [("a/shared.txt", "p", 0, 5)])
    for coding in [left, right]:
        coding["sources"] = {"a/shared.txt": "one", "b/shared.txt": "two", "c/unique.txt": "three"}
    return left, right


def test_duplicate_filenames_have_separate_presence_passage_and_mean_rows():
    report = build_qualbench(list(_duplicates()))
    presence = {row["scope"]: row for row in report["presence"]
                if row["level"] == "code" and row["scope_kind"] == "transcript"}
    assert set(presence) == {"a/shared.txt", "b/shared.txt", "unique.txt"}
    assert all(row["n_units"] == 3 for row in presence.values())
    assert presence["a/shared.txt"]["both"] == 1 and presence["b/shared.txt"]["both"] == 0
    macro = next(row for row in report["presence"] if row["level"] == "code" and row["scope_kind"] == "transcript mean")
    assert macro["percent_agreement"] == pytest.approx((1 + 2 / 3 + 1) / 3)
    passage = {row["scope"]: row for row in report["passages"] if row["scope_kind"] == "transcript"}
    assert set(passage) == set(presence)
    assert passage["a/shared.txt"]["matched_exact"] == 1
    assert passage["b/shared.txt"]["matched_exact"] == 0
    unit_keys = [(row["coding_set"], row["transcript"], row["code_id"]) for row in report["units"]]
    assert len(unit_keys) == len(set(unit_keys)) == 18
    assert {row["transcript"] for row in report["units"]} == set(presence)


def test_direct_passage_comparison_uses_the_same_unique_label():
    left, right = _duplicates()
    assert passage_agreement(left, right, versus_reference=False, source="b/shared.txt")["scope"] == "b/shared.txt"
