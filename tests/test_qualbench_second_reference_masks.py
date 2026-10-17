"""Synthetic assessment-mask and cohort checks for paired reference comparisons."""
from __future__ import annotations

import pytest

from qualframe.qualbench import build_qualbench
from test_qualbench import _set


def _reference(identity, positives=(), absences=()):
    result = _set(identity, positives, kind="reference")
    result["absences"] = [dict(source=source, code_id=code) for source, code in absences]
    return result


def _asymmetric_references():
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/one.txt", "c", 3, 5),
                           ("t/two.txt", "p", 0, 2), ("t/two.txt", "q", 3, 5)])
    first = _reference("reference:first", [("t/one.txt", "p", 0, 2), ("t/two.txt", "p", 0, 2)],
                       [("t/one.txt", "c"), ("t/one.txt", "q"), ("t/two.txt", "c")])
    second = _reference("reference:second", [("t/one.txt", "c", 3, 5), ("t/two.txt", "q", 3, 5)],
                        [("t/one.txt", "p"), ("t/two.txt", "c")])
    return model, first, second


def test_only_jointly_assessed_units_contribute_to_both_reference_metrics():
    model, first, second = _asymmetric_references()
    report = build_qualbench([model], reference=first, second_reference=second)

    assert report["reference_difference_assessment"] == dict(
        n_units_before_exclusions=6, first_assessed_units=5, second_assessed_units=4,
        jointly_assessed_units=3, first_only_assessed_units=2, second_only_assessed_units=1)
    # Joint cells are one/p, one/c and two/c. Positives outside them cannot affect prevalence.
    rows = report["reference_differences"]
    assert all(row["n_units"] == row["units_a"] == row["units_b"] == 3 for row in rows)
    assert all(row["prevalence_a"] == row["prevalence_b"] == pytest.approx(1 / 3) for row in rows)
    model_rows = {row["metric"]: row for row in rows if row["coding_set"] == "model"}
    for metric, expected in (("sensitivity", 1), ("specificity", .5), ("balanced_accuracy", .75)):
        assert model_rows[metric]["a"] == model_rows[metric]["b"] == expected
        assert model_rows[metric]["difference"] == 0


@pytest.mark.parametrize("unit_exclusions,document_exclusions,expected", [
    ("document,code\none.txt,p\n", None, (6, 4, 3, 2, 0, .5)),
    ("document,domain\none.txt,First Domain\n", None, (6, 3, 2, 1, 0, 0)),
    (None, "two.txt\n", (3, 3, 2, 2, .5, .5)),
    ("document,code\none.txt,p\n", "two.txt\n", (3, 2, 1, 1, 0, 1)),
])
def test_manual_exclusions_apply_to_both_reference_masks(tmp_path, unit_exclusions, document_exclusions, expected):
    model, first, second = _asymmetric_references()
    kwargs = {}
    if unit_exclusions is not None:
        path = tmp_path / "synthetic-excluded-units.csv"
        path.write_text(unit_exclusions, encoding="utf-8")
        kwargs["exclude_units"] = path
    if document_exclusions is not None:
        path = tmp_path / "synthetic-excluded-documents.txt"
        path.write_text(document_exclusions, encoding="utf-8")
        kwargs["exclude_documents"] = path

    report = build_qualbench([model], reference=first, second_reference=second, **kwargs)

    total, a, b, shared, prevalence_a, prevalence_b = expected
    assessment = report["reference_difference_assessment"]
    assert (assessment["n_units_before_exclusions"], assessment["first_assessed_units"],
            assessment["second_assessed_units"], assessment["jointly_assessed_units"]) == (total, a, b, shared)
    assert all(row["n_units"] == shared and row["prevalence_a"] == prevalence_a
               and row["prevalence_b"] == prevalence_b for row in report["reference_differences"])


def test_second_reference_content_remapping_and_shorter_cohort_preserve_original_absence_policy():
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/two.txt", "q", 0, 2)])
    first = _reference("reference:first", [("t/one.txt", "p", 0, 2)], [("t/one.txt", "q")])
    second = _reference("reference:second", [("other/copy.txt", "p", 0, 2)], [("other/extra.txt", "q")])
    second["sources"] = {"other/copy.txt": "h1", "other/extra.txt": "different-content"}

    report = build_qualbench([model], reference=first, second_reference=second, bootstrap=10, seed=3)

    assert report["transcripts"] == ["t/one.txt"]
    assert report["transcripts_left_out"] == ["other/extra.txt", "t/two.txt"]
    # The second reference's only absence is on the omitted document. It still establishes
    # its explicit assessment policy: unmentioned one/c and one/q are not negative cells.
    assert report["reference_difference_assessment"] == dict(
        n_units_before_exclusions=3, first_assessed_units=2, second_assessed_units=1,
        jointly_assessed_units=1, first_only_assessed_units=1, second_only_assessed_units=0)
    assert all(row["documents"] == row["n_units"] == 1 and row["prevalence_a"] == row["prevalence_b"] == 1
               for row in report["reference_differences"])
    sensitivity = next(row for row in report["reference_differences"]
                       if row["coding_set"] == "model" and row["metric"] == "sensitivity")
    assert sensitivity["a"] == sensitivity["b"] == 1
    assert sensitivity["difference"] == sensitivity["difference_lower"] == sensitivity["difference_upper"] == 0


def test_no_joint_assessed_units_are_reported_as_undefined_not_zero():
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/two.txt", "p", 0, 2)])
    first = _reference("reference:first", [("t/one.txt", "p", 0, 2)], [("t/one.txt", "q")])
    second = _reference("reference:second", [("t/two.txt", "p", 0, 2)], [("t/two.txt", "c")])

    report = build_qualbench([model], reference=first, second_reference=second, bootstrap=20, seed=1)

    assert report["reference_difference_assessment"]["jointly_assessed_units"] == 0
    assert any("No units are assessed in both references" in warning for warning in report["warnings"])
    assert len(report["reference_differences"]) == 12  # One model and two baselines, four measures each.
    for row in report["reference_differences"]:
        assert row["n_units"] == row["documents"] == row["folders"] == 0
        for key in ("a", "a_lower", "a_upper", "b", "b_lower", "b_upper", "difference",
                    "difference_lower", "difference_upper", "prevalence_a", "prevalence_b"):
            assert row[key] is None
        for suffix in ("", "_a", "_b"):
            assert row["valid_replicates" + suffix] == 0
            assert row["undefined_replicates" + suffix] == 20
