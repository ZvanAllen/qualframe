import sys
from types import SimpleNamespace as NS


import pytest
from test_cost_control import controller
from test_provider_setup import settings
from test_study_setup import make_test_repo

from qualframe.cost_control import UnresolvedRequest
from qualframe.dashboard import DashboardApp
from qualframe.models import ProviderConfig, StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.provider_setup import save_provider_setup
from qualframe.providers.anthropic_provider import AnthropicProvider
from qualframe.providers.base import LLMResponse, LLMUsage
from qualframe.providers.openai_provider import OpenAIProvider
from qualframe.study_setup import StudyWorkspace


class _ResponseStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        yield NS(type=f"response.{self.response.status}", response=self.response)

    def get_final_response(self):
        assert self.response.status == "completed"
        return self.response


def test_unresolved_request_survives_restart_and_blocks_retries(tmp_path):
    cost = controller(tmp_path, max_output_tokens=10)
    request_id, estimate = cost.preflight(
        stage_id="coding", input_label="one", system_prompt="s", user_prompt="u"
    )
    fresh = controller(tmp_path, max_output_tokens=10)
    with pytest.raises(UnresolvedRequest):
        fresh.preflight(stage_id="coding", input_label="one", system_prompt="s", user_prompt="u")
    cost.record_response(
        request_id=request_id,
        estimated_cost_usd=estimate,
        stage_id="coding",
        input_label="one",
        system_prompt="s",
        user_prompt="u",
        response=LLMResponse(text="ok", usage=LLMUsage(output_tokens=3)),
    )
    assert fresh.unresolved_requests() == []
    assert fresh.project_cost_usd() == 3


def test_missing_usage_does_not_clear_reservation(tmp_path):
    cost = controller(tmp_path, max_output_tokens=10)
    request_id, estimate = cost.preflight(
        stage_id="coding", input_label="one", system_prompt="s", user_prompt="u"
    )
    cost.record_response(
        request_id=request_id,
        estimated_cost_usd=estimate,
        stage_id="coding",
        input_label="one",
        system_prompt="s",
        user_prompt="u",
        response=LLMResponse(text="ok"),
    )
    assert len(cost.unresolved_requests()) == 1


@pytest.mark.parametrize("provider_type", [OpenAIProvider, AnthropicProvider])
def test_provider_failure_is_one_attempt_with_sdk_retries_disabled(monkeypatch, provider_type):
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("synthetic timeout")

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return NS(chat=NS(completions=NS(create=fail)), messages=NS(stream=fail), close=lambda: None)

    monkeypatch.setenv("SYNTHETIC_KEY", "fake-key")
    monkeypatch.setitem(sys.modules, "openai", NS(OpenAI=client))
    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=client))
    with pytest.raises(TimeoutError):
        provider_type(model="synthetic", api_key_env="SYNTHETIC_KEY").complete(
            system_prompt="s", user_prompt="u"
        )
    assert len(calls) == 1


