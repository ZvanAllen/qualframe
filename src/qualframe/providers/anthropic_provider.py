from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "ANTHROPIC_API_KEY",
        max_tokens: int = 4000,
        temperature: float | None = 0.0,
        effort: str | None = None,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.effort = effort

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic SDK is not installed. Install with `pip install -e .[llm]`."
            ) from exc

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {self.api_key_env!r} is not set.")

        client = anthropic.Anthropic(api_key=api_key, timeout=300.0, max_retries=0)

        output_config = {"effort": self.effort} if self.effort else {}
        if response_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": response_schema}
        # extra_body keeps this API field available in older supported SDK versions.
        text_blocks: list[str] = []
        with client.messages.stream(
            **({"extra_body": {"output_config": output_config}} if output_config else {}),
            model=self.model,
            max_tokens=self.max_tokens,
            **({} if self.temperature is None else {"temperature": self.temperature}),
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                text_blocks.append(text)
            final_message = stream.get_final_message()
        usage = final_message.usage
        return LLMResponse(
            text="".join(text_blocks).strip(),
            model=final_message.model,
            provider=self.name,
            response_id=final_message.id,
            status="completed"
            if final_message.stop_reason in {"end_turn", "stop_sequence"}
            else "incomplete",
            finish_reason=final_message.stop_reason,
            usage=LLMUsage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=(getattr(usage, "cache_creation_input_tokens", 0) or 0),
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            )
            if usage is not None
            else None,
        )
