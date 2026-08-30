from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage

_MAX_RETRIES = 3
_RETRY_DELAY = 5.0


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "OPENAI_API_KEY",
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
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI SDK is not installed. Install with `pip install -e .[llm]`."
            ) from exc

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Environment variable {self.api_key_env!r} is not set."
            )

        client = OpenAI(api_key=api_key, timeout=300.0)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                usage = response.usage
                prompt_details = getattr(usage, "prompt_tokens_details", None)
                completion_details = getattr(usage, "completion_tokens_details", None)
                reasoning_tokens = (
                    getattr(completion_details, "reasoning_tokens", 0) or 0
                )
                return LLMResponse(
                    text=(response.choices[0].message.content or "").strip(),
                    model=response.model,
                    provider=self.name,
                    response_id=response.id,
                    usage=LLMUsage(
                        input_tokens=max(
                            (getattr(usage, "prompt_tokens", 0) or 0)
                            - (getattr(prompt_details, "cached_tokens", 0) or 0),
                            0,
                        ),
                        cached_input_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
                        output_tokens=max(
                            (getattr(usage, "completion_tokens", 0) or 0)
                            - reasoning_tokens,
                            0,
                        ),
                        reasoning_tokens=reasoning_tokens,
                    ),
                )
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))

        raise RuntimeError(
            f"OpenAI API call failed after {_MAX_RETRIES} attempts"
        ) from last_exc
