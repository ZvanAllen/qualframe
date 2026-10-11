"""Coding instructions: read the study's current instructions, save edits as a new version, switch versions.

Released prompt files are never edited. An edit writes a new prompt file, prompt set and framework
file in the study's own config folder, points the study at the new framework, and logs the change.
Every run records the hash of the instructions it used, so runs coded with different versions can be
compared and reported.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from qualframe.config import load_project_manifest, resolve_repo_path
from qualframe.io.files import sha256_for_file

STANDARD_LABEL = "QualFrame standard instructions"
JSON_CONTRACT = '"codings"'


@dataclass(frozen=True)
class InstructionsVersion:
    framework_ref: str
    prompt_path: str
    label: str
    sha256: str
    created_at_utc: str | None
    created_by: str | None
    current: bool


def _framework_prompt(repo_root: Path, framework_ref: str) -> tuple[str, str, str]:
    """(stage id, prompt file path relative to the studies folder, label) for a framework file."""
    framework = yaml.safe_load(resolve_repo_path(repo_root, framework_ref).read_text(encoding="utf-8")) or {}
    prompt_set_ref = framework.get("prompt_set")
    if not prompt_set_ref:
        raise ValueError("This study's framework has no coding instructions.")
    prompt_set = yaml.safe_load(resolve_repo_path(repo_root, prompt_set_ref).read_text(encoding="utf-8")) or {}
    stages = prompt_set.get("stages") or {}
    if len(stages) != 1:
        raise ValueError("Editing is available for single-step coding instructions. "
                         "The CFIR reference workflow keeps its published prompts unchanged.")
    stage_id, spec = next(iter(stages.items()))
    label = prompt_set.get("label") or (STANDARD_LABEL if not prompt_set.get("study_version") else prompt_set.get("description", ""))
    return stage_id, spec["file"], label


def current_instructions(repo_root: Path, project_path: Path) -> tuple[str, Path, str, str]:
    """(stage id, prompt file, text, label) for the instructions the study uses now."""
    project = load_project_manifest(project_path)
    stage_id, prompt_ref, label = _framework_prompt(repo_root, project.framework)
    path = resolve_repo_path(repo_root, prompt_ref)
    return stage_id, path, path.read_text(encoding="utf-8"), label


def _changes(study_root: Path) -> list[dict]:
    path = study_root / "logs/study_changes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("change_kind") == "instructions_update"]


def instruction_versions(repo_root: Path, project_path: Path) -> list[InstructionsVersion]:
    project = load_project_manifest(project_path)
    changes = _changes(project_path.parent)
    refs: list[str] = []
    meta: dict[str, dict] = {}
    for change in changes:
        if change.get("previous_ref") and change["previous_ref"] not in refs:
            refs.append(change["previous_ref"])
        if change["new_ref"] not in refs:
            refs.append(change["new_ref"])
            meta[change["new_ref"]] = change
    if project.framework not in refs:
        refs.append(project.framework)
    versions = []
    for ref in refs:
        try:
            _, prompt_ref, label = _framework_prompt(repo_root, ref)
        except (OSError, ValueError, KeyError):
            continue
        prompt = resolve_repo_path(repo_root, prompt_ref)
        change = meta.get(ref, {})
        versions.append(InstructionsVersion(
            framework_ref=ref, prompt_path=prompt_ref, label=label, sha256=sha256_for_file(prompt),
            created_at_utc=change.get("timestamp_utc"), created_by=change.get("actor"),
            current=ref == project.framework))
    return versions


def save_instructions(workspace, project_path: Path, *, text: str, label: str, actor: str, rationale: str) -> str:
    """Write the edited instructions as a new version and make it current. Returns the framework ref."""
    actor, rationale = workspace._validate_action_fields(actor, rationale)
    study_root = workspace.managed_study_root(project_path)
    project = load_project_manifest(project_path)
    stage_id, _, current_text, _ = current_instructions(workspace.repo_root, project_path)
    text = text.replace("\r\n", "\n").strip() + "\n"
    label = " ".join(label.split())[:120]
    if not label:
        raise ValueError("Give this version a short name, such as \"Shorter quotations\".")
    if len(text) < 200:
        raise ValueError("The instructions look too short. Edit the existing text rather than replacing it.")
    if JSON_CONTRACT not in text:
        raise ValueError('Keep the Output section: the instructions must still ask for the {"codings": [...]} JSON format.')
    if text == current_text.replace("\r\n", "\n").strip() + "\n":
        raise ValueError("No changes to save.")
    config = study_root / "config"
    prompt_path = workspace._next_version_path(config / "prompts", "coding_instructions", ".md")
    number = prompt_path.stem.rsplit("_v", 1)[1]
    prompt_path.write_text(text, encoding="utf-8")
    framework = yaml.safe_load(resolve_repo_path(workspace.repo_root, project.framework).read_text(encoding="utf-8"))
    prompt_set_path = config / f"prompt_set_v{number}.yaml"
    prompt_set_path.write_text(yaml.safe_dump({
        "id": f"{project.project_id}_instructions_v{number}",
        "description": label,
        "label": label,
        "study_version": int(number),
        "stages": {stage_id: {"file": prompt_path.relative_to(workspace.repo_root).as_posix(),
                              "notes": f"Edited by {actor}: {rationale}"}},
    }, sort_keys=False), encoding="utf-8")
    framework["prompt_set"] = prompt_set_path.relative_to(workspace.repo_root).as_posix()
    framework_path = config / f"framework_v{number}.yaml"
    framework_path.write_text(yaml.safe_dump(framework, sort_keys=False), encoding="utf-8")
    new_ref = framework_path.relative_to(workspace.repo_root).as_posix()
    previous = project.framework
    workspace._update_project_reference(project_path, "framework", new_ref)
    workspace._append_change(study_root, project_id=project.project_id, change_kind="instructions_update",
                             previous_ref=previous, new_ref=new_ref, actor=actor, rationale=rationale)
    return new_ref


def use_instructions(workspace, project_path: Path, *, framework_ref: str, actor: str, rationale: str) -> str:
    """Switch the study to an earlier version listed by instruction_versions."""
    actor, rationale = workspace._validate_action_fields(actor, rationale)
    study_root = workspace.managed_study_root(project_path)
    known = {v.framework_ref: v for v in instruction_versions(workspace.repo_root, project_path)}
    if framework_ref not in known:
        raise ValueError("That version of the coding instructions is not part of this study.")
    project = load_project_manifest(project_path)
    if project.framework == framework_ref:
        return framework_ref
    workspace._update_project_reference(project_path, "framework", framework_ref)
    workspace._append_change(study_root, project_id=project.project_id, change_kind="instructions_update",
                             previous_ref=project.framework, new_ref=framework_ref, actor=actor, rationale=rationale)
    return framework_ref
