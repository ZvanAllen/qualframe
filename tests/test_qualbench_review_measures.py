from copy import deepcopy
import csv
import random
import subprocess
import sys
from pathlib import Path

import pytest

from qualframe.qualbench import build_qualbench, reference_statistics, write_qualbench
from qualframe.qualbench_presence import accuracy_statistics, bootstrap_intervals, sample_documents
from test_qualbench import _set


def reference(included=(), absences=()):
    result = _set("reference:ref", included, kind="reference")
    result["statement"] = "Synthetic reference."
    result["absences"] = [dict(source=source, code_id=code) for source, code in absences]
    return result


def row(report, left="model", level="code", kind="all", scope="All"):
    return next(r for r in report["presence"] if r["left"] == left and r["right"] == "reference:ref"
                and r["level"] == level and r["scope_kind"] == kind and r["scope"] == scope)


def test_absence_sensitive_statistics_and_undefined_denominators():
    stats = reference_statistics(20, 5, 10, 15)
    assert stats["sensitivity"] == stats["recall"] == pytest.approx(2 / 3)
    assert stats["specificity"] == .75
    assert stats["balanced_accuracy"] == pytest.approx((2 / 3 + .75) / 2)
    assert stats["mcc"] == pytest.approx(250 / (25 * 30 * 20 * 25) ** .5)
    for counts in ((0, 0, 0, 5), (5, 0, 0, 0), (0, 0, 0, 0), (0, 5, 0, 0)):
        assert accuracy_statistics(*counts)["mcc"] is None
    assert accuracy_statistics(0, 0, 0, 5)["balanced_accuracy"] is None
    assert accuracy_statistics(0, 0, 5, 5)["balanced_accuracy"] == .5
    assert accuracy_statistics(0, 5, 5, 0)["mcc"] == -1


def test_missing_reference_cells_are_not_negatives_in_any_presence_measure(tmp_path):
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/two.txt", "q", 0, 2)])
    twin = dict(deepcopy(model), set_id="twin")
    ref = reference([("t/one.txt", "p", 0, 2)], [("t/one.txt", "q")])
    report = build_qualbench([model, twin], reference=ref, stability_groups=[["model", "twin"]])
    pooled = row(report)
    assert pooled["n_units"] == 2 and pooled["neither"] == 1 and pooled["left_only"] == 0
    assert pooled["reference_not_assessed"] == pooled["excluded_units"] == 4
    pair = next(r for r in report["presence"] if r["left"] == "model" and r["right"] == "twin" and r["scope_kind"] == "all" and r["level"] == "code")
    assert pair["n_units"] == report["stability"][0]["n_units"] == 2
    excluded = [r for r in report["units"] if not r["assessed"]]
    assert len(excluded) == 12 and all(r["present"] is None for r in excluded)
    assert any(r["observed_present"] == 1 for r in excluded)
    folder = write_qualbench(report, tmp_path / "report")
    assert "reference_not_assessed: 4" in (folder / "README.md").read_text()
    rows = list(csv.DictReader((folder / "units.csv").open()))
    assert all(r["present"] == "" for r in rows if r["assessed"] == "False")


def test_parent_is_positive_from_an_assessed_child_but_partial_absence_is_unknown():
    model = _set("model", [("t/one.txt", "c", 0, 2), ("t/two.txt", "c", 0, 2)])
    ref = reference([("t/one.txt", "c", 0, 2)], [("t/two.txt", "c"), ("t/one.txt", "q"), ("t/two.txt", "q")])
    report = build_qualbench([model], reference=ref)
    parent = row(report, level="parent code")
    assert parent["n_units"] == 3 and parent["both"] == 1 and parent["neither"] == 2
    assert parent["parent_not_fully_assessed"] == 1
    assert row(report, left="baseline:always-present", level="parent code")["n_units"] == 3


