"""Offline recorder regressions; every provider is synthetic and network is refused."""
from __future__ import annotations

import importlib.util
import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from qualframe.cost_control import CostController, CostLimitExceeded, UnresolvedRequest
from qualframe.providers.base import LLMResponse, LLMUsage

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("record_demo_under_test", ROOT / "scripts/record_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = tmp_path / "app"
    for relative in ("config", "prompts", "demo/datasets/ai-scribe"):
        shutil.copytree(ROOT / relative, app / relative)
    monkeypatch.setattr(module, "REPO_ROOT", app)
    monkeypatch.setattr(module, "DATASET", app / "demo/datasets/ai-scribe")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-recorder-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-recorder-key")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Network prohibited in recorder tests"))
    return module


def invoke(recorder, tmp_path, name="cell-one", *, resume=False, preset="openai-gpt-6-1-sol",
           style="find_passages", division="full_codebook", limit=3, max_tokens=16000):
    args = ["--name", name, "--label", name, "--preset", preset, "--state-dir", str(tmp_path / "state"),
            "--coding-style", style, "--codebook-division", division,
            "--limit-usd", str(limit), "--max-tokens", str(max_tokens), "--yes"]
    if resume:
        args.append("--resume")
    return recorder.main(args)


def fake(recorder, monkeypatch, behavior=None):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        if behavior:
            return behavior(len(calls), kwargs)
        return LLMResponse(text='{"codings": []}', model="synthetic-returned-model", provider="openai",
                           usage=LLMUsage(input_tokens=100, cached_input_tokens=20, cache_write_tokens=10,
                                          output_tokens=30, reasoning_tokens=40))

    monkeypatch.setattr(recorder.runner_module, "build_provider",
                        lambda config: SimpleNamespace(name=config.name, complete=complete))
    return calls


def state(tmp_path):
    return json.loads((tmp_path / "state/recording_state.json").read_text(encoding="utf-8"))


def run_root(tmp_path, name="cell-one"):
    saved = state(tmp_path)
    project = tmp_path / "state" / saved["project_manifest_path"]
    return project.parent / "artifacts" / saved["recordings"][name]["run_id"]


def metadata(recorder, name="cell-one"):
    return json.loads((recorder.REPO_ROOT / "demo/recordings" / name / "recording.json").read_text(encoding="utf-8"))


def test_complete_recording_exports_ledger_usage_prompt_and_private_free_metadata(recorder, tmp_path, monkeypatch, capsys):
    calls = fake(recorder, monkeypatch)
    assert invoke(recorder, tmp_path) == 0
    info = metadata(recorder)
    assert len(calls) == info["requests"] == info["expected_requests"] == 6
    assert info["complete"] and info["status"] == "completed"
    assert info["provider_settings"]["max_tokens"] == 16000
    assert info["prompt_sha256"] == recorder.sha256_for_text((recorder.REPO_ROOT / info["prompt_file"]).read_text(encoding="utf-8"))
    assert info["usage_breakdown"] == {"input_tokens": 600, "cached_input_tokens": 120, "cache_write_tokens": 60,
                                       "output_tokens": 180, "reasoning_tokens": 240}
    assert info["reported_usage"] == {"input_tokens": 780, "output_tokens": 420}
    assert info["actual_cost_usd"] == pytest.approx((780 * 2 + 420 * 10) / 1e6)
    assert info["returned_models"] == ["synthetic-returned-model"]
    text = json.dumps(info)
    assert "synthetic-recorder-key" not in text and str(tmp_path) not in text and "api_key_env" not in text
    assert "6/6 responses saved" in capsys.readouterr().out
    project = tmp_path / "state" / state(tmp_path)["project_manifest_path"]
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    policy = yaml.safe_load((tmp_path / "state" / data["cost_policy"]).read_text(encoding="utf-8"))
    assert policy["notification_adapter"] == "none" and policy["notification_recipient_env"] is None
    assert invoke(recorder, tmp_path, resume=True) == 0
    assert len(calls) == 6


def test_interrupt_after_saved_answer_resumes_without_resending_completed_requests(recorder, tmp_path, monkeypatch):
    calls = fake(recorder, monkeypatch)
    original = CostController.record_response
    settled = []

    def interrupt(self, **kwargs):
        record = original(self, **kwargs)
        settled.append(record)
        if len(settled) == 2:
            raise KeyboardInterrupt("synthetic interruption after durable response and usage")
        return record

    monkeypatch.setattr(CostController, "record_response", interrupt)
    with pytest.raises(KeyboardInterrupt):
        invoke(recorder, tmp_path)
    assert len(calls) == 2 and len(list((run_root(tmp_path) / "requests").glob("*.json"))) == 2
    assert not (recorder.REPO_ROOT / "demo/recordings/cell-one").exists()
    monkeypatch.setattr(CostController, "record_response", original)
    assert invoke(recorder, tmp_path, resume=True) == 0
    assert len(calls) == 6 and metadata(recorder)["requests"] == 6
    assert len({c["user_prompt"] for c in calls}) == 6


