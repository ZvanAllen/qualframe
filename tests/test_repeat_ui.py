import json
from types import SimpleNamespace

import pytest
from test_repeat_execution import setup

from qualframe.dashboard import DashboardApp
from qualframe.repeat_ui import prepare_repeat_form, render_repeats, start_repeat_job


def test_browser_prepare_start_and_one_active_job(tmp_path, monkeypatch):
    project, runner, stage = setup(tmp_path)
    app = DashboardApp(runner)
    sources = [i.path for i in runner.build_run_plan().discovered_inputs if i.kind == "transcript"]
    form = dict(
        study_identity=[runner.project.project_id],
        source=sources,
        stage_id=[stage],
        repeat_count=["2"],
    )
    assert "Prepare costed repeat plan" in render_repeats(app)
    identifier = prepare_repeat_form(app, form)
    prepared = render_repeats(app, identifier)
    assert "Start coding repeats" in prepared
    assert f'/stability?experiment={identifier}' in prepared
    assert "View evaluation for this experiment" in prepared
    envelope = json.loads((project.parent / "experiments" / identifier / "plan.json").read_text())
    start = dict(
        study_identity=[runner.project.project_id],
        experiment=[identifier],
        plan_id=[envelope["plan_id"]],
        reviewer=["Tester"],
        rationale=["Synthetic UI QA"],
    )
    dispatched = []
    monkeypatch.setattr(
        "qualframe.repeat_ui.threading",
        SimpleNamespace(Thread=lambda **kwargs: SimpleNamespace(start=lambda: dispatched.append(kwargs))),
    )
    assert start_repeat_job(app, start) == identifier
    assert len(dispatched) == 1
    with pytest.raises(ValueError, match="current study job"):
        start_repeat_job(app, start)
    dispatched[0]["target"]()
    assert app._job_snapshot(identifier).status == "completed"
    rendered = render_repeats(app, identifier)
    assert "View evaluation for this experiment" in rendered
    assert f'/stability?experiment={identifier}' in rendered
    assert '/stability?run=' not in rendered
    assert "Start coding repeats" not in rendered
    assert "2 of 2 repeats complete" in rendered
    assert "Review coding proposals" in rendered


def test_browser_preparation_rejects_stale_study(tmp_path):
    _, runner, stage = setup(tmp_path)
    app = DashboardApp(runner)
    with pytest.raises(ValueError, match="another study"):
        prepare_repeat_form(
            app, dict(study_identity=["other"], repeat_count=["2"], stage_id=[stage])
        )
