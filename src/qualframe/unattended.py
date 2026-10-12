"""Coding runs from the command line, for scripts and for assistants that run studies unattended.

The same rules apply as in the app: the study's spending limit, a recorded approval for each
spending step, one attempt per request, and a researcher's answer before anything that may have
been charged is retried. What differs is that approvals can be given in advance, on the record,
up to an amount the researcher names.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

import yaml

from qualframe.config import load_project_manifest, resolve_repo_path
from qualframe.configuration_lock import create_configuration_lock, run_can_resume
from qualframe.cost_control import CostApprovalRequired, append_cost_approval, approved_cost_thresholds
from qualframe.models import RunPlan
from qualframe.pipeline.project_runner import ProjectRunner


class RunStopped(RuntimeError):
    """A run stopped before finishing; ``status`` says why (for exit codes and summaries)."""

    def __init__(self, status: str, message: str, summary: dict):
        super().__init__(message)
        self.status = status
        self.summary = summary


def _presets(app_root: Path) -> dict[str, dict]:
    data = yaml.safe_load((app_root / "config/model_presets.yaml").read_text(encoding="utf-8")) or {}
    return {p["id"]: dict(p, checked_on=data.get("checked_on")) for p in data.get("presets", [])}


def choose_model(project_path: Path, preset_id: str, *, actor: str, rationale: str, app_root: Path,
                 max_tokens: int | None = None, spending_limit: float | None = None) -> bool:
    """Set the study's model from a preset. Returns False when it was already set that way."""
    from qualframe.provider_setup import ProviderSetup, save_provider_setup
    from qualframe.study_setup import StudyWorkspace

    presets = _presets(app_root)
    if preset_id not in presets:
        raise ValueError(f"Unknown model preset {preset_id!r}. Choose one of: {', '.join(sorted(presets))}.")
    preset = presets[preset_id]
    if preset["provider"] not in {"openai", "anthropic", "openai_compatible"}:
        raise ValueError("Choose a hosted or local model preset.")
    project = load_project_manifest(project_path)
    runner = ProjectRunner(project_path)
    current_limit = None
    try:
        cost = runner._build_cost_controller(run_id="settings", artifact_root=project_path.parent / "artifacts")
        current_limit = cost.policy.absolute_limit_usd if cost else None
    except (ValueError, OSError):
        cost = None
    wanted_tokens = int(max_tokens or preset.get("max_tokens") or 16000)
    wanted_limit = float(spending_limit or current_limit or 5)
    provider = project.provider
    if (cost is not None and provider.name == preset["provider"] and provider.model == preset["model"]
            and provider.max_tokens == wanted_tokens and current_limit == wanted_limit
            and provider.reasoning_effort == preset.get("reasoning_effort")
            and provider.anthropic_effort == preset.get("anthropic_effort")):
        return False
    setup = ProviderSetup(
        provider=preset["provider"], model=preset["model"], max_tokens=wanted_tokens,
        temperature=preset.get("temperature"), api_mode=preset.get("api_mode") or "chat_completions",
        reasoning_effort=preset.get("reasoning_effort"), anthropic_effort=preset.get("anthropic_effort"),
        absolute_limit_usd=wanted_limit, input_rate=float(preset.get("input_rate") or 0),
        output_rate=float(preset.get("output_rate") or 0),
        pricing_date=date.fromisoformat(str(preset.get("checked_on") or date.today().isoformat())),
        pricing_source=preset.get("pricing_source") or "", governance_confirmed=True,
        base_url=preset.get("base_url"))
    workspace = StudyWorkspace(project_path.parents[2])
    save_provider_setup(workspace, project_path, setup, actor=actor, rationale=rationale, use_environment_key=True)
    return True


def resolve_sample(runner: ProjectRunner, names: list[str]) -> list[str]:
    """Workspace-relative paths for the transcripts named (file name, name without extension, or ID such as 5A)."""
    from qualframe.reference_coding import match_document

    transcripts = runner._transcript_files()
    chosen, missing = [], []
    for name in names:
        group, _, rest = name.replace("\\", "/").rpartition("/")
        pool = [t for t in transcripts if not group or t.parent.name.casefold() == group.casefold()]
        found = match_document(rest or name, pool)
        if found is None:
            missing.append(name)
        else:
            chosen.append(found.relative_to(runner.repo_root).as_posix())
    if missing:
        raise ValueError("No single transcript matches: " + ", ".join(missing) + ". Use a file name or an ID such as BC/5A.")
    return sorted(set(chosen))


