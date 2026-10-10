import copy

import pytest
from test_run_comparison import runs

from qualframe.repeat_comparison import build_repeat_report, compare_collection, write_repeat_report
from qualframe.run_comparison import raw_coding_payload


def test_three_runs_distinguish_configuration_pairs_and_keep_denominators(tmp_path):
    project, a, b, _ = runs(tmp_path)
    left = raw_coding_payload(project.parents[2], a)
    second = raw_coding_payload(project.parents[2], b)
    third = copy.deepcopy(second)
    third["run_id"] = "third"
    third["configuration_fingerprint"] = "different-provider-configuration"
    third["included"][0]["start"] += 1
    report = compare_collection([left, second, third])
    assert report["possible_pairs"] == report["eligible_pairs"] == 3
    same = report["summaries"]["same_configuration"]
    different = report["summaries"]["different_configuration"]
    assert same["eligible_pairs"] == 1 and different["eligible_pairs"] == 2
    assert same["metrics"]["exact_span_jaccard"]["mean"] == 1
    assert 0 < different["metrics"]["exact_span_jaccard"]["mean"] < 1
    assert different["metrics"]["code_jaccard"]["mean"] == 1


def test_failures_incompatible_pairs_and_empty_unions_are_never_silently_removed(tmp_path):
    project, a, b, _ = runs(tmp_path)
    left = raw_coding_payload(project.parents[2], a)
    second = copy.deepcopy(left)
    second["run_id"] = "other-cohort"
    second["sources"] = {}
    report = compare_collection(
        [left, second], [{"run_id": "failed", "reason": "Incomplete coding"}]
    )
    assert report["selected_run_count"] == 3 and report["possible_pairs"] == 3
    assert report["eligible_pairs"] == 0 and report["unavailable_pairs"] == 2
    assert len(report["incompatible_pairs"]) == len(report["unavailable_runs"]) == 1
    second = copy.deepcopy(left)
    second.update(run_id="empty-two", included=[], configuration_fingerprint=None)
    left["included"] = []
    report = compare_collection([left, second])
    item = report["summaries"]["unknown_configuration"]["metrics"]["code_jaccard"]
    assert item == {
        "defined_pairs": 0,
        "undefined_pairs": 1,
        "mean": None,
        "minimum": None,
        "maximum": None,
    }


def test_report_freezing_drift_and_duplicate_scope(tmp_path):
    project, a, b, _ = runs(tmp_path)
    root = project.parents[2]
    path = write_repeat_report(root, a.parent, [a, b], dry_run=True)
    assert not path.exists()
    assert write_repeat_report(root, a.parent, [a, b]) == path
    assert write_repeat_report(root, a.parent, [b, a]) == path
    with pytest.raises(ValueError, match="changed since"):
        write_repeat_report(root, a.parent, [a, b], expected_report_id="old")
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        write_repeat_report(root, a.parent, [a, b])
    with pytest.raises(ValueError, match="distinct"):
        build_repeat_report(root, [a, a])
    (b / "run_manifest.json").write_text("{}", encoding="utf-8")
    report = build_repeat_report(root, [a, b])
    assert report["usable_run_count"] == 1 and report["eligible_pairs"] == 0
    assert report["unavailable_runs"][0]["run_id"] == b.name


def test_prepared_experiment_report_keeps_not_started_runs_and_save_scope(tmp_path):
    from test_repeat_execution import setup
    from qualframe.dashboard import DashboardApp
    from qualframe.repeat_execution import prepare_repeats
    from qualframe.repeat_comparison import experiment_report_scope
    from qualframe.reviewed_analysis import snapshot_identity
    from qualframe.stability_ui import render_stability

    project, runner, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=3, stage_id=stage)
    identity = envelope["plan"]["experiment_id"]
    app = DashboardApp(runner)
    ids, context = experiment_report_scope(project, identity)
    report = build_repeat_report(
        runner.repo_root, [app.artifacts_dir / r for r in ids], experiment_context=context
    )
    assert report["possible_pairs"] == report["unavailable_pairs"] == 3
    assert report["usable_run_count"] == report["eligible_pairs"] == 0
    assert len(report["unavailable_runs"]) == 3
    page = render_stability(app, experiment_id=identity)
    assert "Failed and not-started runs" in page and "0 / 3" in page
    form = {
        "study_identity": [runner.project.project_id],
        "experiment": [identity],
        "report_id": [snapshot_identity(report)],
    }
    _, message = app.handle_action("/stability/save", form)
    assert "Saved frozen evaluation" in message
    assert "Download frozen evaluation JSON" in render_stability(app, experiment_id=identity)
