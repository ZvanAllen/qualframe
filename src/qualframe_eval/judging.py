"""Helpers to build blinded judging packs and validate evaluator JSON output."""

from __future__ import annotations

import json
from pathlib import Path


def load_schema(path: str | Path) -> dict:
    """Load a JSON schema file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def blinded_candidate_ids(candidates: list[str]) -> dict[str, str]:
    """Map source candidate IDs (e.g. model names / run IDs) to blinded labels.

    Example: ["claude", "gpt", "gemini"] → {"claude": "Model A", "gpt": "Model B", ...}
    """
    return {cid: f"Model {chr(65 + idx)}" for idx, cid in enumerate(candidates)}