def preapprove_spending(project_path: Path, *, up_to: float, actor: str, rationale: str, run_id: str) -> list[float]:
    """Record approvals for every spending step up to ``up_to`` that isn't approved yet."""
    runner = ProjectRunner(project_path)
    cost = runner._build_cost_controller(run_id=run_id, artifact_root=project_path.parent / "artifacts" / run_id)
    if cost is None:
        raise ValueError("Set a model and spending limit first.")
    if up_to > cost.policy.absolute_limit_usd:
        raise ValueError(f"The study's spending limit is ${cost.policy.absolute_limit_usd:.2f}; approve up to that at most.")
    approved = approved_cost_thresholds(cost.approvals_path, cost.project_id)
    step, recorded = cost.policy.approval_increment_usd, []
    threshold = step
    while threshold <= up_to + 1e-9:
        value = round(threshold, 8)
        if value not in approved:
            append_cost_approval(cost.approvals_path, project_id=cost.project_id, run_id=run_id, threshold_usd=value,
                                 decision="approve", reviewer=actor, rationale=rationale)
            recorded.append(value)
        threshold += step
    return recorded


def _record_execution_approval(run_root: Path, *, actor: str, rationale: str, fingerprint: str, limit: float) -> None:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / f"execution-approval-{uuid.uuid4().hex}.json").write_text(json.dumps({
        "actor": actor, "rationale": rationale, "configuration_fingerprint": fingerprint,
        "absolute_limit_usd": limit, "governance_confirmed": True, "interface": "command line",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_root.name}, indent=2), encoding="utf-8")


_HEARTBEAT_INTERVAL_SECONDS = 30.0
_HEARTBEAT_FRESH_SECONDS = 120.0


