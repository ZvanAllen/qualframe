from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from qualframe.qualbench import build_qualbench, write_qualbench
from qualframe.qualbench_references import reference_differences
from test_qualbench import _set


def inputs():
    predicted = [("t/one.txt", "p", 0, 2), ("t/one.txt", "c", 3, 5), ("t/two.txt", "q", 0, 2)]
    model = _set("model", predicted)
    first = dict(_set("reference:a", [("t/one.txt", "p", 0, 2), ("t/two.txt", "c", 0, 2)], kind="reference"), statement="Synthetic")
    second = dict(_set("reference:b", predicted, kind="reference"), statement="Synthetic")
    return model, first, second


def test_reference_differences_match_independent_hand_counts_and_baselines(tmp_path):
    model, first, second = inputs()
    report = build_qualbench([model], reference=first, second_reference=second)
    rows = {r["metric"]: r for r in report["reference_differences"] if r["coding_set"] == "model"}
    # First: TP1 FP2 FN1 TN2; second: TP3 FP0 FN0 TN3.
    expected = {"sensitivity": (.5, 1), "specificity": (.5, 1), "balanced_accuracy": (.5, 1), "mcc": (0, 1)}
    for metric, (a, b) in expected.items():
        row = rows[metric]
        assert (row["a"], row["b"], row["difference"]) == pytest.approx((a, b, b-a))
        assert row["n_units"] == row["units_a"] == row["units_b"] == 6
        assert row["prevalence_a"] == pytest.approx(2/6)
        assert row["prevalence_b"] == .5
        assert row["a_lower"] is row["b_upper"] is row["difference_lower"] is None
        assert row["difference_direction"] == "second minus first"
    assert len(report["reference_differences"]) == 12
    for row in report["reference_differences"]:
        if row["baseline"] and row["metric"] == "mcc":
            assert row["a"] is row["b"] is row["difference"] is None
    output = write_qualbench(report, tmp_path / "report")
    with (output / "reference_differences.csv").open(newline="", encoding="utf-8") as f:
        saved = list(csv.DictReader(f))
    assert len(saved) == 12
    assert all(r["difference"] == "" for r in saved if r["baseline"] and r["metric"] == "mcc")
    assert json.loads((output / "report.json").read_text())["reference_differences"] == report["reference_differences"]
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "second minus first" in readme and "jointly" in readme


def test_paired_draws_identical_references_have_exactly_zero_defined_differences():
    model, first, _ = inputs()
    second = dict(deepcopy(first), set_id="reference:b")
    report = build_qualbench([model], reference=first, second_reference=second, bootstrap=200, seed=1)
    for row in report["reference_differences"]:
        assert row["a"] == row["b"]
        assert row["a_lower"] == row["b_lower"] and row["a_upper"] == row["b_upper"]
        if row["valid_replicates"]:
            assert row["difference_lower"] == row["difference_upper"] == 0
        else:
            assert row["difference_lower"] is row["difference_upper"] is None
        assert row["valid_replicates"] + row["undefined_replicates"] == 200
    again = build_qualbench([model], reference=first, second_reference=second, bootstrap=200, seed=1)
    assert report["reference_differences"] == again["reference_differences"]


def test_opposite_references_and_folder_draws_are_shared_across_all_sets(monkeypatch):
    calls = []
    def draw(rng, sources, cluster):
        calls.append((list(sources), cluster))
        return ["a/one"] * 2 + ["b/three"]  # Document multiplicity, not unique documents.
    monkeypatch.setattr("qualframe.qualbench_references.sample_documents", draw)
    units = [(s, c) for s in ("a/one", "a/two", "b/three", "z/empty") for c in ("x", "y") if s != "z/empty"]
    first = {("a/one", "x"), ("a/two", "x"), ("b/three", "y")}
    second = set(units) - first
    rows = reference_differences({"model": first, "twin": first}, {}, first, second, units,
                                ["a/one", "a/two", "b/three", "z/empty"], "a", "b", 30, 71, True)
    assert len(calls) == 30 and all(c == (["a/one", "a/two", "b/three"], True) for c in calls)
    for row in rows:
        assert row["documents"] == 3 and row["folders"] == 2
        assert row["resampling"] == "folders_then_documents"
        assert row["difference"] == (-2 if row["metric"] == "mcc" else -1)
        assert row["difference_lower"] == row["difference_upper"] == row["difference"]


