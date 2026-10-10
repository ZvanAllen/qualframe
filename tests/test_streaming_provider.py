import json
import sys
from types import SimpleNamespace as NS

import pytest
from test_cost_control import controller

from qualframe.cost_control import UnresolvedRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.base import LLMResponse, LLMUsage
from qualframe.providers.openai_provider import OpenAIProvider


def response(status="completed", text=" final text ", *, usage=True):
    return NS(
        id="response-synthetic",
        model="gpt-5.2-2025-12-11",
        output_text=text,
        status=status,
        incomplete_details=NS(reason="max_output_tokens") if status == "incomplete" else None,
        error=NS(code="server_error") if status == "failed" else None,
        service_tier="priority",
        usage=NS(
            input_tokens=20,
            input_tokens_details=NS(cached_tokens=5),
            output_tokens=100,
            output_tokens_details=NS(reasoning_tokens=90),
        )
        if usage
        else None,
    )


def install_client(monkeypatch, events, final=None, failure=None):
    state = dict(calls=[], client_closed=False, stream_closed=False, consumed=0, final_calls=0)

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            state["stream_closed"] = True

        def __iter__(self):
            for event in events:
                state["consumed"] += 1
                yield event
            if failure:
                raise failure

        def get_final_response(self):
            state["final_calls"] += 1
            if final is None:
                raise RuntimeError("Did not receive response.completed")
            return final

    def stream(**kwargs):
        state["calls"].append(kwargs)
        return Stream()

    def client(**kwargs):
        state["client_options"] = kwargs
        return NS(
            responses=NS(stream=stream),
            close=lambda: state.update(client_closed=True),
        )

    monkeypatch.setenv("SYNTHETIC_KEY", "fake-key")
    monkeypatch.setitem(sys.modules, "openai", NS(OpenAI=client))
    return state


def provider():
    return OpenAIProvider(
        model="gpt-5.2-2025-12-11",
        api_key_env="SYNTHETIC_KEY",
        api_mode="responses",
        reasoning_effort="medium",
        max_tokens=24000,
        temperature=None,
    )


