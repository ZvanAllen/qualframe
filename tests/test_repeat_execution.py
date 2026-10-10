import json

import pytest
from test_provider_setup import settings
from test_study_setup import make_test_repo

from qualframe.config import resolve_repo_path
from qualframe.cost_control import CostLimitExceeded
from qualframe.models import StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.provider_setup import save_provider_setup
from qualframe.providers.base import LLMUsage
from qualframe.providers.mock_provider import MockProvider
from qualframe.repeat_execution import (
    _acquire_execution_lock,
    execute_repeats,
    experiment_root,
    prepare_repeats,
    repeat_preflight,
)
from qualframe.study_setup import StudyWorkspace


def setup(tmp_path, *, live=False, **provider_options):
    repo = make_test_repo(tmp_path)
    workspace = StudyWorkspace(repo)
    created = workspace.create(
        StudyCreationRequest(
            title="Repeat QA", data_classification="synthetic", include_synthetic_fixtures=True
        )
    )
    project = repo / created.project_manifest_path
    if live:
        save_provider_setup(
            workspace,
            project,
            settings(**provider_options),
            actor="Tester",
            rationale="Synthetic test",
        )
    runner = ProjectRunner(project)
    stage = next(s.id for s in runner.pipeline.stages if s.prompt_ref)
    return project, runner, stage


def options(envelope, **updates):
    return dict(
        plan_id=envelope["plan_id"], actor="Tester", rationale="Synthetic stability QA", **updates
    )


def test_scoped_repeats_are_isolated_and_dry_run_makes_no_calls(tmp_path, monkeypatch):
    project, runner, stage = setup(tmp_path)
    source = next(
        i.path for i in runner.build_run_plan().discovered_inputs if i.kind == "transcript"
    )
    draft = prepare_repeats(
        project, repeat_count=3, stage_id=stage, source_paths=[source], dry_run=True
    )
    assert not (project.parent / "experiments").exists()
    assert len(draft["plan"]["run_plan"]["planned_stage_runs"]) == 1
    envelope = prepare_repeats(project, repeat_count=3, stage_id=stage, source_paths=[source])
    identifier = envelope["plan"]["experiment_id"]
    root = experiment_root(project, identifier)
    monkeypatch.setattr(
        "qualframe.pipeline.project_runner.build_provider",
        lambda *_: (_ for _ in ()).throw(AssertionError("Provider construction during dry run")),
    )
    execute_repeats(project, identifier, dry_run=True, **options(envelope))
    assert not (root / "attempts").exists()
    monkeypatch.setattr(
        "qualframe.pipeline.project_runner.build_provider", lambda *_: MockProvider()
    )
    execute_repeats(project, identifier, **options(envelope))
    assert json.loads((root / "status.json").read_text())["status"] == "completed"
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    ids = envelope["plan"]["run_ids"]
    assert len(set(ids)) == 3
    for run_id in ids:
        frozen = json.loads((artifacts / run_id / "run_plan.json").read_text())
        manifest = json.loads((artifacts / run_id / "run_manifest.json").read_text())
        assert [i["path"] for i in frozen["discovered_inputs"]] == [source]
        assert len(manifest["artifact_paths"]) == 1
        assert (artifacts / run_id / "evidence_review/index.json").exists()
    before = {p: p.read_bytes() for p in artifacts.rglob("*.json")}
    execute_repeats(project, identifier, resume=True, **options(envelope))
    assert before == {p: p.read_bytes() for p in before}
    assert repeat_preflight(project, identifier)["remaining_repeats"] == 0


@pytest.mark.parametrize("kind", ["source", "prompt", "config"])
def test_stale_inputs_block_before_provider_construction(tmp_path, monkeypatch, kind):
    project, runner, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)
    if kind == "source":
        path = runner.repo_root / envelope["plan"]["run_plan"]["discovered_inputs"][0]["path"]
    elif kind == "prompt":
        path = runner.repo_root / next(
            a.path for a in runner.configuration_lock.assets if a.kind == "prompt"
        )
    else:
        path = project
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# changed input\n")
    monkeypatch.setattr(
        "qualframe.pipeline.project_runner.build_provider",
        lambda *_: (_ for _ in ()).throw(AssertionError("Provider must not be constructed")),
    )
    with pytest.raises(ValueError, match="changed"):
        execute_repeats(project, envelope["plan"]["experiment_id"], **options(envelope))


def test_failure_stops_following_repeats_and_resume_skips_completed_artifacts(
    tmp_path, monkeypatch
):
    project, runner, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=3, stage_id=stage)
    calls = []

    class FailOnce(MockProvider):
        def complete(self, **kwargs):
            calls.append(kwargs["user_prompt"])
            if len(calls) == 4:
                raise TimeoutError("Synthetic failure")
            return super().complete(**kwargs)

    monkeypatch.setattr("qualframe.pipeline.project_runner.build_provider", lambda *_: FailOnce())
    identifier = envelope["plan"]["experiment_id"]
    with pytest.raises(RuntimeError, match="no automatic retry"):
        execute_repeats(project, identifier, **options(envelope))
    assert len(calls) == 4
    cost = runner._build_cost_controller(
        run_id=envelope["plan"]["run_ids"][1], artifact_root=experiment_root(project, identifier)
    )
    pending = cost.unresolved_requests()
    assert len(pending) == 1
    cost.reconcile_request(
        request_id=pending[0]["request_id"],
        usage=LLMUsage(),
        reviewer="Tester",
        rationale="Synthetic local failure used no API",
        evidence_reference="Mock failure fixture",
    )
    preview = repeat_preflight(project, identifier)
    assert preview["completed_run_ids"] == envelope["plan"]["run_ids"][:1]
    assert preview["remaining_repeats"] == 2
    with pytest.raises(ValueError, match="explicit resume"):
        execute_repeats(project, identifier, **options(envelope))
    execute_repeats(project, identifier, resume=True, **options(envelope))
    # Completed first repeat and first source of second repeat are not called again.
    assert len(calls) == 7
    assert repeat_preflight(project, identifier)["remaining_repeats"] == 0