def test_manual_code_and_domain_exclusions_are_deduplicated_and_audited(tmp_path):
    model = _set("model", [("t/one.txt", "p", 0, 2)])
    ref = reference([("t/one.txt", "p", 0, 2)], [("t/two.txt", "q")])
    excluded = tmp_path / "units.csv"
    excluded.write_text("document,code\none.txt,p\none.txt,p\ntwo.txt,c\n")
    report = build_qualbench([model], reference=ref, exclude_units=excluded)
    assert row(report)["excluded_units"] == 5 and row(report)["excluded_code"] == 2
    assert row(report)["reference_not_assessed"] == 4  # Reasons overlap on two/c.
    assert len(report["unit_exclusions_requested"]) == 2
    excluded.write_text("document,domain\none.txt,First Domain\n")
    domain_report = build_qualbench([model], reference=ref, exclude_units=excluded)
    assert row(domain_report)["excluded_domain"] == 2
    assert row(domain_report, level="parent code")["both"] == 0


def test_no_absence_reference_keeps_implicit_negatives_and_masks_still_apply_without_reference(tmp_path):
    model = _set("model", [])
    ref = reference()
    assert row(build_qualbench([model], reference=ref))["n_units"] == 6
    excluded = tmp_path / "units.csv"
    excluded.write_text("document,domain\none.txt,First\n")
    report = build_qualbench([model, dict(deepcopy(model), set_id="twin")], exclude_units=excluded)
    assert report["presence"][0]["n_units"] == 4


def test_baselines_cover_exact_same_levels_and_scopes_and_ignore_model_proposals():
    model = _set("model", [])
    ref = reference([("t/one.txt", "p", 0, 2)])
    report = build_qualbench([model], reference=ref)
    actual = {(r["level"], r["scope_kind"], r["scope"]): r for r in report["presence"] if r["left"] == "model"}
    for baseline in ("baseline:always-present", "baseline:always-absent"):
        rows = {(r["level"], r["scope_kind"], r["scope"]): r for r in report["presence"] if r["left"] == baseline}
        assert rows.keys() == actual.keys()
        assert all(r["n_units"] == actual[key]["n_units"] for key, r in rows.items())
    positive, negative = row(report, "baseline:always-present"), row(report, "baseline:always-absent")
    assert (positive["both"], positive["left_only"], positive["right_only"], positive["neither"]) == (1, 5, 0, 0)
    assert (negative["both"], negative["left_only"], negative["right_only"], negative["neither"]) == (0, 0, 1, 5)
    assert positive["balanced_accuracy"] == negative["balanced_accuracy"] == .5
    assert positive["mcc"] is negative["mcc"] is None
    assert len(report["coding_sets"]) == 2


def test_codes_table_prevalence_counts_and_unassessed_code():
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/two.txt", "p", 0, 2)])
    ref = reference([("t/one.txt", "p", 0, 2)], [("t/two.txt", "p")])
    report = build_qualbench([model], reference=ref)
    codes = {r["code_id"]: r for r in report["codes_table"]}
    assert codes["p"]["reference_prevalence"] == .5 and codes["p"]["set_prevalence"] == 1
    assert codes["p"]["true_positive"] == codes["p"]["false_positive"] == 1
    assert codes["p"]["f1"] == pytest.approx(2 / 3)
    assert codes["c"]["n_units"] == 0 and codes["c"]["reference_prevalence"] is None


def test_document_exclusion_removes_every_compared_table_but_keeps_absence_policy(tmp_path):
    model = _set("model", [("t/one.txt", "p", 0, 2), ("t/two.txt", "q", 0, 2)])
    ref = reference([("t/one.txt", "p", 0, 2)], [("t/two.txt", "q")])
    excluded = tmp_path / "documents.txt"
    excluded.write_text("two.txt\n\ntwo.txt\n")
    report = build_qualbench([model], reference=ref, exclude_documents=excluded)
    assert report["transcripts"] == ["t/one.txt"]
    assert report["documents_excluded"] == ["t/two.txt"]
    assert row(report)["n_units"] == 1  # Absence on removed document still establishes original policy.
    assert report["coding_sets"][0]["coded_passages"] == 1
    assert report["passages"][0]["left_passages"] == 1
    assert all(r["transcript"] == "one.txt" for r in report["units"])


