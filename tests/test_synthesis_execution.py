import json

import pytest
from test_reviewed_analysis import decide
from test_synthesis_plan import reviewed

from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.synthesis_execution import current_plan, execute_synthesis, synthesis_preflight
from qualframe.synthesis_plan import write_synthesis_plan
from qualframe.synthesis_review import (
    export_synthesis,
    read_job,
    review_statement,
)


def ready(tmp_path):
    project, run_id, root, review, records, path = reviewed(tmp_path)
    plan = write_synthesis_plan(project.parents[2], root, review, path, "selected_cohort")
    identity = plan.stem[15:]
    runner = ProjectRunner(project)
    preview = synthesis_preflight(runner, root, identity)
    options = dict(
        fingerprint=preview["configuration_fingerprint"], actor="QA", rationale="Synthetic test"
    )
    return project, root, review, records, identity, options


def test_synthesis_dry_run_review_edit_export_and_stale_inputs(tmp_path):
    project, root, review, source_records, identity, options = ready(tmp_path)
    path = execute_synthesis(project, root, identity, dry_run=True, **options)
    assert not path.exists()
    path = execute_synthesis(project, root, identity, **options)
    status, plan, records = read_job(path)
    assert status["status"] == "awaiting_review" and len(records) == 4
    assert status["cost_usd"] == 0
    with pytest.raises(ValueError, match="Resolve every"):
        export_synthesis(path, inputs_current=True)
    for record in records:
        review_statement(path, record["statement_id"], decision="accept", reviewer="QA")
    first = records[0]
    review_statement(
        path,
        first["statement_id"],
        decision="edit",
        reviewer="QA",
        edited_text="A reviewed descriptive statement.",
        evidence_ids=first["evidence_ids"],
    )
    review_statement(path, first["statement_id"], decision="accept", reviewer="QA")
    result = export_synthesis(path, inputs_current=True)
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["reviewed_statements"][0]["text"] == "A reviewed descriptive statement."
    assert len(payload["review_history"]) == len(records) + 2
    assert export_synthesis(path, inputs_current=True) == result
    with pytest.raises(ValueError, match="outside its reviewed"):
        review_statement(
            path,
            first["statement_id"],
            decision="edit",
            reviewer="QA",
            edited_text="Invalid citation",
            evidence_ids=["invented"],
        )
    decide(project, root, review, source_records[0], "reject")
    with pytest.raises(ValueError, match="stale"):
        current_plan(ProjectRunner(project), root, identity)
    with pytest.raises(ValueError, match="inputs changed"):
        export_synthesis(path, inputs_current=False)
    assert result.exists()


def test_synthesis_blocks_changed_configuration_and_tampered_plan(tmp_path):
    project, root, _, _, identity, options = ready(tmp_path)
    with pytest.raises(ValueError, match="Configuration changed"):
        execute_synthesis(project, root, identity, **dict(options, fingerprint="wrong"))
    path = root / "analysis" / f"synthesis-plan-{identity}.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["calls"][0]["input"]["evidence"][0]["exact_text"] = "Changed"
    changed = snapshot_identity(plan)
    (root / "analysis" / f"synthesis-plan-{changed}.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="differs from its reviewed"):
        current_plan(ProjectRunner(project), root, changed)


def test_synthesis_preserves_failed_response_and_blocks_review(tmp_path, monkeypatch):
    project, root, _, _, identity, options = ready(tmp_path)
    from qualframe.providers.base import LLMResponse, LLMUsage
    from qualframe.synthesis_execution import SyntheticSynthesisProvider

    monkeypatch.setattr(
        SyntheticSynthesisProvider,
        "complete",
        lambda *a, **k: LLMResponse(
            text='{"summaries":[{"code_id":"invented","statements":[]}]}', usage=LLMUsage()
        ),
    )
    with pytest.raises(ValueError, match="absent from the reviewed"):
        execute_synthesis(project, root, identity, **options)
    target = next((root / "analysis" / "synthesis").iterdir())
    status, plan, records = read_job(target)
    assert status["status"] == "failed" and records == []
    assert list(target.glob("*-response.json"))
    with pytest.raises(ValueError, match="Resolve every"):
        export_synthesis(target, inputs_current=True)


def test_synthesis_live_approval_key_and_ceiling_gates(tmp_path, monkeypatch):
    from test_provider_setup import settings

    from qualframe.cost_control import CostLimitExceeded
    from qualframe.provider_setup import save_provider_setup
    from qualframe.study_setup import StudyWorkspace

    project, root, _, _, identity, options = ready(tmp_path)
    workspace = StudyWorkspace(project.parents[2])
    save_provider_setup(workspace, project, settings(), actor="QA", rationale="Synthetic paid test")
    runner = ProjectRunner(project)
    monkeypatch.delenv(runner.project.provider.api_key_env, raising=False)
    monkeypatch.setattr(
        "qualframe.synthesis_execution.build_provider",
        lambda *a, **k: pytest.fail("Gated request reached a provider"),
    )
    options["fingerprint"] = runner.configuration_lock.fingerprint_sha256
    with pytest.raises(ValueError, match="Confirm provider transfer"):
        execute_synthesis(project, root, identity, **options)
    with pytest.raises(ValueError, match="configured API key"):
        execute_synthesis(project, root, identity, live_confirmed=True, **options)
    save_provider_setup(
        workspace,
        project,
        settings(absolute_limit_usd=0.000001),
        actor="QA",
        rationale="Test ceiling",
    )
    options["fingerprint"] = ProjectRunner(project).configuration_lock.fingerprint_sha256
    with pytest.raises(CostLimitExceeded, match="remaining study ceiling"):
        execute_synthesis(project, root, identity, live_confirmed=True, **options)
    assert not (root / "analysis" / "synthesis").exists()
