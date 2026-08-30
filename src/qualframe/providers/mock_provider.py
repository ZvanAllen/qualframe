from __future__ import annotations

from pathlib import Path
from typing import Sequence

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens


def _directed_fixture_response(user_prompt: str) -> str | None:
    """Return offset-valid rows only for the checked-in directed-analysis fixture."""
    marker = "Transcript:\n\n"
    if marker not in user_prompt or "| Meaning Unit ID |" not in user_prompt:
        return None
    transcript = user_prompt.split(marker, 1)[1].split("\n\n---\n\n", 1)[0]
    candidates = [
        (
            "access_availability",
            "Appointments were rarely available when the fictional clinic was needed.",
            "The exact statement describes fictional appointment availability.",
        ),
        (
            "experience_communication",
            "Staff explained the fictional next steps clearly and respectfully.",
            "The exact statement describes fictional service communication.",
        ),
    ]
    rows: list[str] = []
    for index, (code_id, exact_text, rationale) in enumerate(candidates, start=1):
        if f'"id": "{code_id}"' not in user_prompt:
            continue
        start = transcript.find(exact_text)
        if start < 0:
            continue
        rows.append(
            f"| synthetic-unit-{index} | {start} | {start + len(exact_text)} | "
            f"{exact_text} | {code_id} | {rationale} |"
        )
    if not rows:
        return None
    return (
        "## Sheet: Directed Coding\n\n"
        "| Meaning Unit ID | Evidence Start | Evidence End | Exact Evidence | Code ID | Rationale |\n"
        "|---|---:|---:|---|---|---|\n"
        + "\n".join(rows)
    )


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock") -> None:
        self.model = model

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
    ) -> LLMResponse:
        attachment_names = ", ".join(path.name for path in attachments or [])
        message = _directed_fixture_response(user_prompt) or (
            "MOCK RESPONSE\n"
            f"system_prompt_chars={len(system_prompt)}\n"
            f"user_prompt_chars={len(user_prompt)}\n"
            f"attachments={attachment_names or 'none'}"
        )
        return LLMResponse(
            text=message,
            model=self.model,
            provider=self.name,
            usage=LLMUsage(
                input_tokens=estimate_tokens(system_prompt + user_prompt),
                output_tokens=estimate_tokens(message),
            ),
        )
