from __future__ import annotations

from pathlib import Path

from qualframe.config import load_prompt_set


def get_prompt_text(prompt_set_path: Path, prompt_ref: str, repo_root: Path) -> str:
    prompt_set = load_prompt_set(prompt_set_path)
    if prompt_ref not in prompt_set.stages:
        raise KeyError(f"Prompt ref '{prompt_ref}' not found in {prompt_set_path}.")
    file_path = repo_root / prompt_set.stages[prompt_ref].file
    return file_path.read_text(encoding="utf-8")


def list_prompt_files(prompt_set_path: Path) -> dict[str, str]:
    prompt_set = load_prompt_set(prompt_set_path)
    return {stage_id: spec.file for stage_id, spec in prompt_set.stages.items()}