def test_responses_effort_usage_and_incomplete_status(monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return NS(
            output_text="partial",
            model="synthetic",
            id="response-1",
            status="incomplete",
            incomplete_details=NS(reason="max_output_tokens"),
            usage=NS(
                input_tokens=20,
                input_tokens_details=NS(cached_tokens=5),
                output_tokens=100,
                output_tokens_details=NS(reasoning_tokens=90),
            ),
        )

    monkeypatch.setenv("SYNTHETIC_KEY", "fake-key")
    monkeypatch.setitem(
        sys.modules, "openai", NS(OpenAI=lambda **kwargs: NS(responses=NS(stream=lambda **opts: _ResponseStream(create(**opts))), close=lambda: None))
    )
    result = OpenAIProvider(
        model="synthetic",
        api_key_env="SYNTHETIC_KEY",
        temperature=None,
        api_mode="responses",
        reasoning_effort="low",
        max_tokens=100,
    ).complete(system_prompt="s", user_prompt="u")
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["store"] is False
    assert captured["max_output_tokens"] == 100
    assert "temperature" not in captured
    assert result.status == "incomplete"
    assert result.usage == LLMUsage(
        input_tokens=15, cached_input_tokens=5, output_tokens=10, reasoning_tokens=90
    )


def test_incomplete_output_records_usage_before_rejection(tmp_path):
    cost = controller(tmp_path, max_output_tokens=10)
    provider = NS(
        complete=lambda **kwargs: LLMResponse(
            text="partial", status="incomplete", usage=LLMUsage(output_tokens=3)
        )
    )
    runner = object.__new__(ProjectRunner)
    with pytest.raises(RuntimeError, match="incomplete"):
        runner._complete(
            provider=provider,
            cost_controller=cost,
            stage_id="coding",
            input_label="one",
            user_prompt="s",
        )
    assert cost.project_cost_usd() == 3
    assert cost.unresolved_requests() == []
    assert len(list((cost.artifact_root / "requests").glob("*.json"))) == 1


@pytest.mark.parametrize(
    "config",
    [
        dict(name="anthropic", reasoning_effort="low"),
        dict(name="openai", api_mode="responses", reasoning_effort="low", temperature=0),
        dict(name="openai", anthropic_effort="high"),
    ],
)
def test_incompatible_effort_rejected(config):
    with pytest.raises(ValueError):
        ProviderConfig(**config)


def test_live_browser_requires_current_approval_and_key(tmp_path, monkeypatch):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(
            title="Paid synthetic", data_classification="synthetic", include_synthetic_fixtures=True
        )
    )
    project = root / created.project_manifest_path
    save_provider_setup(workspace, project, settings(), actor="Tester", rationale="Synthetic QA")
    runner = ProjectRunner(project)
    app = DashboardApp(runner)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, "paid-test")
    with pytest.raises(PermissionError):
        app.start_local_execution("paid-test")
    approval = dict(
        actor="Tester", rationale="Synthetic QA", live_confirmed="yes", fingerprint="stale"
    )
    with pytest.raises(ValueError, match="Configuration changed"):
        app.start_local_execution("paid-test", approval=approval)
    approval["fingerprint"] = plan.configuration_fingerprint
    monkeypatch.delenv(runner.project.provider.api_key_env, raising=False)
    with pytest.raises(ValueError, match="API key"):
        app.start_local_execution("paid-test", approval=approval)
    monkeypatch.setenv(runner.project.provider.api_key_env, "fake-key")
    dispatched = []
    monkeypatch.setattr(
        "qualframe.dashboard.threading.Thread",
        lambda **kwargs: NS(start=lambda: dispatched.append(kwargs)),
    )
    app.start_local_execution("paid-test", approval=approval)
    assert len(dispatched) == 1
    assert list((app.artifacts_dir / "paid-test").glob("execution-approval-*.json"))
    with pytest.raises(ValueError, match="already in progress"):
        app.start_local_execution("paid-test", approval=approval)


def test_reconciliation_uses_original_prices_and_replaces_estimate(tmp_path):
    cost = controller(tmp_path, max_output_tokens=10)
    request_id, estimate = cost.preflight(
        stage_id="coding", input_label="one", system_prompt="s", user_prompt="u"
    )
    cost.record_response(
        request_id=request_id,
        estimated_cost_usd=estimate,
        stage_id="coding",
        input_label="one",
        system_prompt="s",
        user_prompt="u",
        response=LLMResponse(text="estimated"),
    )
    cost.pricing.output_per_million_usd = 0
    record = cost.reconcile_request(
        request_id=request_id,
        usage=LLMUsage(output_tokens=4),
        reviewer="Tester",
        rationale="Provider confirmed billable tokens",
        evidence_reference="Synthetic provider statement 1",
    )
    assert record.calculated_cost_usd == 4
    assert cost.project_cost_usd() == 4
    assert not cost.unresolved_requests()
    assert (cost.ledger_path.parent / "usage_reconciliations.jsonl").exists()
    with pytest.raises(ValueError):
        cost.reconcile_request(
            request_id=request_id,
            usage=LLMUsage(),
            reviewer="Tester",
            rationale="Duplicate",
            evidence_reference="Synthetic statement 1",
        )


