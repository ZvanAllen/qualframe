from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from qualframe.io.files import sha256_for_file
from qualframe.models import AdjudicationAction


def load_adjudication_actions(review_dir: Path) -> list[AdjudicationAction]:
    path = review_dir / "adjudication" / "actions.jsonl"
    if not path.exists():
        return []
    return [
        AdjudicationAction.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_adjudication_action(
    *,
    review_dir: Path,
    artifact_root: Path,
    run_id: str,
    item_path: Path,
    decision: str,
    reviewer: str,
    rationale: str,
    edited_row: dict[str, str] | None = None,
) -> AdjudicationAction:
    review_dir = review_dir.resolve()
    resolved_item = item_path.resolve()
    if not resolved_item.is_relative_to(review_dir) or not resolved_item.exists():
        raise ValueError("Review item must exist inside the selected run review queue.")
    if decision == "edit" and not edited_row:
        raise ValueError("An edit decision requires a non-empty edited row.")
    if decision != "edit" and edited_row is not None:
        raise ValueError("edited_row is allowed only for an edit decision.")
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("Reviewer and rationale are required for adjudication.")

    action_id = f"adjudication-{uuid4().hex}"
    derived_rel: str | None = None
    timestamp = datetime.now(timezone.utc).isoformat()
    if edited_row is not None:
        derived_path = artifact_root / "adjudicated" / f"{action_id}.json"
        derived_path.parent.mkdir(parents=True, exist_ok=True)
        derived_payload = {
            "kind": "adjudicated_row",
            "run_id": run_id,
            "source_review_item": str(resolved_item.relative_to(review_dir)),
            "source_review_item_sha256": sha256_for_file(resolved_item),
            "edited_row": edited_row,
            "created_at_utc": timestamp,
        }
        derived_path.write_text(json.dumps(derived_payload, indent=2), encoding="utf-8")
        derived_rel = str(derived_path.relative_to(artifact_root))

    action = AdjudicationAction(
        action_id=action_id,
        run_id=run_id,
        item_path=str(resolved_item.relative_to(review_dir)),
        item_sha256=sha256_for_file(resolved_item),
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        edited_row=edited_row,
        derived_artifact_path=derived_rel,
        timestamp_utc=timestamp,
    )
    log_path = review_dir / "adjudication" / "actions.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(action.model_dump_json() + "\n")
    return action


def latest_adjudication_by_item(review_dir: Path) -> dict[str, AdjudicationAction]:
    latest: dict[str, AdjudicationAction] = {}
    for action in load_adjudication_actions(review_dir):
        latest[action.item_path] = action
    return latest
