"""Prepare immutable reviewed-evidence synthesis inputs; no provider dispatch."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from qualframe.io.files import sha256_for_file
from qualframe.reviewed_analysis import load_snapshot, snapshot_freshness, snapshot_identity

PROMPT_PATH = "prompts/directed/synthesis/v1/reviewed_scope.md"


def build_synthesis_plan(
    repo_root: Path,
    run_root: Path,
    review_root: Path,
    snapshot_path: Path,
    grouping: str,
    *,
    project_path: Path | None = None,
    metadata_field: str | None = None,
    metadata_values: list[str] | None = None,
    missing_policy: str = "error",
) -> dict:
    if grouping not in {"per_transcript", "selected_cohort", "metadata"}:
        raise ValueError("Choose per-transcript, selected-cohort, or metadata summary scopes.")
    if snapshot_path.resolve().parent != (run_root / "analysis").resolve():
        raise ValueError("Select a snapshot from this run.")
    snapshot = load_snapshot(snapshot_path)
    fresh, reason = snapshot_freshness(snapshot, repo_root, run_root, review_root)
    if not fresh:
        raise ValueError("Freeze current reviewed evidence before planning synthesis: " + reason)
    payload = snapshot["payload"]
    if not payload["evidence"]:
        raise ValueError("Synthesis requires at least one retained evidence passage.")
    metadata_grouping = None
    source_scopes = {}
    metadata_group_ids = {}
    if grouping == "metadata":
        from qualframe.metadata_synthesis import freeze_metadata_grouping, read_metadata_catalog

        if project_path is None:
            raise ValueError("Metadata synthesis needs the current study manifest.")
        catalog = read_metadata_catalog(project_path, payload["source_paths"])
        if catalog["project_id"] != payload["project_id"]:
            raise ValueError("Metadata belongs to another study.")
        metadata_grouping = freeze_metadata_grouping(
            catalog, metadata_field or "", values=metadata_values, missing_policy=missing_policy
        )
        for group in metadata_grouping["groups"]:
            # Group identities separate a literal '[missing value]' from missing data.
            scope = group["group_id"]
            metadata_group_ids[scope] = group
            source_scopes.update({source: scope for source in group["source_paths"]})
    groups = {}
    for item in payload["evidence"]:
        source = item["source_path"].replace(chr(92), "/")
        if grouping == "metadata" and source not in source_scopes:
            continue
        scope = (
            source_scopes[source]
            if grouping == "metadata"
            else source
            if grouping == "per_transcript"
            else "Selected cohort"
        )
        groups.setdefault(scope, []).append(
            dict(
                evidence_id=item["record_id"],
                code_id=item["code_id"],
                source_path=source,
                source_sha256=item["source_sha256"],
                start=item["span"]["start_offset"],
                end=item["span"]["end_offset"],
                exact_text=item["span"]["exact_text"],
            )
        )
    if not groups:
        raise ValueError(
            "The selected metadata scopes need at least one retained evidence passage."
        )
    prompt = repo_root / PROMPT_PATH
    calls = []
    for scope, evidence in sorted(groups.items()):
        codes = {item["code_id"] for item in evidence}
        data = dict(
            scope=scope,
            source_paths=sorted({item["source_path"] for item in evidence}),
            codes=[code for code in payload["codebook"]["codes"] if code["id"] in codes],
            evidence=evidence,
        )
        if metadata_grouping:
            group = metadata_group_ids[scope]
            data["scope"] = group["label"]
            data["metadata_scope"] = group["definition"]
            data["source_paths"] = group["source_paths"]
            data["sources_without_retained_evidence"] = sorted(
                set(group["source_paths"]) - {item["source_path"] for item in evidence}
            )
            calls.append(dict(group_id=scope, input=data))
        else:
            calls.append(dict(group_id=snapshot_identity(dict(scope=scope))[:16], input=data))
    plan = dict(
        kind="qualframe_synthesis_plan_v1",
        status="prepared_only",
        project_id=payload["project_id"],
        run_id=payload["run_id"],
        snapshot_id=snapshot["snapshot_id"],
        grouping=grouping,
        included_sources=payload["source_paths"],
        excluded_sources=payload.get("excluded_source_paths", []),
        sources_without_retained_evidence=sorted(
            set(payload["source_paths"])
            - {e["source_path"].replace(chr(92), "/") for e in payload["evidence"]}
        ),
        prompt_path=PROMPT_PATH,
        prompt_sha256=sha256_for_file(prompt),
        prompt_text=prompt.read_text(encoding="utf-8"),
        calls=calls,
        execution_status=(
            "No requests sent. Provider, budget, approval and execution are separate future steps."
        ),
    )
    if metadata_grouping:
        plan["kind"] = "qualframe_synthesis_plan_v2"
        plan["metadata_grouping"] = metadata_grouping
        plan["codebook"] = payload["codebook"]
        plan["snapshot_source_paths"] = payload["source_paths"]
        plan["included_sources"] = sorted(source_scopes)
        plan["excluded_sources"] = sorted(
            set(payload.get("excluded_source_paths", []))
            | {row["source_path"] for row in metadata_grouping["excluded_sources"]}
        )
        plan["sources_without_retained_evidence"] = sorted(
            set(source_scopes)
            - {item["source_path"].replace(chr(92), "/") for item in payload["evidence"]}
        )
        plan["execution_status"] = (
            "Prepared inputs only. Provider execution requires separate approval."
        )
    return plan


def write_synthesis_plan(
    repo_root: Path,
    run_root: Path,
    review_root: Path,
    snapshot_path: Path,
    grouping: str,
    *,
    dry_run: bool = False,
    project_path: Path | None = None,
    metadata_field: str | None = None,
    metadata_values: list[str] | None = None,
    missing_policy: str = "error",
) -> Path:
    plan = build_synthesis_plan(
        repo_root,
        run_root,
        review_root,
        snapshot_path,
        grouping,
        project_path=project_path,
        metadata_field=metadata_field,
        metadata_values=metadata_values,
        missing_policy=missing_policy,
    )
    identity = snapshot_identity(plan)
    path = run_root / "analysis" / f"synthesis-plan-{identity}.json"
    if not dry_run:
        if path.exists():
            if snapshot_identity(json.loads(path.read_text(encoding="utf-8"))) != identity:
                raise ValueError("Stored synthesis plan content has changed.")
        else:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(plan, handle, indent=2, ensure_ascii=False)
    return path


class SynthesisStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class CodeSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code_id: str
    statements: list[SynthesisStatement]


class SynthesisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summaries: list[CodeSynthesis]


def validate_synthesis_response(plan: dict, group_id: str, response: dict) -> SynthesisResponse:
    """Check citation membership only; human review must assess meaning/support."""
    call = next((c for c in plan["calls"] if c["group_id"] == group_id), None)
    if call is None:
        raise ValueError("Unknown synthesis scope.")
    evidence = {e["evidence_id"]: e for e in call["input"]["evidence"]}
    codes = {e["code_id"] for e in evidence.values()}
    parsed = SynthesisResponse.model_validate(response)
    if len({s.code_id for s in parsed.summaries}) != len(parsed.summaries):
        raise ValueError("Duplicate code summaries.")
    for summary in parsed.summaries:
        if summary.code_id not in codes:
            raise ValueError("Summary code is absent from the reviewed scope.")
        for statement in summary.statements:
            for identity in statement.evidence_ids:
                if identity not in evidence or evidence[identity]["code_id"] != summary.code_id:
                    raise ValueError(
                        "A synthesis citation falls outside its reviewed code or scope."
                    )
    return parsed
