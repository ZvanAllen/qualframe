from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage

_MAX_RETRIES = 3
_RETRY_DELAY = 5.0  # seconds between retries


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "ANTHROPIC_API_KEY",
        max_tokens: int = 4000,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.temperature = temperature

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
    ) -> LLMResponse:
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Anthropic SDK is not installed. Install with `pip install -e .[llm]`."
            ) from exc

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Environment variable {self.api_key_env!r} is not set."
            )

        client = anthropic.Anthropic(api_key=api_key, timeout=300.0)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                text_blocks: list[str] = []
                with client.messages.stream(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
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
                    usage=LLMUsage(
                        input_tokens=getattr(usage, "input_tokens", 0) or 0,
                        cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                        cache_write_tokens=(
                            getattr(usage, "cache_creation_input_tokens", 0) or 0
                        ),
                        output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    ),
                )
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))

        raise RuntimeError(
            f"Anthropic API call failed after {_MAX_RETRIES} attempts"
        ) from last_exc