def _heartbeat_is_fresh(run_root: Path) -> bool:
    """Malformed, future-dated, or old heartbeat files do not establish a live run."""
    try:
        data = json.loads((run_root / "heartbeat.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return False
        pid = data.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return False
        stamp = datetime.fromisoformat(data["timestamp_utc"])
        if stamp.tzinfo is None:
            return False
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return 0 <= age < _HEARTBEAT_FRESH_SECONDS
    except (OSError, ValueError, TypeError, KeyError):
        return False


def _write_heartbeat(run_root: Path) -> None:
    # Readers see either complete version, never a partially written timestamp.
    temporary = run_root / f".heartbeat-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(json.dumps({
            "pid": os.getpid(), "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        temporary.replace(run_root / "heartbeat.json")
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _run_lock(run_root: Path, message: str) -> Iterator[None]:
    """Serialize execution and reconciliation; the OS releases this lock on process death."""
    handle = (run_root / "execution.lock").open("a+b")
    try:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError(message) from exc
        yield
    finally:
        # Keep the file: deleting a lock file can let other workers lock different inodes.
        handle.close()


@contextmanager
def _live_progress(project_path: Path, run_id: str, run_root: Path,
                   say: Callable[[str], None], every_seconds: float) -> Iterator[None]:
    stop = threading.Event()
    _write_heartbeat(run_root)

    def report() -> None:
        next_report = time.monotonic() + every_seconds
        while not stop.wait(min(_HEARTBEAT_INTERVAL_SECONDS, max(0.001, next_report - time.monotonic()))):
            try:
                _write_heartbeat(run_root)
                if time.monotonic() >= next_report:
                    next_report = time.monotonic() + every_seconds
                    s = run_status(project_path, run_id)
                    say(f"{datetime.now().strftime('%H:%M')} {s['transcripts_done']}/{s['transcripts_planned']} transcripts, "
                        f"{s['requests_recorded']} requests, ${s['run_cost_usd']:.2f} this run, study ${s['study_spend_usd']}")
            except (OSError, ValueError):
                continue

    reporter = threading.Thread(target=report, daemon=True)
    try:
        reporter.start()
        yield
    finally:
        stop.set()
        if reporter.ident is not None:
            reporter.join()
        (run_root / "heartbeat.json").unlink(missing_ok=True)


def run_status(project_path: Path, run_id: str) -> dict:
    """Where a run stands, from its files: transcripts done, requests, cost, and anything waiting on a person."""
    project = load_project_manifest(project_path)
    repo_root = project_path.parents[2]
    run_root = resolve_repo_path(repo_root, project.paths["artifacts"]) / run_id
    if not (run_root / "run_plan.json").exists():
        raise ValueError(f"No run {run_id} in this study.")
    plan = RunPlan.model_validate_json((run_root / "run_plan.json").read_text(encoding="utf-8"))
    transcripts = len([i for i in plan.discovered_inputs if i.kind == "transcript"])
    done = len(list(run_root.glob("*/*_artifact.json")))
    settings = json.loads((run_root / "run_settings.json").read_text(encoding="utf-8")) if (run_root / "run_settings.json").exists() else {}
    ledger = project_path.parent / "logs/cost_ledger.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()] if ledger.exists() else []
    mine = {row["request_id"]: row for row in rows if row.get("run_id") == run_id}
    runner = ProjectRunner(project_path)
    unresolved = []
    try:
        cost = runner._build_cost_controller(run_id=run_id, artifact_root=run_root)
        unresolved = [dict(request_id=r["request_id"], run_id=r.get("run_id"), input_label=r.get("input_label"),
                           most_it_could_cost_usd=r.get("estimated_cost_usd")) for r in cost.unresolved_requests()
                      if r.get("run_id") == run_id] if cost else []
        study_spend = cost.project_cost_usd() if cost else None
        limit = cost.policy.absolute_limit_usd if cost else None
    except (ValueError, OSError):
        study_spend = limit = None
    manifest = run_root / "run_manifest.json"
    pause = run_root / "cost_pause.json"
    running = _heartbeat_is_fresh(run_root)
    if running:
        status = "running"
    elif unresolved:
        status = "failed_request_needs_confirmation"
    elif manifest.exists():
        status = json.loads(manifest.read_text(encoding="utf-8")).get("status", "completed")
    elif pause.exists():
        threshold = json.loads(pause.read_text(encoding="utf-8")).get("threshold_usd")
        approved = approved_cost_thresholds(project_path.parent / "logs/cost_approvals.jsonl", project.project_id)
        status = "stopped" if threshold is not None and round(threshold, 8) in approved else "paused_for_spending_check"
    else:
        status = "stopped"
    return dict(
        run_id=run_id, status=status, model=(settings.get("provider") or {}).get("model"),
        transcripts_done=done, transcripts_planned=transcripts,
        requests_recorded=len(list((run_root / "requests").glob("*.json"))),
        run_cost_usd=round(sum(float(r.get("calculated_cost_usd") or 0) for r in mine.values()), 4),
        study_spend_usd=round(study_spend, 2) if study_spend is not None else None, spending_limit_usd=limit,
        sample=plan.transcript_sample, unresolved_requests=[] if running else unresolved,
        in_flight_requests=unresolved if running else [],
        review_ready=(run_root / "evidence_review/index.json").exists(),
    )


def execute(project_path: Path, run_id: str, *, actor: str, rationale: str, approve_up_to: float | None = None,
            say: Callable[[str], None] = print, every_seconds: float = 60.0) -> dict:
    """Run (or resume) a saved run plan to the end, reporting progress. Raises RunStopped if it stops."""
    from qualframe.evidence_review import write_evidence_review_index

    project_path = project_path.resolve()
    runner = ProjectRunner(project_path)
    run_root = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"]) / run_id
    plan = RunPlan.model_validate_json((run_root / "run_plan.json").read_text(encoding="utf-8"))
    current = create_configuration_lock(project_path).fingerprint_sha256
    if current != plan.configuration_fingerprint and not run_can_resume(project_path, run_root, plan.configuration_fingerprint):
        raise ValueError("The study's coding settings changed since this run was planned (model, instructions, codebook "
                         "or options). Start a new run instead.")
    if not math.isfinite(every_seconds) or every_seconds <= 0:
        raise ValueError("The progress interval must be a positive, finite number of seconds.")
    with _run_lock(run_root, "This run is already running. Wait for it to stop before resuming."):
        if _heartbeat_is_fresh(run_root):
            raise ValueError("This run is already running. Wait for its heartbeat to expire before resuming.")
        cost = runner._build_cost_controller(run_id=run_id, artifact_root=run_root)
        if cost is None and runner.project.provider.name not in {"mock", "cached_demo", "recorded"}:
            raise ValueError("Set a model and spending limit first.")
        # The spending safeguard remains study-wide, even though status describes one run.
        if cost is not None and cost.unresolved_requests():
            raise RunStopped("failed_request_needs_confirmation",
                             "An earlier request failed and may have been charged. Confirm it first (qualframe confirm-request).",
                             run_status(project_path, run_id))
        if approve_up_to:
            steps = preapprove_spending(project_path, up_to=approve_up_to, actor=actor, rationale=rationale, run_id=run_id)
            if steps:
                say("Approved spending steps in advance: " + ", ".join(f"${s:,.0f}" for s in steps))
        _record_execution_approval(run_root, actor=actor, rationale=rationale, fingerprint=plan.configuration_fingerprint or "",
                                   limit=cost.policy.absolute_limit_usd if cost else 0)
        try:
            with _live_progress(project_path, run_id, run_root, say, every_seconds):
                runner.execute_run_plan(plan, run_id)
                write_evidence_review_index(project_manifest_path=project_path, run_id=run_id)
        except CostApprovalRequired as exc:
            summary = run_status(project_path, run_id)
            summary["status"] = "paused_for_spending_check"
            raise RunStopped("paused_for_spending_check",
                             f"Paused before passing the ${exc.pause.threshold_usd:,.0f} spending step. Approve further "
                             "spending (resume with --approve-up-to) to continue.", summary) from exc
        except Exception as exc:
            summary = run_status(project_path, run_id)
            kind = "failed_request_needs_confirmation" if summary["unresolved_requests"] else "failed"
            summary["status"] = kind
            raise RunStopped(kind, str(exc), summary) from exc
        return run_status(project_path, run_id)


def start(project_path: Path, *, actor: str, rationale: str, sample: list[str] | None = None,
          approve_up_to: float | None = None, say: Callable[[str], None] = print, every_seconds: float = 60.0) -> dict:
    """Plan a new run (all transcripts, or a sample) with the study's current model, and run it."""
    project_path = project_path.resolve()
    runner = ProjectRunner(project_path)
    if sample:
        runner.transcript_sample = set(resolve_sample(runner, sample))
    plan = runner.build_run_plan()
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    artifacts.mkdir(parents=True, exist_ok=True)
    run_id = runner._make_run_id()
    while True:
        try:
            (artifacts / run_id).mkdir()
            break
        except FileExistsError:
            run_id = f"{runner._make_run_id()}-{uuid.uuid4().hex[:8]}"
    runner.save_run_plan(plan, run_id)
    count = len([i for i in plan.discovered_inputs if i.kind == "transcript"])
    say(f"Run {run_id}: {runner.project.provider.model} on {count} transcript{'s' if count != 1 else ''}.")
    return execute(project_path, run_id, actor=actor, rationale=rationale, approve_up_to=approve_up_to,
                   say=say, every_seconds=every_seconds)


def confirm_request(project_path: Path, request_id: str, *, charged: str, actor: str, note: str = "",
                    input_tokens: int = 0, output_tokens: int = 0) -> float:
    """Record whether a failed request was charged: "no", "yes" (with tokens) or "maximum" (its most possible cost)."""
    from qualframe.providers.base import LLMUsage

    runner = ProjectRunner(project_path)
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    cost = runner._build_cost_controller(run_id="reconciliation", artifact_root=artifacts)
    row = next((r for r in cost.unresolved_requests() if r["request_id"] == request_id), None) if cost else None
    if row is None:
        raise ValueError("That request has already been confirmed, or isn't part of this study.")
    run_root = artifacts / str(row.get("run_id"))
    refusal = "Cannot confirm a request while its run is running. Wait for the run to stop first."
    with _run_lock(run_root, refusal):
        if _heartbeat_is_fresh(run_root):
            raise ValueError(refusal)
        record_path = run_root / "requests" / f"{request_id}.json"
        record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
        error = str(record.get("error_message") or record.get("error_type") or "not recorded")[:300]
        if charged == "no":
            usage = LLMUsage()
            rationale = "Researcher confirmed the provider did not charge: the request failed before any output."
            evidence = f"Researcher confirmation. Request record requests/{request_id}.json: {error}."
        elif charged == "yes":
            if input_tokens + output_tokens <= 0:
                raise ValueError("Give the input and output tokens shown on the provider's usage page.")
            usage = LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens)
            rationale = "Researcher reported the provider charged for this failed request."
            evidence = "Token counts entered from the provider's usage page."
        elif charged == "maximum":
            rate = float(row["pricing"]["output_per_million_usd"]) or 1.0
            usage = LLMUsage(output_tokens=math.ceil(float(row["estimated_cost_usd"]) * 1_000_000 / rate))
            rationale = "Not known whether the provider charged; the most the request could have cost is recorded."
            evidence = f"Researcher's choice to count the maximum. Request record requests/{request_id}.json: {error}."
        else:
            raise ValueError('Say whether it was charged: "no", "yes" (with tokens) or "maximum".')
        if note:
            rationale += " Note: " + note
        saved = cost.reconcile_request(request_id=request_id, usage=usage, reviewer=actor, rationale=rationale,
                                       evidence_reference=evidence)
        return saved.calculated_cost_usd
