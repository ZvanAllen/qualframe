"""Cost-gated synthesis jobs from current immutable reviewed evidence."""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from pathlib import Path

from qualframe.config import resolve_repo_path
from qualframe.cost_control import CostLimitExceeded, utc_now
from qualframe.io.files import sha256_for_file
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers import build_provider
from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage
from qualframe.reviewed_analysis import load_snapshot, snapshot_freshness, snapshot_identity
from qualframe.synthesis_plan import build_synthesis_plan, validate_synthesis_response


def read_plan(run_root: Path, plan_id: str) -> dict:
    if len(plan_id) != 64 or any(c not in "0123456789abcdef" for c in plan_id):
        raise ValueError("Select an existing synthesis plan.")
    path = run_root / "analysis" / f"synthesis-plan-{plan_id}.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    if snapshot_identity(plan) != plan_id:
        raise ValueError("Synthesis plan changed after preparation.")
    return plan


def current_plan(runner: ProjectRunner, run_root: Path, plan_id: str) -> dict:
    plan = read_plan(run_root, plan_id)
    if plan["project_id"] != runner.project.project_id or plan["run_id"] != run_root.name:
        raise ValueError("Synthesis plan belongs to another study or coding run.")
    snapshot = load_snapshot(run_root / "analysis" / f"snapshot-{plan['snapshot_id']}.json")
    review = (
        resolve_repo_path(runner.repo_root, runner.project.paths["review_queue"]) / run_root.name
    )
    fresh, reason = snapshot_freshness(snapshot, runner.repo_root, run_root, review)
    if not fresh:
        raise ValueError("Synthesis inputs are stale: " + reason)
    metadata = plan.get("metadata_grouping")
    options = dict(project_path=runner.project_manifest_path,
        metadata_field=metadata["field"], metadata_values=metadata["selected_values"],
        missing_policy=metadata["missing_policy"]) if metadata else {}
    expected = build_synthesis_plan(
        runner.repo_root,
        run_root,
        review,
        run_root / "analysis" / f"snapshot-{plan['snapshot_id']}.json",
        plan["grouping"],
        **options,
    )
    if plan != expected:
        raise ValueError("Prepared synthesis content differs from its reviewed snapshot or prompt.")
    return plan


def synthesis_preflight(runner: ProjectRunner, run_root: Path, plan_id: str) -> dict:
    """Read-only configuration and cost preview, without reservations or requests."""
    plan = current_plan(runner, run_root, plan_id)
    schema = json.loads(
        (runner.repo_root / "config/schemas/reviewed_synthesis_v1.json").read_text(encoding="utf-8")
    )
    provider = runner.project.provider
    if provider.name not in {"mock", "openai", "anthropic"}:
        raise ValueError("Synthesis supports OpenAI, Anthropic, or synthetic mock execution.")
    if provider.name == "mock" and runner.project.data_classification != "synthetic":
        raise ValueError("The synthesis mock is available for synthetic studies only.")
    cost = runner._build_cost_controller(
        run_id="synthesis-preflight", artifact_root=run_root / "analysis"
    )
    if provider.name != "mock" and cost is None:
        raise ValueError("Configure provider pricing and an absolute spending ceiling first.")
    if cost and cost.unresolved_requests():
        raise ValueError("Prior request usage is unresolved; reconcile it before synthesis.")
    estimate = (
        sum(
            cost.estimate_usd(
                system_prompt=plan["prompt_text"] + json.dumps(schema),
                user_prompt=json.dumps(call["input"], ensure_ascii=False),
            )
            for call in plan["calls"]
        )
        if cost
        else 0.0
    )
    spent = cost.project_cost_usd() if cost else 0.0
    if cost and spent + estimate > cost.policy.absolute_limit_usd:
        raise CostLimitExceeded("The planned synthesis exceeds the remaining study ceiling.")
    return dict(
        plan_id=plan_id,
        response_schema=schema,
        response_schema_sha256=snapshot_identity(schema),
        configuration_fingerprint=runner.configuration_lock.fingerprint_sha256,
        provider=provider.model_dump(mode="json"),
        call_count=len(plan["calls"]),
        estimated_cost_usd=round(estimate, 8),
        spent_usd=spent,
        absolute_limit_usd=cost.policy.absolute_limit_usd if cost else 0,
        pricing=cost.snapshot.model_dump(mode="json") if cost else None,
        cost_policy=cost.policy.model_dump(mode="json") if cost else None,
    )


class SyntheticSynthesisProvider(LLMProvider):
    name = "mock"

    def complete(
        self, *, system_prompt: str, user_prompt: str, attachments=None, response_schema=None
    ) -> LLMResponse:
        data = json.loads(user_prompt)
        grouped = {}
        for item in data["evidence"]:
            grouped.setdefault(item["code_id"], []).append(
                dict(
                    text="Reviewed passage: " + item["exact_text"],
                    evidence_ids=[item["evidence_id"]],
                )
            )
        return LLMResponse(
            text=json.dumps(
                dict(summaries=[dict(code_id=k, statements=v) for k, v in grouped.items()])
            ),
            provider="mock",
            model="synthetic-synthesis-fixture",
            usage=LLMUsage(),
        )


