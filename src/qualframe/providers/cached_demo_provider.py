from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens


class CachedDemoProvider(LLMProvider):
    """Replay checked-in synthetic responses for the interview demo.

    This provider never opens a network connection. It exists only to make the
    synthetic demo deterministic and presentable when model credentials or
    connectivity are unavailable.
    """

    name = "cached_demo"
    model = "qualframe-synthetic-cache-v1"

    def __init__(self, cache_dir: Path | None = None) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.cache_dir = cache_dir or repo_root / "demo" / "cached_responses"

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        attachments: Sequence[Path] | None = None,
    ) -> LLMResponse:
        stage_id, replacements = self._identify_response(user_prompt)
        template_path = self.cache_dir / f"{stage_id}.md"
        if not template_path.exists():
            raise FileNotFoundError(
                f"Cached demo response is missing: {template_path}. "
                "The interview demo cannot fall back safely without this checked-in fixture."
            )

        text = template_path.read_text(encoding="utf-8")
        for key, value in replacements.items():
            text = text.replace("{" + key + "}", value)
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            usage=LLMUsage(
                input_tokens=estimate_tokens(system_prompt + user_prompt),
                output_tokens=estimate_tokens(text),
            ),
        )

    def _identify_response(self, user_prompt: str) -> tuple[str, dict[str, str]]:
        if "Code the transcript for ONE CFIR domain only:" in user_prompt:
            match = re.search(
                r"Code the transcript for ONE CFIR domain only:\s*([^\r\n.]+)",
                user_prompt,
            )
            domain = match.group(1).strip() if match else "Implementation Process"
            return "transcript_to_cfir", {"CFIR_DOMAIN": domain}

        if "rolls up subconstruct-level rows into their parent construct" in user_prompt:
            return "participant_parent_construct_rollup", {}

        if "using the attached transcript where the quotes" in user_prompt:
            return "quote_context_enrichment", {}

        if "Two Excel workbooks (or worksheets) with CFIR-coded tables" in user_prompt:
            network_match = re.search(
                r"demo[/\\]fixtures[/\\]transcripts[/\\]([^/\\\r\n]+)",
                user_prompt,
            )
            source_label = network_match.group(1) if network_match else "Synthetic Network Alpha"
            return "participant_to_network_synthesis", {"SOURCE_LABEL": source_label}

        if "Eight Excel workbooks, each representing one jurisdictional" in user_prompt:
            return "cross_network_synthesis", {}

        raise ValueError(
            "CachedDemoProvider could not identify the requested stage. "
            "The production prompts may have changed; refresh the synthetic cache deliberately."
        )
