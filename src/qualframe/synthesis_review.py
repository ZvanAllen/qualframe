"""Append-only human review and export of source-linked synthesis statements."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from qualframe.cost_control import _append_jsonl, _read_jsonl, utc_now
from qualframe.io.files import sha256_for_file
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.synthesis_plan import validate_synthesis_response


def job_root(run_root: Path, job_id: str) -> Path:
    if (
        not job_id.startswith("synthesis-")
        or len(job_id) != 42
        or any(c not in "0123456789abcdef" for c in job_id[10:])
    ):
        raise ValueError("Select a synthesis job in this run.")
    return run_root / "analysis" / "synthesis" / job_id


def read_job(target: Path) -> tuple[dict, dict, list[dict]]:
    status = json.loads((target / "status.json").read_text(encoding="utf-8"))
    plan = json.loads((target / "plan.json").read_text(encoding="utf-8"))
    config = json.loads((target / "execution.json").read_text(encoding="utf-8"))
    if (
        snapshot_identity(plan) != status["plan_id"]
        or snapshot_identity(config) != status["execution_sha256"]
    ):
        raise ValueError("Stored synthesis inputs or execution settings have changed.")
    for name, digest in status["response_hashes"].items():
        if Path(name).name != name or sha256_for_file(target / name) != digest:
            raise ValueError("A stored model response has changed.")
    records = []
    if status["status"] in {"awaiting_review", "no_statements"}:
        bundle = json.loads((target / "proposals.json").read_text(encoding="utf-8"))
        if snapshot_identity(bundle) != status["proposals_sha256"]:
            raise ValueError("Stored synthesis proposals have changed.")
        records = bundle["records"]
    return status, plan, records


def latest_summary_actions(target: Path) -> dict[str, dict]:
    return {row["statement_id"]: row for row in _read_jsonl(target / "review_actions.jsonl")}


def review_statement(
    target: Path,
    statement_id: str,
    *,
    decision: str,
    reviewer: str,
    rationale: str = "",
    edited_text: str = "",
    evidence_ids: list[str] | None = None,
) -> dict:
    status, plan, records = read_job(target)
    if status["status"] != "awaiting_review":
        raise ValueError("This job has no completed synthesis proposals to review.")
    record = next((r for r in records if r["statement_id"] == statement_id), None)
    if record is None:
        raise ValueError("Unknown synthesis statement.")
    if decision not in {"accept", "edit", "reject", "defer"} or not reviewer.strip():
        raise ValueError("Select a decision and enter the researcher name.")
    edited = None
    if decision == "edit":
        edited = dict(text=edited_text.strip(), evidence_ids=sorted(set(evidence_ids or [])))
        validate_synthesis_response(
            plan,
            record["group_id"],
            dict(summaries=[dict(code_id=record["code_id"], statements=[edited])]),
        )
    if decision == "accept":
        previous = latest_summary_actions(target).get(statement_id, {})
        if previous.get("edited"):
            if previous["statement_sha256"] != snapshot_identity(record):
                raise ValueError("Reviewed statement changed after its decision.")
            edited = previous["edited"]
            validate_synthesis_response(
                plan,
                record["group_id"],
                dict(summaries=[dict(code_id=record["code_id"], statements=[edited])]),
            )
    action = dict(
        action_id="summary-review-" + uuid.uuid4().hex,
        statement_id=statement_id,
        statement_sha256=snapshot_identity(record),
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        edited=edited,
        timestamp_utc=utc_now(),
    )
    _append_jsonl(target / "review_actions.jsonl", action)
    return action


def export_synthesis(target: Path, *, inputs_current: bool) -> Path:
    status, plan, records = read_job(target)
    if not inputs_current:
        raise ValueError(
            "Review inputs changed. Generate and review a new synthesis before exporting."
        )
    actions = latest_summary_actions(target)
    if not records or any(
        r["statement_id"] not in actions or actions[r["statement_id"]]["decision"] == "defer"
        for r in records
    ):
        raise ValueError("Resolve every proposed summary before exporting.")
    retained, rejected = [], []
    for record in records:
        action = actions[record["statement_id"]]
        if action["statement_sha256"] != snapshot_identity(record):
            raise ValueError("Reviewed statement changed after its decision.")
        if action["decision"] == "reject":
            rejected.append(record["statement_id"])
            continue
        item = dict(record)
        if action["edited"]:
            item.update(action["edited"])
        validate_synthesis_response(
            plan,
            item["group_id"],
            dict(
                summaries=[
                    dict(
                        code_id=item["code_id"],
                        statements=[dict(text=item["text"], evidence_ids=item["evidence_ids"])],
                    )
                ]
            ),
        )
        retained.append(item)
    payload = dict(
        kind="qualframe_reviewed_synthesis_v1",
        job_id=target.name,
        plan=plan,
        execution=json.loads((target / "execution.json").read_text(encoding="utf-8")),
        model_response_hashes=status["response_hashes"],
        reviewed_statements=retained,
        rejected_statement_ids=rejected,
        review_actions=list(actions.values()),
        review_history=_read_jsonl(target / "review_actions.jsonl"),
    )
    path = target / f"reviewed-synthesis-{snapshot_identity(payload)}.json"
    if not path.exists():
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
    elif snapshot_identity(json.loads(path.read_text(encoding="utf-8"))) != snapshot_identity(
        payload
    ):
        raise ValueError("Stored reviewed synthesis export has changed.")
    return path