def test_live_approval_key_budget_and_unresolved_usage_fail_closed(tmp_path, monkeypatch):
    project, runner, stage = setup(tmp_path, live=True)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)
    identifier = envelope["plan"]["experiment_id"]
    assert envelope["plan"]["budget_at_preparation"]["estimated_cost_usd"] > 0
    with pytest.raises(ValueError, match="Confirm governed"):
        execute_repeats(project, identifier, **options(envelope))
    monkeypatch.delenv(runner.project.provider.api_key_env, raising=False)
    with pytest.raises(ValueError, match="API key"):
        execute_repeats(project, identifier, **options(envelope, live_confirmed=True))
    monkeypatch.setenv(runner.project.provider.api_key_env, "synthetic-not-a-real-key")

    class Failing(MockProvider):
        def complete(self, **kwargs):
            raise TimeoutError("Synthetic provider failure")

    monkeypatch.setattr("qualframe.pipeline.project_runner.build_provider", lambda *_: Failing())
    with pytest.raises(RuntimeError, match="no automatic retry"):
        execute_repeats(project, identifier, **options(envelope, live_confirmed=True))
    with pytest.raises(ValueError, match="usage is unresolved"):
        execute_repeats(project, identifier, **options(envelope, live_confirmed=True, resume=True))
    root = experiment_root(project, identifier)
    assert len(list((root / "attempts").glob("*.json"))) == 1


def test_excessive_forecast_does_not_write_experiment(tmp_path):
    project, runner, stage = setup(tmp_path, live=True, absolute_limit_usd=0.001)
    with pytest.raises(CostLimitExceeded):
        prepare_repeats(project, repeat_count=10, stage_id=stage)
    assert not (project.parent / "experiments").exists()


def test_changed_completed_output_and_concurrent_workers_block(tmp_path):
    project, runner, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)
    identifier = envelope["plan"]["experiment_id"]
    root = experiment_root(project, identifier)
    lock = _acquire_execution_lock(root / "execution.lock")
    try:
        with pytest.raises(ValueError, match="active worker"):
            execute_repeats(project, identifier, **options(envelope))
    finally:
        lock.close()
    execute_repeats(project, identifier, **options(envelope))
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    path = artifacts / envelope["plan"]["run_ids"][0] / "run_manifest.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="preserved outputs changed"):
        execute_repeats(project, identifier, resume=True, **options(envelope))


@pytest.mark.parametrize("count", [0, 1, 11, True, 2.5])
def test_repeat_count_is_bounded(tmp_path, count):
    project, _, stage = setup(tmp_path)
    with pytest.raises(ValueError, match="between 2 and 10"):
        prepare_repeats(project, repeat_count=count, stage_id=stage)


def test_malformed_coding_stops_before_next_repeat(tmp_path, monkeypatch):
    from qualframe.providers.base import LLMResponse

    project, runner, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)

    class Malformed(MockProvider):
        def complete(self, **kwargs):
            return LLMResponse(
                text="No usable table.", provider="mock", model="mock", usage=LLMUsage()
            )

    monkeypatch.setattr("qualframe.pipeline.project_runner.build_provider", lambda *_: Malformed())
    with pytest.raises(ValueError, match="valid outputs|incomplete"):
        execute_repeats(project, envelope["plan"]["experiment_id"], **options(envelope))
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    assert not (artifacts / envelope["plan"]["run_ids"][1]).exists()


def test_incomplete_completion_receipt_cannot_skip_a_repeat(tmp_path):
    project, _, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)
    identifier = envelope["plan"]["experiment_id"]
    root = experiment_root(project, identifier)
    run_id = envelope["plan"]["run_ids"][0]
    (root / "completed").mkdir()
    (root / "completed" / f"{run_id}.json").write_text(
        json.dumps(dict(run_id="different", hashes={}))
    )
    with pytest.raises(ValueError, match="receipt belongs"):
        execute_repeats(project, identifier, **options(envelope))


def test_start_rechecks_fresh_versus_resume_under_worker_lock(tmp_path, monkeypatch):
    from qualframe import repeat_execution

    project, _, stage = setup(tmp_path)
    envelope = prepare_repeats(project, repeat_count=2, stage_id=stage)
    identifier = envelope["plan"]["experiment_id"]
    root = experiment_root(project, identifier)
    before = (root / "status.json").read_bytes()
    acquire = repeat_execution._acquire_execution_lock

    def intervening_worker(path):
        (root / "attempts").mkdir()
        return acquire(path)

    monkeypatch.setattr(repeat_execution, "_acquire_execution_lock", intervening_worker)
    with pytest.raises(ValueError, match="explicit resume"):
        execute_repeats(project, identifier, **options(envelope))
    assert (root / "status.json").read_bytes() == before