@pytest.mark.parametrize("content", ["document,other\none.txt,p\n", "document,code\nmissing.txt,p\n", "document,code\none.txt,unknown\n", "document,code\none.txt,\n", "document,code\none.txt,p,extra\n", "document,domain\none.txt,Missing\n"])
def test_invalid_exclusion_files_fail_closed(tmp_path, content):
    file = tmp_path / "bad.csv"; file.write_text(content)
    with pytest.raises(ValueError):
        build_qualbench([_set("model", [])], reference=reference(), exclude_units=file)


def test_ambiguous_document_basename_requires_path(tmp_path):
    model = _set("model", []); model["sources"] = {"a/doc.txt": "h1", "b/doc.txt": "h2"}
    ref = dict(deepcopy(model), set_id="reference:ref", set_kind="reference")
    file = tmp_path / "exclude.txt"; file.write_text("doc.txt")
    with pytest.raises(ValueError, match="matches 2"):
        build_qualbench([model], reference=ref, exclude_documents=file)
    file.write_text("b/doc.txt")
    assert build_qualbench([model], reference=ref, exclude_documents=file)["transcripts"] == ["a/doc.txt"]
    file.write_text("a/doc.txt\nb/doc.txt")
    with pytest.raises(ValueError, match="No common"):
        build_qualbench([model], reference=ref, exclude_documents=file)


def test_document_bootstrap_matches_hand_enumerated_extremes_and_is_paired():
    data = {("one", "code", "all", "All"): {"a/1": [1, 0, 0, 1], "a/2": [0, 1, 1, 0]},
            ("twin", "code", "all", "All"): {"a/1": [1, 0, 0, 1], "a/2": [0, 1, 1, 0]}}
    rows = bootstrap_intervals(data, ["a/1", "a/2"], ["one", "twin"], "ref", 500, 73, False)
    f1 = next(r for r in rows if r["left"] == "one" and r["kind"] == "estimate" and r["metric"] == "f1")
    assert (f1["lower_95"], f1["estimate"], f1["upper_95"]) == (0, .5, 1)
    assert all(r["lower_95"] == r["upper_95"] == r["estimate"] == 0 for r in rows if r["kind"] == "paired_difference")
    assert rows == bootstrap_intervals(data, ["a/1", "a/2"], ["one", "twin"], "ref", 500, 73, False)


def test_bootstrap_undefined_and_pairwise_valid_counts_are_explicit():
    data = {("positive", "code", "all", "All"): {"a/1": [1, 1, 0, 0], "a/2": [1, 1, 0, 0]},
            ("negative", "code", "all", "All"): {"a/1": [0, 0, 1, 1], "a/2": [0, 0, 1, 1]}}
    rows = bootstrap_intervals(data, ["a/1", "a/2"], ["positive", "negative"], "ref", 20, 1, False)
    assert all(r["valid_replicates"] == 0 and r["undefined_replicates"] == 20
               and r["lower_95"] is None for r in rows if r["metric"] == "mcc")
    assert all(r["valid_replicates"] == 20 for r in rows if r["metric"] == "balanced_accuracy")


def test_hierarchical_resampling_draws_folders_then_their_own_documents():
    class Draw:
        def __init__(self): self.calls = []
        def choices(self, population, k):
            self.calls.append((population, k))
            return [population[0]] * k
    rng = Draw()
    assert sample_documents(rng, ["a/1", "a/2", "b/3"], True) == ["a/1"] * 4
    assert rng.calls == [(["a", "b"], 2), (["a/1", "a/2"], 2), (["a/1", "a/2"], 2)]
    rng = Draw()
    assert sample_documents(rng, ["a/1", "a/2", "b/3"], False) == ["a/1"] * 3
    assert len(rng.calls) == 1