def test_unresolved_transport_attempt_blocks_resume_and_other_cells(recorder, tmp_path, monkeypatch):
    def fail_second(n, kwargs):
        if n == 2:
            raise RuntimeError("Synthetic transport error")
        return LLMResponse(text='{"codings": []}', usage=LLMUsage(input_tokens=100, output_tokens=20))

    calls = fake(recorder, monkeypatch, fail_second)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        invoke(recorder, tmp_path)
    with pytest.raises(UnresolvedRequest, match="unresolved usage"):
        invoke(recorder, tmp_path, resume=True)
    with pytest.raises(ValueError, match="active recording"):
        invoke(recorder, tmp_path, name="cell-two")
    assert len(calls) == 2


@pytest.mark.parametrize("response", [
    LLMResponse(text='{"codings": []}', status="incomplete", usage=LLMUsage(input_tokens=100, output_tokens=20)),
    LLMResponse(text="", usage=LLMUsage(input_tokens=100, output_tokens=20)),
    LLMResponse(text='{"codings": []}', usage=None),
])
def test_incomplete_empty_or_unpriced_response_never_resends(recorder, tmp_path, monkeypatch, response):
    calls = fake(recorder, monkeypatch, lambda n, kwargs: response)
    with pytest.raises((RuntimeError, ValueError, UnresolvedRequest)):
        invoke(recorder, tmp_path)
    assert len(calls) == 1
    with pytest.raises((ValueError, UnresolvedRequest)):
        invoke(recorder, tmp_path, resume=True)
    assert len(calls) == 1


def test_missing_saved_paid_response_is_not_resent(recorder, tmp_path, monkeypatch):
    calls = fake(recorder, monkeypatch)
    original = CostController.record_response

    def interrupt(self, **kwargs):
        original(self, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(CostController, "record_response", interrupt)
    with pytest.raises(KeyboardInterrupt):
        invoke(recorder, tmp_path)
    next((run_root(tmp_path) / "requests").glob("*.json")).unlink()
    monkeypatch.setattr(CostController, "record_response", original)
    with pytest.raises(ValueError, match="ledger|saved response"):
        invoke(recorder, tmp_path, resume=True)
    assert len(calls) == 1


def test_shared_budget_counts_another_model_and_cell(recorder, tmp_path, monkeypatch):
    calls = fake(recorder, monkeypatch, lambda n, kwargs: LLMResponse(
        text='{"codings": []}', usage=LLMUsage(input_tokens=12000, output_tokens=128)))
    assert invoke(recorder, tmp_path, limit=0.175, max_tokens=128) == 0
    assert len(calls) == 6
    with pytest.raises(CostLimitExceeded):
        invoke(recorder, tmp_path, name="cell-two", preset="anthropic-sonnet-5-5", limit=0.175, max_tokens=128)
    assert len(calls) == 6
    assert state(tmp_path)["active_recording"] == "cell-two"
    assert metadata(recorder)["actual_cost_usd"] == pytest.approx(0.15168)
    with pytest.raises(ValueError, match="limits cannot change"):
        invoke(recorder, tmp_path, name="cell-two", resume=True, preset="anthropic-sonnet-5-5", limit=3, max_tokens=128)


def test_decide_grouped_records_actual_v4_and_24_distinct_responses(recorder, tmp_path, monkeypatch):
    def answer(n, kwargs):
        ids = kwargs["response_schema"]["properties"]["decisions"]["items"]["properties"]["code_id"]["enum"]
        return LLMResponse(text=json.dumps({"decisions": [{"code_id": code, "present": False,
                            "quote": "", "rationale": "Synthetic absence"} for code in ids]}),
                           usage=LLMUsage(input_tokens=100, output_tokens=100))

    calls = fake(recorder, monkeypatch, answer)
    invoke(recorder, tmp_path, style="decide_each_code", division="top_level_categories")
    info = metadata(recorder)
    assert len(calls) == info["expected_requests"] == 24
    assert info["prompt_file"] == "prompts/directed/v4/decide_each_code.md"
    assert info["partition_strategy"] == "per_top_level_category"
    assert len(info["response_sha256"]) == 24
    assert len({p.stem.rsplit("__", 1)[-1] for p in (recorder.REPO_ROOT / "demo/recordings/cell-one/responses").glob("*.txt")}) == 4


def test_state_lock_and_changed_resume_options_block_before_provider(recorder, tmp_path, monkeypatch):
    calls = fake(recorder, monkeypatch)
    root = tmp_path / "state"
    root.mkdir()
    lock = root / ".recording.lock"
    lock.write_text("synthetic other recorder", encoding="utf-8")
    with pytest.raises(UnresolvedRequest):
        invoke(recorder, tmp_path)
    assert not calls
    lock.unlink()
    original = CostController.record_response

    def interrupt(self, **kwargs):
        original(self, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(CostController, "record_response", interrupt)
    with pytest.raises(KeyboardInterrupt):
        invoke(recorder, tmp_path)
    with pytest.raises(ValueError, match="original provider"):
        invoke(recorder, tmp_path, resume=True, style="decide_each_code")
    assert len(calls) == 1
