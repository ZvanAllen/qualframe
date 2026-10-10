import os
from datetime import date

import pytest
from test_study_setup import make_test_repo

from qualframe.config import load_project_manifest
from qualframe.models import StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.provider_setup import ProviderSetup, save_provider_setup
from qualframe.study_setup import StudyWorkspace


def settings(**updates):
    return ProviderSetup.model_validate(
        {
            "provider": "openai",
            "model": "synthetic-model-id",
            "max_tokens": 2000,
            "temperature": 0,
            "absolute_limit_usd": 5,
            "input_rate": 1,
            "output_rate": 2,
            "pricing_date": date.today(),
            "pricing_source": "https://platform.openai.com/docs/pricing",
            "governance_confirmed": True,
            **updates,
        }
    )


def test_provider_settings_are_versioned_and_secrets_stay_outside_files(tmp_path, monkeypatch):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Provider setup study", data_classification="synthetic")
    )
    project = root / created.project_manifest_path
    before = project.read_bytes()
    env = "QUALFRAME_PROVIDER_SETUP_STUDY_OPENAI_KEY"
    monkeypatch.setenv(env, "")
    secret = "synthetic-session-secret"
    folder = save_provider_setup(
        workspace, project, settings(), actor="Reviewer", rationale="Prepare test", api_key=secret
    )
    assert (folder / "project-before.yaml").read_bytes() == before
    assert os.environ[env] == secret
    for path in project.parent.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()
    updated = load_project_manifest(project)
    assert updated.provider.model == "synthetic-model-id"
    assert updated.provider.api_key_env == env
    assert updated.cost_policy.endswith("cost.yaml")
    assert updated.pricing_snapshot.endswith("pricing.yaml")
    assert ProjectRunner(project).build_run_plan().configuration_fingerprint


@pytest.mark.parametrize(
    "update",
    [
        {"governance_confirmed": False},
        {"absolute_limit_usd": float("nan")},
        {"input_rate": 0},
        {"pricing_source": "https://unrelated.example/pricing"},
        {"model": "model with spaces"},
        {"provider": "unknown"},
    ],
)
def test_invalid_provider_settings_are_rejected(update):
    with pytest.raises(ValueError):
        settings(**update)


def test_changed_provider_invalidates_previous_run_plan(tmp_path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Plan identity study", data_classification="synthetic")
    )
    project = root / created.project_manifest_path
    runner = ProjectRunner(project)
    plan = runner.build_run_plan()
    save_provider_setup(workspace, project, settings(), actor="Reviewer", rationale="New provider")
    with pytest.raises(ValueError, match="changed after preflight"):
        ProjectRunner(project).execute_run_plan(plan, "must-not-run")
    assert not (project.parent / "artifacts/must-not-run").exists()
