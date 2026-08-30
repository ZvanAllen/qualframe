from __future__ import annotations

from pathlib import Path
from typing import Type, TypeVar

import yaml
from pydantic import BaseModel

from qualframe.models import (
    AnalysisPlanSpec,
    CodebookSpec,
    CostPolicySpec,
    DisagreementSpec,
    FrameworkSpec,
    MethodSpec,
    PipelineSpec,
    PricingSnapshotSpec,
    ProjectManifest,
    PromptSet,
    ReviewPolicySpec,
    StageOutputSpec,
)

T = TypeVar("T", bound=BaseModel)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML at {path} did not contain a top-level mapping.")
    return data


def _load_model(path: Path, model: Type[T]) -> T:
    return model.model_validate(_load_yaml(path))


def repo_root_from(path: Path) -> Path:
    return path.resolve().parents[1] if path.name == "project.yaml" else path.resolve().parent


def resolve_repo_path(repo_root: Path, maybe_relative: str) -> Path:
    path = Path(maybe_relative)
    return path if path.is_absolute() else (repo_root / path).resolve()


def load_project_manifest(path: Path) -> ProjectManifest:
    return _load_model(path, ProjectManifest)


def load_framework_spec(path: Path) -> FrameworkSpec:
    return _load_model(path, FrameworkSpec)


def load_method_spec(path: Path) -> MethodSpec:
    return _load_model(path, MethodSpec)


def load_codebook_spec(path: Path) -> CodebookSpec:
    return _load_model(path, CodebookSpec)


def load_review_policy_spec(path: Path) -> ReviewPolicySpec:
    return _load_model(path, ReviewPolicySpec)


def load_analysis_plan_spec(path: Path) -> AnalysisPlanSpec:
    return _load_model(path, AnalysisPlanSpec)


def load_cost_policy_spec(path: Path) -> CostPolicySpec:
    return _load_model(path, CostPolicySpec)


def load_pricing_snapshot_spec(path: Path) -> PricingSnapshotSpec:
    return _load_model(path, PricingSnapshotSpec)


def load_pipeline_spec(path: Path) -> PipelineSpec:
    return _load_model(path, PipelineSpec)


def load_prompt_set(path: Path) -> PromptSet:
    return _load_model(path, PromptSet)


def load_disagreement_spec(path: Path) -> DisagreementSpec:
    return _load_model(path, DisagreementSpec)


def load_stage_output_spec(path: Path) -> StageOutputSpec:
    return _load_model(path, StageOutputSpec)