def execute_synthesis(
    project_path: Path,
    run_root: Path,
    plan_id: str,
    *,
    fingerprint: str,
    actor: str,
    rationale: str,
    live_confirmed: bool = False,
    dry_run: bool = False,
    job_id: str | None = None,
) -> Path:
    runner = ProjectRunner(project_path)
    from qualframe.study_setup import StudyWorkspace

    StudyWorkspace(runner.repo_root).managed_study_root(project_path)
    expected = (
        resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"]) / run_root.name
    )
    if expected.resolve() != run_root.resolve():
        raise ValueError("Coding run belongs to another study.")
    preview = synthesis_preflight(runner, run_root, plan_id)
    if fingerprint != preview["configuration_fingerprint"]:
        raise ValueError("Configuration changed; review the synthesis preflight again.")
    if not actor.strip() or not rationale.strip():
        raise ValueError("Synthesis needs a researcher identity and approval rationale.")
    live = runner.project.provider.name != "mock"
    if live and not live_confirmed:
        raise ValueError("Confirm provider transfer and spending before synthesis.")
    if live and not os.getenv(runner.project.provider.api_key_env or ""):
        raise ValueError("Enter the configured API key for this app session.")
    identifier = job_id or "synthesis-" + uuid.uuid4().hex
    if (
        not identifier.startswith("synthesis-")
        or len(identifier) != 42
        or any(c not in "0123456789abcdef" for c in identifier[10:])
    ):
        raise ValueError("Invalid synthesis job identity.")
    target = run_root / "analysis" / "synthesis" / identifier
    if target.exists():
        raise ValueError("This synthesis job already exists. Outputs are never overwritten.")
    if dry_run:
        return target
    plan = current_plan(runner, run_root, plan_id)
    target.mkdir(parents=True)
    (target / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    config = dict(
        preview,
        actor=actor.strip(),
        rationale=rationale.strip(),
        live_confirmed=live_confirmed,
        created_at_utc=utc_now(),
    )
    (target / "execution.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    cost = runner._build_cost_controller(run_id=identifier, artifact_root=target)
    provider = build_provider(runner.project.provider) if live else SyntheticSynthesisProvider()
    status = dict(
        job_id=identifier,
        plan_id=plan_id,
        snapshot_id=plan["snapshot_id"],
        status="running",
        completed_groups=[],
        response_hashes={},
        execution_sha256=snapshot_identity(config),
        error=None,
    )
    records = []

    def save_status():
        status["cost_usd"] = cost.run_cost_usd() if cost else 0
        temporary = target / "status.pending.json"
        temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
        temporary.replace(target / "status.json")

    save_status()
    try:
        for call in plan["calls"]:
            # Recheck reviewed inputs and configuration between requests.
            fresh_runner = ProjectRunner(project_path)
            if fresh_runner.configuration_lock.fingerprint_sha256 != fingerprint:
                raise ValueError("Configuration changed during synthesis.")
            current_plan(fresh_runner, run_root, plan_id)
            request = dict(
                system_prompt=plan["prompt_text"],
                user_prompt=json.dumps(call["input"], ensure_ascii=False),
                response_schema=preview["response_schema"],
            )
            (target / f"{call['group_id']}-input.json").write_text(
                json.dumps(request, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            response = runner._complete(
                provider=provider,
                cost_controller=cost,
                stage_id="reviewed_synthesis",
                input_label=call["group_id"],
                **request,
            )
            (target / f"{call['group_id']}-response.json").write_text(
                json.dumps(dataclasses.asdict(response), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            response_path = target / f"{call['group_id']}-response.json"
            status["response_hashes"][response_path.name] = sha256_for_file(response_path)
            parsed = validate_synthesis_response(plan, call["group_id"], json.loads(response.text))
            for summary in parsed.summaries:
                for position, statement in enumerate(summary.statements):
                    item = dict(
                        group_id=call["group_id"],
                        code_id=summary.code_id,
                        position=position,
                        **statement.model_dump(),
                    )
                    item["statement_id"] = snapshot_identity(item)
                    records.append(item)
            status["completed_groups"].append(call["group_id"])
            save_status()
        bundle = dict(plan_id=plan_id, job_id=identifier, records=records)
        (target / "proposals.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        status["proposals_sha256"] = snapshot_identity(bundle)
        status["status"] = "awaiting_review" if records else "no_statements"
    except Exception as exc:
        status["status"] = "failed"
        status["error"] = f"{type(exc).__name__}: {exc}"
        save_status()
        raise
    save_status()
    return target
