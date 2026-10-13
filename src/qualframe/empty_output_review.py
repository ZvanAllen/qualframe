"""Explicit, append-only review of validated zero-proposal coding outputs."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.response_parser import parse_decisions_json, strict_empty_tables
from qualframe.io.transcript_io import transcript_to_text


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key(path: str) -> str:
    return path.replace("\\", "/")


def _within(root: Path, relative: str) -> Path:
    target = (root / _key(relative)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Review input leaves its study boundary.")
    return target


def _digest(value: dict) -> str:
    return sha256_for_text(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _required_headers(repo_root: Path, run_root: Path, stage: str, *, all_empty: bool) -> list[str]:
    lock = _read(run_root / "analysis_configuration_lock.json")
    headers: list[str] = []
    for kind in ("framework", "structured_output_schema"):
        for asset in lock.get("assets", []):
            if asset.get("kind") != kind:
                continue
            path = _within(repo_root, asset["path"])
            if sha256_for_file(path) != asset["sha256"]:
                raise ValueError(
                    "The frozen output contract changed; restore its version before review."
                )
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if kind == "framework":
                headers = data.get("required_columns", [])
            elif stage in data.get("stages", {}):
                rule = data["stages"][stage]
                if all_empty and rule.get("require_rows", True):
                    raise ValueError(
                        "This frozen output contract requires coding rows; "
                        "an empty table needs a new coding run."
                    )
                headers = rule.get("required_columns", [])
    if not headers:
        raise ValueError("A frozen output column contract is needed to validate an empty table.")
    return headers


def _uses_decisions_contract(repo_root: Path, run_root: Path) -> bool:
    """Read the locked method; an arbitrary JSON object cannot change its contract."""
    lock = _read(run_root / "analysis_configuration_lock.json")
    for asset in lock.get("assets", []):
        if asset.get("kind") != "method":
            continue
        path = _within(repo_root, asset["path"])
        if sha256_for_file(path) != asset["sha256"]:
            raise ValueError("The frozen method changed; restore its version before review.")
        method = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return method.get("coding", {}).get("decision_style", "find_passages") == "decide_each_code"
    return False


def _is_empty_codings(raw: str) -> bool:
    # A valid JSON answer with an empty codings list is an explicit "nothing fits" for that scope.
    from qualframe.io.response_parser import parse_coding_json

    try:
        return parse_coding_json(raw) == {"Directed Coding": []}
    except ValueError:
        return False


def _is_empty_decisions(raw: str) -> bool:
    # A valid empty decision array is an audited omission, never a claim of absence.
    return parse_decisions_json(raw) == {"Directed Coding": []}


def empty_table_issue(
    repo_root: Path | None, run_root: Path, calls: list[dict], outputs: list[dict]
) -> str:
    """Return a blocking issue for empty sheets lacking explicit valid raw tables.

    Existing CFIR artifacts may contain [] for entirely unparsed responses.
    Those entries are never treated as successful empty output. Multi-request
    output is checked against each frozen partition/domain response separately.
    """
    if not any(
        any(not rows for rows in (output.get("parsed_output") or {}).values()) for output in outputs
    ):
        return ""
    if repo_root is None:
        return "Empty output requires its frozen source and output contract for validation."
    try:
        decisions_contract = _uses_decisions_contract(repo_root, run_root)
        headers = set() if decisions_contract else set(
            _required_headers(
                repo_root,
                run_root,
                calls[0]["stage_id"],
                all_empty=all(not any((o.get("parsed_output") or {}).values()) for o in outputs),
            )
        )
        domains = [call["domain"] for call in calls if call.get("domain")]
        for output in outputs:
            parsed = output.get("parsed_output") or {}
            empty = [sheet for sheet, rows in parsed.items() if not rows]
            if not empty:
                continue
            raw = output.get("response_text", "")
            if len(calls) > 1 and len(outputs) == 1:
                if any(
                    not any(sheet == d or sheet.startswith(d + ": ") for d in domains)
                    for sheet in empty
                ):
                    raise ValueError("An empty sheet is not linked to a frozen coding scope.")
                marker = "Partition: " if "## Partition: " in raw else "Sheet: "
                # Only outer headings declared by the frozen request plan split
                # responses; incidental headings cannot satisfy a missing call.
                pattern = re.compile(
                    r"^## "
                    + re.escape(marker)
                    + "("
                    + "|".join(re.escape(d) for d in domains)
                    + r")\s*$",
                    re.MULTILINE,
                )
                matches = list(pattern.finditer(raw))
                sections: dict[str, str] = {}
                for i, match in enumerate(matches):
                    name = match.group(1)
                    content = raw[
                        match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(raw)
                    ]
                    # CFIR sometimes repeats its wrapper heading inside a response.
                    if name in sections and sections[name].strip():
                        raise ValueError(
                            "Duplicate coding scopes make this empty response ambiguous."
                        )
                    sections[name] = content
                for domain in domains:
                    if not any(
                        sheet == domain or sheet.startswith(domain + ": ") for sheet in empty
                    ):
                        continue
                    if decisions_contract:
                        if not _is_empty_decisions(sections.get(domain, "")) or not output.get("no_decisions", {}).get(domain):
                            raise ValueError(
                                "An empty decision scope needs a valid decisions array and its missing-code audit."
                            )
                        continue
                    if _is_empty_codings(sections.get(domain, "")):
                        continue
                    tables = strict_empty_tables(sections.get(domain, ""))
                    if len(tables) != 1 or not headers <= set(tables[0]["headers"]):
                        raise ValueError(
                            "A coding scope has missing, malformed, or unparsed output; "
                            "it cannot be confirmed empty."
                        )
            else:
                if decisions_contract:
                    if len(empty) != 1 or any(parsed.values()) or not _is_empty_decisions(raw) or not any(output.get("no_decisions", {}).values()):
                        raise ValueError(
                            "An empty decision response needs a valid decisions array and its missing-code audit."
                        )
                    continue
                if len(empty) == 1 and not any(parsed.values()) and _is_empty_codings(raw):
                    continue
                tables = strict_empty_tables(raw)
                if len(tables) != len(empty) or any(
                    not headers <= set(t["headers"]) for t in tables
                ):
                    raise ValueError(
                        "Empty output does not contain a complete header-only table "
                        "matching the frozen columns."
                    )
                if any(parsed.values()):
                    raise ValueError(
                        "Mixed populated and empty tables need a separately validated coding scope."
                    )
        return ""
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return str(exc)


def empty_output_binding(
    repo_root: Path, run_root: Path, source: dict, stage: str, outputs: list[dict]
) -> dict:
    path = _within(repo_root, source["path"])
    if sha256_for_file(path) != source["sha256"]:
        raise ValueError(
            "The source changed since coding. Restore the original or create a new run."
        )
    manifest = _read(run_root / "run_manifest.json")
    return {
        "kind": "qualframe_empty_output_binding_v1",
        "project_id": manifest["project_id"],
        "run_id": manifest["run_id"],
        "source_path": _key(source["path"]),
        "source_sha256": source["sha256"],
        "source_text_sha256": sha256_for_text(transcript_to_text(path)),
        "stage_id": stage,
        "configuration_fingerprint": manifest.get("configuration_fingerprint"),
        "run_plan_sha256": sha256_for_file(run_root / "run_plan.json"),
        "review_index_sha256": sha256_for_file(run_root / "evidence_review/index.json"),
        "artifacts": [
            {
                "path": output["artifact_rel"],
                "sha256": sha256_for_file(_within(run_root, output["artifact_rel"])),
                "prompt_sha256": output.get("prompt_sha256"),
                "provider": output.get("provider"),
                "model": output.get("model"),
            }
            for output in sorted(outputs, key=lambda o: o["artifact_rel"])
        ],
    }


def load_empty_output_actions(review_root: Path) -> list[dict]:
    path = review_root / "empty_outputs/actions.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def latest_empty_output_action(review_root: Path, source_path: str) -> dict | None:
    return next(
        (
            action
            for action in reversed(load_empty_output_actions(review_root))
            if action.get("source_path") == _key(source_path)
        ),
        None,
    )


def empty_output_state(
    repo_root: Path, run_root: Path, review_root: Path, source_path: str
) -> dict:
    from qualframe.study_progress import transcript_progress

    row = next(
        (
            r
            for r in transcript_progress(run_root, review_root, [], repo_root)
            if r["path"] == _key(source_path)
        ),
        None,
    )
    if row is None:
        raise ValueError("Choose a transcript from the frozen run cohort.")
    return row


def append_empty_output_action(
    *,
    repo_root: Path,
    run_root: Path,
    review_root: Path,
    source_path: str,
    expected_binding: str,
    decision: str,
    reviewer: str,
    rationale: str,
    dry_run: bool = False,
) -> dict:
    if decision not in {"confirm_empty", "needs_recoding", "defer"}:
        raise ValueError("Choose confirm empty, needs recoding, or decide later.")
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("Enter the researcher name and reason for this source-level decision.")
    state = empty_output_state(repo_root, run_root, review_root, source_path)
    if not state.get("empty_eligible"):
        raise ValueError(
            state.get("empty_issue") or "This source is not ready for zero-proposal review."
        )
    binding = state["empty_binding"]
    digest = _digest(binding)
    if not expected_binding or digest != expected_binding:
        raise ValueError(
            "The source or coding inputs changed after this page opened. Refresh before deciding."
        )
    action = dict(
        action_id="empty-review-" + uuid4().hex,
        source_path=_key(source_path),
        binding_sha256=digest,
        binding=binding,
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    if not dry_run:
        path = review_root / "empty_outputs/actions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(action, ensure_ascii=False) + "\n")
    return action
