from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from qualframe.config import (
    load_analysis_plan_spec,
    load_codebook_spec,
    load_cost_policy_spec,
    load_framework_spec,
    load_method_spec,
    load_pipeline_spec,
    load_project_manifest,
    load_prompt_set,
    load_pricing_snapshot_spec,
    load_review_policy_spec,
    load_stage_output_spec,
    resolve_repo_path,
)
from qualframe.decision_style import get_stage_prompt_path, validate_decision_style
from qualframe.io.files import sha256_for_file
from qualframe.models import (
    ConfigurationAssetRef,
    ConfigurationImpact,
    LockedAnalysisConfiguration,
)


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _file_asset(
    *,
    kind: str,
    asset_id: str,
    version: str | None,
    path: Path,
    repo_root: Path,
) -> ConfigurationAssetRef:
    return ConfigurationAssetRef(
        kind=kind,
        id=asset_id,
        version=version,
        path=_display_path(path, repo_root),
        sha256=sha256_for_file(path),
    )


def _embedded_asset(kind: str, asset_id: str, value: BaseModel) -> ConfigurationAssetRef:
    return ConfigurationAssetRef(
        kind=kind,
        id=asset_id,
        sha256=_canonical_sha256(value.model_dump(mode="json")),
    )


def create_configuration_lock(project_yaml: Path) -> LockedAnalysisConfiguration:
    """Load and hash every configured analysis asset without exposing secret values."""
    project_yaml = project_yaml.resolve()
    repo_root = project_yaml.parents[2]
    project = load_project_manifest(project_yaml)

    framework_path = resolve_repo_path(repo_root, project.framework)
    pipeline_path = resolve_repo_path(repo_root, project.pipeline)
    framework = load_framework_spec(framework_path)
    pipeline = load_pipeline_spec(pipeline_path)
    method = load_method_spec(resolve_repo_path(repo_root, project.method)) if project.method else None
    validate_decision_style(pipeline, method)
    if not framework.prompt_set:
        raise ValueError("framework spec does not define a prompt_set")
    prompt_set_path = resolve_repo_path(repo_root, framework.prompt_set)
    prompt_set = load_prompt_set(prompt_set_path)

    assets: list[ConfigurationAssetRef] = [
        _file_asset(
            kind="project",
            asset_id=project.project_id,
            version=None,
            path=project_yaml,
            repo_root=repo_root,
        ),
        _file_asset(
            kind="framework",
            asset_id=framework.id,
            version=None,
            path=framework_path,
            repo_root=repo_root,
        ),
        _file_asset(
            kind="pipeline",
            asset_id=pipeline.id,
            version=None,
            path=pipeline_path,
            repo_root=repo_root,
        ),
        _file_asset(
            kind="prompt_set",
            asset_id=prompt_set.id,
            version=None,
            path=prompt_set_path,
            repo_root=repo_root,
        ),
    ]

    for stage_id, prompt in prompt_set.stages.items():
        # A ref may be shared by coding and later stages. Lock every distinct
        # file actually selected, without changing legacy single-prompt assets.
        prompt_paths = dict.fromkeys(
            get_stage_prompt_path(repo_root, prompt_set_path, stage, method)
            for stage in pipeline.stages if stage.enabled and stage.prompt_ref == stage_id
        ) or {resolve_repo_path(repo_root, prompt.file): None}
        for prompt_path in prompt_paths:
            assets.append(
                _file_asset(
                    kind="prompt",
                    asset_id=stage_id,
                    version=None,
                    path=prompt_path,
                    repo_root=repo_root,
                )
            )

    optional_assets: list[tuple[str, str | None, Callable[[Path], BaseModel]]] = [
        ("method", project.method, load_method_spec),
        ("codebook", project.codebook, load_codebook_spec),
        ("review_policy", project.review_policy, load_review_policy_spec),
        ("analysis_plan", project.analysis_plan, load_analysis_plan_spec),
        ("cost_policy", project.cost_policy, load_cost_policy_spec),
        ("pricing_snapshot", project.pricing_snapshot, load_pricing_snapshot_spec),
    ]
    for kind, configured_path, loader in optional_assets:
        if not configured_path:
            continue
        asset_path = resolve_repo_path(repo_root, configured_path)
        asset = loader(asset_path)
        assets.append(
            _file_asset(
                kind=kind,
                asset_id=str(getattr(asset, "id")),
                version=getattr(asset, "version", None),
                path=asset_path,
                repo_root=repo_root,
            )
        )

    reference_book = resolve_repo_path(repo_root, project.paths.get('reference', 'data/reference')) / 'codebook.xlsx'
    if any(stage.domain_iterations for stage in pipeline.stages) and reference_book.exists():
        assets.append(_file_asset(kind='codebook', asset_id='cfir-reference', version=None,
            path=reference_book, repo_root=repo_root))

    if project.structured_output.enforce:
        schema_path = resolve_repo_path(repo_root, project.structured_output.spec)
        schema = load_stage_output_spec(schema_path)
        assets.append(
            _file_asset(
                kind="structured_output_schema",
                asset_id=schema.id,
                version=None,
                path=schema_path,
                repo_root=repo_root,
            )
        )

    assets.extend(
        [
            _embedded_asset("provider", project.provider.name, project.provider),
            _embedded_asset("governance", "project_governance", project.governance),
            _embedded_asset("structured_output", "structured_output_policy", project.structured_output),
        ]
    )
    assets = sorted(assets, key=lambda item: (item.kind, item.id, item.path or ""))
    fingerprint = _canonical_sha256([asset.model_dump(mode="json") for asset in assets])
    return LockedAnalysisConfiguration(
        lock_id=f"{project.project_id}:{fingerprint[:12]}",
        project_id=project.project_id,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        fingerprint_sha256=fingerprint,
        assets=assets,
    )


