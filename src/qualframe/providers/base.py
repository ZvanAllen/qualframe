from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass
class LLMUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


def estimate_tokens(text: str) -> int:
    """Return a conservative local token estimate without provider calls."""
    return max(1, (len(text) + 3) // 4)


@dataclass
class LLMResponse:
    text: str
    model: str | None = None
    provider: str | None = None
    response_id: str | None = None
    usage: LLMUsage | None = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