def test_stream_consumes_events_and_preserves_request_and_final_usage(monkeypatch):
    final = response()
    events = [NS(type="response.created"), NS(type="response.output_text.delta", delta="partial")]
    events.append(NS(type="response.completed", response=final))
    state = install_client(monkeypatch, events, final)
    schema = {"type": "object", "properties": {}}
    result = provider().complete(
        system_prompt="Original system", user_prompt="Original user", response_schema=schema
    )
    assert state["calls"] == [
        dict(
            model="gpt-5.2-2025-12-11",
            instructions="Original system",
            input="Original user",
            max_output_tokens=24000,
            store=False,
            reasoning={"effort": "medium"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "qualframe_synthesis",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
    ]
    assert state["client_options"] == dict(api_key="fake-key", timeout=600.0, max_retries=0)
    assert state["consumed"] == 3 and state["final_calls"] == 1
    assert state["client_closed"] and state["stream_closed"]
    assert result.text == "final text" and result.response_id == "response-synthetic"
    assert result.service_tier == "priority"
    assert result.usage == LLMUsage(
        input_tokens=15, cached_input_tokens=5, output_tokens=10, reasoning_tokens=90
    )


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_terminal_noncompleted_response_preserves_usage_for_runner(monkeypatch, status):
    final = response(status)
    state = install_client(monkeypatch, [NS(type=f"response.{status}", response=final)])
    result = provider().complete(system_prompt="s", user_prompt="u")
    assert result.status == status and result.usage is not None
    assert result.finish_reason == (
        "max_output_tokens" if status == "incomplete" else "server_error"
    )
    assert state["final_calls"] == 0 and len(state["calls"]) == 1
    assert state["client_closed"] and state["stream_closed"]


@pytest.mark.parametrize("mode", ["interrupted", "error_event", "eof"])
def test_partial_stream_never_becomes_output_or_retries(monkeypatch, tmp_path, mode):
    events = [NS(type="response.output_text.delta", delta="partial must not be returned")]
    if mode == "error_event":
        events.append(NS(type="error", message="Sensitive request details"))
    error = TimeoutError("Synthetic interruption") if mode == "interrupted" else None
    state = install_client(monkeypatch, events, failure=error)
    cost = controller(tmp_path, max_output_tokens=10)
    runner = object.__new__(ProjectRunner)
    with pytest.raises(RuntimeError, match="no automatic retry"):
        runner._complete(
            provider=provider(),
            cost_controller=cost,
            stage_id="coding",
            input_label="synthetic",
            user_prompt="u",
        )
    assert len(state["calls"]) == 1 and state["client_closed"] and state["stream_closed"]
    assert cost.project_cost_usd() == 0 and len(cost.unresolved_requests()) == 1
    receipt = json.loads(next((cost.artifact_root / "requests").glob("*.json")).read_text())
    assert receipt["status"] == "usage_unresolved"
    assert "Sensitive request details" not in json.dumps(receipt)
    with pytest.raises(UnresolvedRequest):
        cost.preflight(
            stage_id="coding", input_label="synthetic", system_prompt="s", user_prompt="u"
        )
    assert len(state["calls"]) == 1


@pytest.mark.parametrize("text,usage", [("", True), ("final text", False)])
def test_empty_or_missing_usage_stays_visible_to_caller(monkeypatch, text, usage):
    final = response(text=text, usage=usage)
    state = install_client(monkeypatch, [NS(type="response.completed", response=final)], final)
    result = provider().complete(system_prompt="s", user_prompt="u")
    assert result.text == text and result.status == "completed"
    assert (result.usage is not None) == usage
    assert len(state["calls"]) == 1 and state["client_closed"]


@pytest.mark.parametrize("terminal_status", ["completed", "incomplete", "failed"])
def test_real_installed_sdk_stream_uses_one_mock_http_request(monkeypatch, terminal_status):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    real_client = openai.OpenAI
    requests, clients = [], []

    def payload(status, text=""):
        return dict(
            id="resp-fixture",
            object="response",
            created_at=1,
            model="gpt-5.2-2025-12-11",
            status=status,
            error={"code": "server_error", "message": "Synthetic"} if status == "failed" else None,
            incomplete_details={"reason": "max_output_tokens"} if status == "incomplete" else None,
            service_tier="default",
            output=[
                dict(
                    id="msg-1",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[dict(type="output_text", text=text, annotations=[])],
                )
            ]
            if text
            else [],
            usage=dict(
                input_tokens=20,
                input_tokens_details=dict(cached_tokens=5),
                output_tokens=10,
                output_tokens_details=dict(reasoning_tokens=3),
                total_tokens=30,
            ),
            parallel_tool_calls=True,
            tool_choice="auto",
            tools=[],
        )

    def handle(request):
        requests.append(json.loads(request.content))
        events = [
            dict(type="response.created", response=payload("in_progress"), sequence_number=0),
            dict(
                type=f"response.{terminal_status}",
                response=payload(terminal_status, "Fixture output"),
                sequence_number=1,
            ),
        ]
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    def client(**kwargs):
        result = real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )
        clients.append(result)
        return result

    monkeypatch.setenv("SYNTHETIC_KEY", "fake-key")
    monkeypatch.setattr(openai, "OpenAI", client)
    result = provider().complete(system_prompt="s", user_prompt="u")
    assert len(requests) == 1 and requests[0]["stream"] is True
    assert requests[0]["store"] is False and requests[0]["max_output_tokens"] == 24000
    assert result.status == terminal_status and result.text == "Fixture output"
    assert result.usage == LLMUsage(
        input_tokens=15, cached_input_tokens=5, output_tokens=7, reasoning_tokens=3
    )
    assert result.service_tier == "default" and clients[0].is_closed()


def test_old_response_reconstruction_keeps_optional_tier_compatible():
    assert LLMResponse(**dict(text="old cached output", model="mock")).service_tier is None
