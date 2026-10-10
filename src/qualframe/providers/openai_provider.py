from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "OPENAI_API_KEY",
        max_tokens: int = 4000,
        temperature: float | None = 0.0,
        api_mode: str = "chat_completions",
        reasoning_effort: str | None = None,
        base_url: str | None = None,
        provider_name: str = "openai",
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.name = provider_name
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_mode = api_mode
        self.reasoning_effort = reasoning_effort

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI SDK is not installed. Install with `pip install -e .[llm]`."
            ) from exc

        api_key = os.getenv(self.api_key_env) if self.api_key_env else None
        if not api_key and self.base_url:
            # Local servers such as Ollama and LM Studio ignore the key but the SDK requires one.
            api_key = "not-required-for-local-endpoint"
        if not api_key:
            raise RuntimeError(f"Environment variable {self.api_key_env!r} is not set.")

        # A model on this computer may read a long transcript for many minutes before its first
        # output, so local servers get a longer wait.
        from urllib.parse import urlparse

        local = (urlparse(self.base_url or "").hostname or "") in {"localhost", "127.0.0.1", "::1"}
        client = OpenAI(
            api_key=api_key, timeout=1800.0 if local else 600.0, max_retries=0,
            **({"base_url": self.base_url} if self.base_url else {}),
        )

        try:
            options = {} if self.temperature is None else {"temperature": self.temperature}
            if response_schema is not None:
                specification = {
                    "name": "qualframe_synthesis",
                    "strict": True,
                    "schema": response_schema,
                }
                if self.api_mode == "responses":
                    options["text"] = {"format": {"type": "json_schema", **specification}}
                else:
                    options["response_format"] = {
                        "type": "json_schema",
                        "json_schema": specification,
                    }
            if self.api_mode == "responses":
                if self.reasoning_effort is not None:
                    options["reasoning"] = {"effort": self.reasoning_effort}
                with client.responses.stream(
                    model=self.model,
                    instructions=system_prompt,
                    input=user_prompt,
                    max_output_tokens=self.max_tokens,
                    store=False,
                    **options,
                ) as stream:
                    terminal_response = None
                    for event in stream:
                        if event.type in {"response.incomplete", "response.failed"}:
                            # Older SDK helpers only finalize response.completed.
                            # Preserve terminal failure/incomplete usage for accounting.
                            terminal_response = event.response
                        elif event.type == "error":
                            raise RuntimeError("OpenAI response stream reported an error.")
                    # This consumes only the existing stream; it sends no retrieval or retry.
                    response = (
                        terminal_response
                        if terminal_response is not None
                        else stream.get_final_response()
                    )
                usage = response.usage
                cached = (
                    getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
                )
                reasoning = (
                    getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0)
                    or 0
                )
                return LLMResponse(
                    text=response.output_text.strip(),
                    model=response.model,
                    provider=self.name,
                    response_id=response.id,
                    status=response.status,
                    finish_reason=(
                        getattr(response.incomplete_details, "reason", None)
                        or getattr(getattr(response, "error", None), "code", None)
                    ),
                    service_tier=getattr(response, "service_tier", None),
                    usage=LLMUsage(
                        input_tokens=max(usage.input_tokens - cached, 0),
                        cached_input_tokens=cached,
                        output_tokens=max(usage.output_tokens - reasoning, 0),
                        reasoning_tokens=reasoning,
                    )
                    if usage is not None
                    else None,
                )

            # Streamed so that a slow local model can take as long as it needs: the timeout
            # applies to each wait for the next piece of output, not to the whole response.
            stream = client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **options,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            parts: list[str] = []
            finish_reason = None
            usage = None
            response_id = model_name = service_tier = None
            for chunk in stream:
                response_id = response_id or getattr(chunk, "id", None)
                model_name = model_name or getattr(chunk, "model", None)
                service_tier = getattr(chunk, "service_tier", None) or service_tier
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", None) if delta is not None else None
                    if content:
                        parts.append(content)
                    if getattr(choice, "finish_reason", None):
                        finish_reason = choice.finish_reason
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            completion_details = getattr(usage, "completion_tokens_details", None)
            reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0) or 0
            return LLMResponse(
                text="".join(parts).strip(),
                model=model_name or self.model,
                provider=self.name,
                response_id=response_id,
                status="completed" if finish_reason == "stop" else "incomplete",
                finish_reason=finish_reason,
                service_tier=service_tier,
                usage=LLMUsage(
                    input_tokens=max(
                        (getattr(usage, "prompt_tokens", 0) or 0)
                        - (getattr(prompt_details, "cached_tokens", 0) or 0),
                        0,
                    ),
                    cached_input_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
                    output_tokens=max(
                        (getattr(usage, "completion_tokens", 0) or 0) - reasoning_tokens,
                        0,
                    ),
                    reasoning_tokens=reasoning_tokens,
                )
                if usage is not None
                else None,
            )
        finally:
            client.close()