def test_bootstrap_integration_same_point_estimates_and_masked_units():
    model = _set("model", [("t/one.txt", "p", 0, 2)])
    ref = reference([("t/one.txt", "p", 0, 2)], [("t/one.txt", "q"), ("t/two.txt", "q")])
    report = build_qualbench([model, dict(deepcopy(model), set_id="twin")], reference=ref, bootstrap=30, seed=47, cluster_by_folder=True)
    presence = {(r["left"], r["level"], r["scope_kind"], r["scope"]): r for r in report["presence"] if r["comparison"] == "versus reference"}
    for interval in report["bootstrap"]:
        if interval["kind"] == "estimate":
            point = presence[(interval["left"], interval["level"], interval["scope_kind"], interval["scope"])][interval["metric"]]
            assert interval["estimate"] == pytest.approx(point) if point is not None else interval["estimate"] is None
    assert all(r["resampling"] == "folders_then_documents" for r in report["bootstrap"])


def test_bootstrap_defaults_and_invalid_requests():
    model = _set("model", [])
    assert build_qualbench([model], reference=reference())["bootstrap"] == []
    for kwargs in (dict(bootstrap=-1), dict(bootstrap=1.5), dict(cluster_by_folder=True)):
        with pytest.raises(ValueError):
            build_qualbench([model], reference=reference(), **kwargs)
    with pytest.raises(ValueError, match="reference"):
        build_qualbench([model, dict(deepcopy(model), set_id="twin")], bootstrap=20)


def test_cli_help_names_new_options():
    script = Path(__file__).resolve().parents[1] / "scripts/qualbench.py"
    result = subprocess.run([sys.executable, str(script), "compare", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for option in ("--exclude-units", "--exclude-documents", "--bootstrap", "--seed", "--cluster-by-folder"):
        assert option in result.stdout


@pytest.mark.parametrize("header,values", [
    ("document,code,code", "one.txt,p,q"),
    ("document,document,code", "one.txt,two.txt,p"),
    ("document,domain,domain", "one.txt,First,Outcomes Addendum"),
])
def test_duplicate_exclusion_headers_are_rejected_instead_of_overwriting_columns(tmp_path, header, values):
    excluded = tmp_path / "duplicate-headers.csv"
    excluded.write_text(header + "\n" + values + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly document,code or document,domain"):
        build_qualbench([_set("model", [])], reference=reference(), exclude_units=excluded)


def test_bootstrap_folder_metadata_matches_single_directory_for_bare_source_paths():
    data = {("model", "code", "all", "All"): {
        "one.txt": [1, 0, 0, 1], "two.txt": [0, 1, 1, 0],
    }}
    rows = bootstrap_intervals(data, ["one.txt", "two.txt"], ["model"], "ref", 10, 4, True)
    assert rows
    assert all(r["folders"] == 1 and r["documents"] == 2 for r in rows)
    assert all(r["resampling"] == "folders_then_documents" for r in rows)


def test_words_candidates_count_as_located_in_a_separate_qualbench_profile_column():
    model = _set("model", [
        ("t/one.txt", "p", 0, 2), ("t/one.txt", "c", 3, 5), ("t/two.txt", "q", 0, 2),
    ])
    for item, method in zip(model["included"], [
        "unique_exact_quote", "normalized_quote_candidate", "normalized_words_candidate",
    ], strict=True):
        item["anchoring_method"] = method
    ref = reference([("t/two.txt", "q", 0, 2)])
    ref["included"][0]["anchoring_method"] = "normalized_words_candidate"
    report = build_qualbench([model], reference=ref)
    profiles = {profile["set_id"]: profile for profile in report["coding_sets"]}
    model_profile = profiles["model"]
    assert model_profile["passages_located"] == model_profile["passages_uniquely_located"] == 3
    assert model_profile["located_exactly"] == model_profile["located_after_typography"] == 1
    assert model_profile["located_after_word_normalization"] == 1
    ref_profile = profiles["reference:ref"]
    assert ref_profile["passages_located"] == ref_profile["located_after_word_normalization"] == 1
    assert ref_profile["located_exactly"] == ref_profile["located_after_typography"] == 0
    assert model_profile["quotations_not_found"] == ref_profile["quotations_not_found"] == 0