def compare_configuration_locks(
    previous: LockedAnalysisConfiguration,
    current: LockedAnalysisConfiguration,
) -> ConfigurationImpact:
    """Identify changed asset types and whether prior analysis must be rerun."""
    previous_assets = {
        (asset.kind, asset.id, asset.path): asset.sha256 for asset in previous.assets
    }
    current_assets = {
        (asset.kind, asset.id, asset.path): asset.sha256 for asset in current.assets
    }
    keys = set(previous_assets) | set(current_assets)
    changed = sorted(
        {key[0] for key in keys if previous_assets.get(key) != current_assets.get(key)}
    )
    return ConfigurationImpact(
        previous_fingerprint=previous.fingerprint_sha256,
        current_fingerprint=current.fingerprint_sha256,
        changed_asset_kinds=changed,
        requires_rerun=previous.fingerprint_sha256 != current.fingerprint_sha256,
    )


def write_configuration_lock(lock: LockedAnalysisConfiguration, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(lock.model_dump_json(indent=2), encoding="utf-8")
    return output_path


# Spending settings: the study's spending limit and the price list. Changing them (for example
# raising the limit after a run pauses) changes nothing about how the transcripts are coded.
SPENDING_KINDS = ("cost_policy", "pricing_snapshot")


def spending_only_change(project_yaml: Path, locked: LockedAnalysisConfiguration) -> bool:
    """True when the study differs from a run's locked configuration only in its spending settings.

    Everything that shapes the coding (prompts, codebook, method, pipeline, model and its settings)
    must be identical. The run's earlier study file is found among the snapshots QualFrame keeps
    whenever the model or spending settings are saved.
    """
    import yaml

    project_yaml = project_yaml.resolve()
    current = create_configuration_lock(project_yaml)
    if current.fingerprint_sha256 == locked.fingerprint_sha256:
        return True

    def coding_assets(lock: LockedAnalysisConfiguration) -> dict:
        return {(a.kind, a.id, a.path): a.sha256 for a in lock.assets if a.kind not in SPENDING_KINDS + ("project",)}

    if coding_assets(current) != coding_assets(locked):
        return False
    earlier_hash = next((a.sha256 for a in locked.assets if a.kind == "project"), None)
    earlier = next((path for path in sorted(project_yaml.parent.glob("config/provider-*/project-*.yaml"))
                    if sha256_for_file(path) == earlier_hash), None)
    if earlier is None:
        return False

    def without_spending(path: Path) -> dict:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return {key: value for key, value in data.items() if key not in SPENDING_KINDS}

    return without_spending(earlier) == without_spending(project_yaml)


def run_can_resume(project_yaml: Path, artifact_root: Path, configuration_fingerprint: str | None) -> bool:
    """Whether a run planned under ``configuration_fingerprint`` may continue with the study as it is now."""
    lock_path = artifact_root / "analysis_configuration_lock.json"
    if not configuration_fingerprint or not lock_path.exists():
        return False
    locked = LockedAnalysisConfiguration.model_validate_json(lock_path.read_text(encoding="utf-8"))
    if locked.fingerprint_sha256 != configuration_fingerprint:
        return False
    return spending_only_change(project_yaml, locked)
