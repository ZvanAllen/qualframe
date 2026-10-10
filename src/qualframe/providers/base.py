from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LLMUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """Return a rough display estimate without provider calls."""
    return max(1, (len(text) + 3) // 4)


@dataclass
class LLMResponse:
    text: str
    model: str | None = None
    provider: str | None = None
    response_id: str | None = None
    usage: LLMUsage | None = None
    status: str = "completed"
    finish_reason: str | None = None
    service_tier: str | None = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