def test_anthropic_effort_forwarded_without_temperature(monkeypatch):
    captured = {}

    class Stream:
        text_stream = ["synthetic response"]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_final_message(self):
            return NS(
                model="synthetic",
                id="message-1",
                stop_reason="end_turn",
                usage=NS(input_tokens=2, output_tokens=3),
            )

    def stream(**kwargs):
        captured.update(kwargs)
        return Stream()

    monkeypatch.setenv("SYNTHETIC_KEY", "fake-key")
    monkeypatch.setitem(
        sys.modules, "anthropic", NS(Anthropic=lambda **kwargs: NS(messages=NS(stream=stream)))
    )
    result = AnthropicProvider(
        model="synthetic", api_key_env="SYNTHETIC_KEY", temperature=None, effort="low"
    ).complete(system_prompt="s", user_prompt="u", response_schema={"type":"object"})
    assert captured["extra_body"]["output_config"] == {"effort": "low", "format":{"type":"json_schema","schema":{"type":"object"}}}
    assert "temperature" not in captured
    assert result.status == "completed"


def test_provider_form_preserves_saved_effort_and_ceiling():
    from qualframe.provider_setup_ui import provider_setup_form

    rendered = provider_setup_form(
        "openai",
        "synthetic",
        {"api_mode": "responses", "reasoning_effort": "low", "absolute_limit_usd": 1},
    )
    assert '<option value="responses" selected>' in rendered
    assert "<option selected>low</option>" in rendered
    assert 'value="1"' in rendered


def test_hyphenated_source_filter_runs_exact_source_and_rejects_no_match(tmp_path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(StudyCreationRequest(title="Filter smoke", data_classification="synthetic", include_synthetic_fixtures=True))
    runner = ProjectRunner(root / created.project_manifest_path)
    plan = runner.build_run_plan()
    manifest_path = runner.execute_run_plan(plan, "one-source", transcript_filter="SYN-01")
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["artifact_paths"]) == 1
    assert "SYN-01" in manifest["artifact_paths"][0]
    with pytest.raises(ValueError, match="matched no sources"):
        runner.execute_run_plan(plan, "missing-source", transcript_filter="NOT-PRESENT")
    assert not (manifest_path.parent.parent / "missing-source").exists()


@pytest.mark.parametrize('api_mode',['responses','chat_completions'])
def test_openai_native_schema_is_forwarded(monkeypatch,api_mode):
    captured={}
    schema={'type':'object','properties':{},'required':[],'additionalProperties':False}
    def create(**kwargs):
        captured.update(kwargs)
        if kwargs.get('stream'):
            return iter([NS(id='r',model='synthetic',usage=None,choices=[NS(delta=NS(content='{}'),finish_reason='stop')])])
        return NS(output_text='{}',model='synthetic',id='r',status='completed',incomplete_details=None,usage=None,choices=[NS(message=NS(content='{}'),finish_reason='stop')])
    monkeypatch.setenv('SYNTHETIC_KEY','fake-key')
    monkeypatch.setitem(sys.modules,'openai',NS(OpenAI=lambda **kwargs:NS(responses=NS(stream=lambda **opts: _ResponseStream(create(**opts))),chat=NS(completions=NS(create=create)),close=lambda:None)))
    OpenAIProvider(model='synthetic',api_key_env='SYNTHETIC_KEY',api_mode=api_mode).complete(system_prompt='s',user_prompt='u',response_schema=schema)
    specification=captured['text']['format'] if api_mode=='responses' else captured['response_format']['json_schema']
    assert specification['schema']==schema and specification['strict'] is True
