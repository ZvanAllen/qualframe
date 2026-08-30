from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage

_MAX_RETRIES = 3
_RETRY_DELAY = 5.0


class GoogleProvider(LLMProvider):
    name = "google"

    def __init__(
        self,
        *,
        model: str,
        api_key_env: str = "GOOGLE_API_KEY",
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
            import google.generativeai as genai  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Google Generative AI SDK is not installed. "
                "Install with `pip install -e .[llm]`."
            ) from exc

        api_key = os.getenv(self.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Environment variable {self.api_key_env!r} is not set."
            )

        genai.configure(api_key=api_key, transport="rest")

        generation_config = genai.GenerationConfig(
            max_output_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                model = genai.GenerativeModel(
                    model_name=self.model,
                    system_instruction=system_prompt,
                    generation_config=generation_config,
                )
                response = model.generate_content(
                    user_prompt, request_options={"timeout": 300}
                )
                usage = getattr(response, "usage_metadata", None)
                return LLMResponse(
                    text=response.text.strip(),
                    model=self.model,
                    provider=self.name,
                    response_id=getattr(response, "response_id", None),
                    usage=LLMUsage(
                        input_tokens=max(
                            (getattr(usage, "prompt_token_count", 0) or 0)
                            - (getattr(usage, "cached_content_token_count", 0) or 0),
                            0,
                        ),
                        cached_input_tokens=getattr(usage, "cached_content_token_count", 0) or 0,
                        output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
                        reasoning_tokens=getattr(usage, "thoughts_token_count", 0) or 0,
                    ),
                )
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))

        raise RuntimeError(
            f"Google API call failed after {_MAX_RETRIES} attempts"
        ) from last_exc