def test_existing_tables_unchanged_when_second_reference_has_different_assessment():
    model, first, second = inputs()
    second["absences"] = [dict(source="t/one.txt", code_id="q")]
    old = build_qualbench([model], reference=first, bootstrap=20, seed=7)
    new = build_qualbench([model], reference=first, second_reference=second, bootstrap=20, seed=7)
    for table in ("presence", "bootstrap", "codes_table", "units", "passages", "stability", "coding_sets", "exclusions"):
        assert old[table] == new[table]
    assert old["reference_differences"] == []
    assert new["reference_difference_assessment"]["jointly_assessed_units"] == 4


def test_report_provenance_and_legacy_readme(monkeypatch, tmp_path):
    model, first, _ = inputs()
    provenance = {"git_commit": "ab" * 20, "git_dirty": False}
    monkeypatch.setattr("qualframe.qualbench.get_code_provenance", lambda: provenance)
    report = build_qualbench([model], reference=first)
    assert report["git_commit"] == provenance["git_commit"] and report["git_dirty"] is False
    assert report["qualframe_version"] == "0.11.0"
    out = write_qualbench(report, tmp_path / "new")
    text = (out / "README.md").read_text(encoding="utf-8")
    assert "Git commit: " + provenance["git_commit"] in text and "uncommitted changes: no" in text
    for key in ("git_commit", "git_dirty", "qualframe_version", "second_reference", "reference_differences"):
        report.pop(key, None)
    legacy = write_qualbench(report, tmp_path / "old")
    assert "Git commit: not recorded; uncommitted changes: not recorded" in (legacy / "README.md").read_text()


def test_second_reference_requires_first_and_rejects_duplicate_ids():
    model, first, second = inputs()
    with pytest.raises(ValueError, match="requires"):
        build_qualbench([model], second_reference=second)
    with pytest.raises(ValueError, match="once"):
        build_qualbench([model], reference=first, second_reference=first)
    script = Path(__file__).resolve().parents[1] / "scripts" / "qualbench.py"
    result = subprocess.run([sys.executable, str(script), "compare", "--study", "does-not-exist", "--second-reference", "b"], capture_output=True, text=True)
    assert result.returncode == 2 and "--second-reference requires --reference" in result.stderr


def test_cli_wires_both_saved_references_and_requested_bootstrap(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("qualbench_script_for_test", root / "scripts" / "qualbench.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model, first, second = inputs()
    monkeypatch.setattr(module, "_study", lambda study: (tmp_path / "project.yaml", tmp_path))
    monkeypatch.setattr(module, "load_project_manifest", lambda project: SimpleNamespace(paths={"artifacts": "artifacts"}))
    monkeypatch.setattr(module, "resolve_repo_path", lambda repo, path: repo / path)
    monkeypatch.setattr(module, "run_coding_set", lambda repo, path: model)
    monkeypatch.setattr(module, "reference_folder", lambda project, id: tmp_path / id)
    loaded = []
    def load(path, repo):
        loaded.append(path.parent.name)
        return first if path.parent.name == "a" else second
    monkeypatch.setattr(module, "load_reference_coding", load)
    monkeypatch.setattr(module, "reference_coding_set", lambda ref: ref)
    out = tmp_path / "report"
    module.compare(SimpleNamespace(study="project", run=["model"], reference="a", second_reference="b", stability=None,
                                   exclude_units=None, exclude_documents=None, bootstrap=10, seed=1, cluster_by_folder=True, out=str(out)))
    assert loaded == ["a", "b"]
    result = json.loads((out / "report.json").read_text())
    assert result["bootstrap_settings"] == dict(replicates=10, seed=1, cluster_by_folder=True)
    assert result["second_reference"]["set_id"] == "reference:b"
    assert len(result["reference_differences"]) == 12
