from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from qualframe.models import GateAction, ReleaseAction, RunManifest


def _append_jsonl(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")


def load_gate_actions(artifact_root: Path) -> list[GateAction]:
    path = artifact_root / "governance" / "gate_actions.jsonl"
    if not path.exists():
        return []
    return [
        GateAction.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def latest_gate_actions(artifact_root: Path) -> dict[str, GateAction]:
    latest: dict[str, GateAction] = {}
    for action in load_gate_actions(artifact_root):
        latest[action.stage_id] = action
    return latest


def approved_gate_ids(artifact_root: Path) -> set[str]:
    return {
        stage_id
        for stage_id, action in latest_gate_actions(artifact_root).items()
        if action.decision == "approve"
    }


def append_gate_action(
    artifact_root: Path,
    *,
    run_id: str,
    stage_id: str,
    decision: str,
    reviewer: str,
    rationale: str,
) -> GateAction:
    action = GateAction(
        action_id=f"gate-{uuid4().hex}",
        run_id=run_id,
        stage_id=stage_id,
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )
    if not action.reviewer or not action.rationale:
        raise ValueError("Reviewer and rationale are required for a gate action.")
    _append_jsonl(
        artifact_root / "governance" / "gate_actions.jsonl",
        action.model_dump_json(),
    )
    return action


def append_release_action(
    artifact_root: Path,
    *,
    run_id: str,
    reviewer: str,
    rationale: str,
) -> ReleaseAction:
    manifest_path = artifact_root / "run_manifest.json"
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.status != "completed":
        raise ValueError("Run cannot be released before all enforced gates are approved.")

    action = ReleaseAction(
        action_id=f"release-{uuid4().hex}",
        run_id=run_id,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )
    if not action.reviewer or not action.rationale:
        raise ValueError("Reviewer and rationale are required for release.")
    _append_jsonl(
        artifact_root / "governance" / "release_actions.jsonl",
        action.model_dump_json(),
    )
    manifest.release_status = "released"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return action


def assert_export_allowed(artifact_root: Path, require_release: bool) -> None:
    if not require_release:
        return
    manifest_path = artifact_root / "run_manifest.json"
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if manifest.status != "completed" or manifest.release_status != "released":
        raise PermissionError(
            "Export blocked: enforced review gates must be approved and the run explicitly released."
        )
