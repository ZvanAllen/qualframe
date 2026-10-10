import json

import pytest
from test_benchmark_metrics import payload
from test_run_comparison import runs

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.benchmark_reporting import benchmark_bundle_directory
from qualframe.benchmark_ui import render_benchmark, save_benchmark_form
from qualframe.comparison_ui import render_comparison
from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import raw_coding_payload


def workspace(tmp_path):
    project, left, right, _ = runs(tmp_path)
    app = DashboardApp(ProjectRunner(project))
    report = build_benchmark_report(
        raw_coding_payload(app.repo_root, left), raw_coding_payload(app.repo_root, right)
    )
    form = {
        "run_id": [left.name],
        "right_id": [right.name],
        "study_identity": [app.runner.project.project_id],
        "report_id": [snapshot_identity(report)],
    }
    return app, left, right, report, form


def test_selected_pair_link_and_read_only_detailed_workspace(tmp_path):
    app, left, right, report, form = workspace(tmp_path)
    comparison = render_comparison(app, left.name, right.name)
    assert f"/benchmark?left={left.name}&amp;right={right.name}" in comparison
    page = render_benchmark(app, left.name, right.name)
    for label in (
        "Detailed span benchmark",
        "Exact span F1",
        "Overlap F1 at 0.25",
        "Overlap F1 at 0.50",
        "Overlap F1 at 0.75",
        "What entered these scores",
        "Human edits and assumed test acceptance are excluded",
        "Inspect passages",
        "Matched pairs only",
    ):
        assert label in page
    identifier = report["inputs"]["left"]["included"][0]["record_id"]
    assert f"/evidence?run_id={left.name}&amp;item={identifier}" in page
    assert form["report_id"][0] in page
    assert page.count("<!DOCTYPE html>") + page.count("<!doctype html>") == 1
    assert not (left / "benchmarks").exists()


def test_save_binds_displayed_snapshot_and_provides_verified_downloads(tmp_path):
    app, left, right, report, form = workspace(tmp_path)
    identifier, message = app.handle_action("/benchmark/save", form)
    assert identifier == left.name and "Saved frozen span benchmark" in message
    bundle = benchmark_bundle_directory(report, left / "benchmarks")
    assert {item.name for item in bundle.iterdir()} == {"report.json", "by_code.csv", "index.html"}
    assert json.loads((bundle / "report.json").read_text(encoding="utf-8")) == report
    before = {item.name: item.read_bytes() for item in bundle.iterdir()}
    save_benchmark_form(app, form)
    assert before == {item.name: item.read_bytes() for item in bundle.iterdir()}
    page = render_benchmark(app, left.name, right.name)
    assert "Download frozen benchmark JSON" in page and "Download per-code CSV" in page


@pytest.mark.parametrize("filename", ["report.json", "by_code.csv"])
def test_modified_saved_files_disable_downloads_and_are_not_overwritten(tmp_path, filename):
    app, left, right, report, form = workspace(tmp_path)
    save_benchmark_form(app, form)
    bundle = benchmark_bundle_directory(report, left / "benchmarks")
    path = bundle / filename
    if filename.endswith("json"):
        altered = dict(report, project_id="changed")
        path.write_text(json.dumps(altered), encoding="utf-8")
    else:
        path.write_text("changed csv", encoding="utf-8")
    modified = path.read_bytes()
    page = render_benchmark(app, left.name, right.name)
    assert "Saved benchmark files could not be verified" in page
    assert "Download frozen benchmark JSON" not in page and "Download per-code CSV" not in page
    with pytest.raises(ValueError, match="Stored benchmark bundle changed"):
        save_benchmark_form(app, form)
    assert path.read_bytes() == modified


def test_cross_study_unknown_pair_missing_identity_and_stale_inputs_block_save(tmp_path):
    app, left, right, _, form = workspace(tmp_path)
    with pytest.raises(ValueError, match="another study"):
        save_benchmark_form(app, dict(form, study_identity=["other"]))
    with pytest.raises(ValueError, match="Missing benchmark field"):
        save_benchmark_form(app, dict(form, report_id=[""]))
    with pytest.raises(ValueError, match="Choose two coding runs"):
        save_benchmark_form(app, dict(form, run_id=["../outside"]))
    with pytest.raises(ValueError, match="distinct runs"):
        render_benchmark(app, left.name, left.name)
    # The JSON still parses and retains the same records, but its input identity changed.
    index = right / "evidence_review/index.json"
    index.write_bytes(index.read_bytes() + b" ")
    with pytest.raises(ValueError, match="inputs changed after display"):
        save_benchmark_form(app, form)
    assert not (left / "benchmarks").exists()


def test_missing_pair_and_empty_sets_are_explicit_without_writes(tmp_path, monkeypatch):
    app, left, right, _, _ = workspace(tmp_path)
    assert "Choose two coding runs first" in render_benchmark(app)
    monkeypatch.setattr(
        "qualframe.benchmark_ui.raw_coding_payload",
        lambda repo_root, root: payload(root.name),
    )
    page = render_benchmark(app, left.name, right.name)
    assert "Undefined" in page and "2 codes with no spans in either run" in page
    assert "does not establish that the construct is absent" in page
    assert not (left / "benchmarks").exists()


def test_details_escape_quotes_and_expose_ambiguous_catalog_diagnostics(tmp_path, monkeypatch):
    app, left, right, _, _ = workspace(tmp_path)

    def raw(repo_root, root):
        result = payload(root.name, [("s1", "c1", 0, 10)])
        result["included"][0]["exact_text"] = '<script>alert("test")</script>'
        result["codebook"]["codes"].append(dict(id="c2", label="Different definition"))
        return result

    monkeypatch.setattr("qualframe.benchmark_ui.raw_coding_payload", raw)
    page = render_benchmark(app, left.name, right.name)
    assert "&lt;script&gt;alert(&quot;test&quot;)&lt;/script&gt;" in page
    assert '<script>alert("test")</script>' not in page
    assert "Frozen catalog diagnostics" in page and "Ambiguous duplicate code ID" in page
    assert "ambiguous definitions; no included spans" in page
