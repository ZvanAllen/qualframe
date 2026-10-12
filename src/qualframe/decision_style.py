"""Select the versioned instructions that are executed and locked for a method."""
from __future__ import annotations

from pathlib import Path

from qualframe.config import load_prompt_set, resolve_repo_path
from qualframe.models import MethodSpec, PipelineSpec, StageSpec

DECIDE_EACH_CODE_PROMPT = "prompts/directed/v4/decide_each_code.md"


def uses_code_decisions(stage: StageSpec, method: MethodSpec | None) -> bool:
    return bool(
        method and method.coding.decision_style == "decide_each_code"
        and not stage.domain_iterations and stage.input_source == "raw_transcripts"
        and stage.use_codebook and stage.input_grouping == "per_file"
    )


def validate_decision_style(pipeline: PipelineSpec, method: MethodSpec | None) -> None:
    if not method or method.coding.decision_style != "decide_each_code":
        return
    active = [stage for stage in pipeline.stages if stage.enabled and stage.prompt_ref]
    if any(stage.domain_iterations for stage in active) or not any(
        uses_code_decisions(stage, method) for stage in active
    ):
        raise ValueError("Decide on every code requires the general directed coding workflow; "
                         "the CFIR reference workflow keeps its published instructions.")


def get_stage_prompt_path(repo_root: Path, prompt_set_path: Path,
                          stage: StageSpec, method: MethodSpec | None) -> Path:
    if uses_code_decisions(stage, method):
        return resolve_repo_path(repo_root, DECIDE_EACH_CODE_PROMPT)
    prompt_set = load_prompt_set(prompt_set_path)
    if stage.prompt_ref not in prompt_set.stages:
        raise KeyError(f"Prompt ref '{stage.prompt_ref}' not found in {prompt_set_path}.")
    return resolve_repo_path(repo_root, prompt_set.stages[stage.prompt_ref].file)
