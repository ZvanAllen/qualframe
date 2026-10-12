from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_provider_setup import settings
from test_study_setup import make_test_repo

from qualframe.models import StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.provider_setup import save_provider_setup
from qualframe.providers.base import LLMResponse, LLMUsage
from qualframe.study_setup import StudyWorkspace
from qualframe.unattended import (
    RunStopped,
    choose_model,
    confirm_request,
    execute,
    preapprove_spending,
    resolve_sample,
    run_status,
    start,
)

ROOT = Path(__file__).resolve().parents[1]


def _study(tmp_path, paid=True):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(StudyCreationRequest(
        title="Unattended", data_classification="synthetic", include_synthetic_fixtures=True))
    project = root / created.project_manifest_path
    if paid:
        save_provider_setup(workspace, project, settings(absolute_limit_usd=50), actor="Tester", rationale="Synthetic")
    return project


def _fake_provider(monkeypatch, behaviour):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs["user_prompt"][-60:])
        return behaviour(len(calls))

    monkeypatch.setattr("qualframe.pipeline.project_runner.build_provider",
                        lambda config: NS(name="openai", complete=complete))
    monkeypatch.setenv("QUALFRAME_UNATTENDED_OPENAI_KEY", "fake")
    return calls


def _answer(_):
    return LLMResponse(text='{"codings": []}', model="synthetic-model-id", provider="openai",
                       usage=LLMUsage(input_tokens=100, output_tokens=20))


def test_a_paid_run_from_the_command_line_finishes_and_is_ready_for_review(tmp_path, monkeypatch):
    project = _study(tmp_path)
    calls = _fake_provider(monkeypatch, _answer)
    lines = []
    summary = start(project, actor="Zack (run by an assistant)", rationale="Study A repeat", approve_up_to=40,
                    say=lines.append, every_seconds=3600)
    assert summary["status"] in {"completed", "awaiting_review"} and summary["review_ready"]
    assert summary["transcripts_done"] == summary["transcripts_planned"] == 2 and len(calls) == 2
    assert summary["run_cost_usd"] > 0 and summary["unresolved_requests"] == []
    approvals = [json.loads(line) for line in (project.parent / "logs/cost_approvals.jsonl").read_text().splitlines()]
    assert [a["threshold_usd"] for a in approvals] == [20.0, 40.0] and approvals[0]["reviewer"].startswith("Zack")
    run_root = project.parent / "artifacts" / summary["run_id"]
    approval = json.loads(next(run_root.glob("execution-approval-*.json")).read_text())
    assert approval["interface"] == "command line"
    assert any("Approved spending steps in advance: $20, $40" in line for line in lines)
    # Approving again records nothing new; approving past the study's limit is refused.
    assert preapprove_spending(project, up_to=40, actor="Z", rationale="r", run_id=summary["run_id"]) == []
    with pytest.raises(ValueError, match="spending limit"):
        preapprove_spending(project, up_to=60, actor="Z", rationale="r", run_id=summary["run_id"])


def test_a_sample_run_names_transcripts_by_id_or_group(tmp_path, monkeypatch):
    project = _study(tmp_path)
    _fake_provider(monkeypatch, _answer)
    runner = ProjectRunner(project)
    assert resolve_sample(runner, ["Synthetic Service Beta/SYN-02"]) == [
        p.relative_to(runner.repo_root).as_posix() for p in runner._transcript_files() if p.stem == "SYN-02"]
    with pytest.raises(ValueError, match="No single transcript matches: SYN-99"):
        resolve_sample(runner, ["SYN-99"])
    summary = start(project, actor="Z", rationale="Sample", sample=["SYN-01.txt"], say=lambda _: None, every_seconds=3600)
    assert summary["transcripts_planned"] == 1 and summary["sample"] and summary["sample"][0].endswith("SYN-01.txt")


def test_a_failed_request_stops_the_run_until_confirmed_then_it_resumes(tmp_path, monkeypatch):
    project = _study(tmp_path)

    def fail_second(n):
        if n == 2:
            raise RuntimeError("Connection error.")
        return _answer(n)

    _fake_provider(monkeypatch, fail_second)
    with pytest.raises(RunStopped) as stopped:
        start(project, actor="Z", rationale="Full run", approve_up_to=20, say=lambda _: None, every_seconds=3600)
    assert stopped.value.status == "failed_request_needs_confirmation"
    summary = stopped.value.summary
    [pending] = summary["unresolved_requests"]
    assert summary["status"] == "failed_request_needs_confirmation" and summary["transcripts_done"] == 1
    run_id = summary["run_id"]
    with pytest.raises(RunStopped, match="Confirm it first"):
        execute(project, run_id, actor="Z", rationale="Resume", say=lambda _: None, every_seconds=3600)
    charged = confirm_request(project, pending["request_id"], charged="maximum", actor="Z", note="power cut")
    assert charged == pytest.approx(pending["most_it_could_cost_usd"], rel=1e-3)
    calls = _fake_provider(monkeypatch, _answer)
    finished = execute(project, run_id, actor="Z", rationale="Resume", say=lambda _: None, every_seconds=3600)
    assert finished["transcripts_done"] == 2 and len(calls) == 1  # only the failed transcript was sent again
    with pytest.raises(ValueError, match="already been confirmed"):
        confirm_request(project, pending["request_id"], charged="no", actor="Z")


def test_choose_model_from_a_preset_and_keep_it_when_unchanged(tmp_path):
    project = _study(tmp_path)
    assert choose_model(project, "anthropic-haiku-5-5", actor="Z", rationale="Low-cost model", app_root=ROOT,
                        spending_limit=50)
    provider = ProjectRunner(project).project.provider
    assert (provider.name, provider.model, provider.max_tokens) == ("anthropic", "claude-haiku-5-5", 64000)
    assert not choose_model(project, "anthropic-haiku-5-5", actor="Z", rationale="Again", app_root=ROOT)
    assert choose_model(project, "anthropic-haiku-5-5", actor="Z", rationale="More room", app_root=ROOT, spending_limit=60)
    with pytest.raises(ValueError, match="Unknown model preset"):
        choose_model(project, "not-a-preset", actor="Z", rationale="x", app_root=ROOT)


def test_command_line_status_and_codes(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from qualframe.cli import app
    project = _study(tmp_path)
    _fake_provider(monkeypatch, _answer)
    result = CliRunner().invoke(app, ["code", str(project), "--researcher", "Z", "--reason", "Test",
                                      "--approve-up-to", "20", "--progress-every", "3600"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output[result.output.index("{"):])
    status = CliRunner().invoke(app, ["status", str(project)])
    assert status.exit_code == 0 and json.loads(status.output)["run_id"] == summary["run_id"]
    assert run_status(project, summary["run_id"])["review_ready"]
