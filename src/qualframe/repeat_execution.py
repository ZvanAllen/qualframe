"""Bounded sequential coding repeats against one frozen configuration and cohort."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from qualframe.config import resolve_repo_path
from qualframe.cost_control import CostLimitExceeded, utc_now
from qualframe.evidence_review import write_evidence_review_index
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import RunPlan, StageArtifact
from qualframe.pipeline.project_runner import _API_SYSTEM_PROMPT, ProjectRunner
from qualframe.prompts import get_prompt_text
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.study_setup import StudyWorkspace


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def _save_status(root: Path, status: dict) -> None:
    temporary = root / "status.pending.json"
    temporary.write_text(json.dumps(status, indent=2), encoding="utf-8")
    temporary.replace(root / "status.json")


def _acquire_execution_lock(path: Path) -> BinaryIO:
    """OS-held lock releases on worker death, allowing an explicit safe resume."""
    handle = path.open("a+b")
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
        handle.close()
        raise ValueError("This repeated-coding experiment already has an active worker.") from exc
    return handle


def experiment_root(project_path: Path, experiment_id: str) -> Path:
    if not re.fullmatch(r"repeat-[0-9a-f]{32}", experiment_id):
        raise ValueError("Select a prepared repeated-coding experiment.")
    runner = ProjectRunner(project_path)
    study = StudyWorkspace(runner.repo_root).managed_study_root(project_path)
    return study / "experiments" / experiment_id


def read_repeat_plan(project_path: Path, experiment_id: str) -> dict:
    root = experiment_root(project_path, experiment_id)
    envelope = _read(root / "plan.json")
    plan = envelope["plan"]
    if snapshot_identity(plan) != envelope["plan_id"] or plan["experiment_id"] != experiment_id:
        raise ValueError("The frozen repeated-coding plan was modified.")
    count = plan.get("repeat_count")
    expected_ids = (
        [f"{experiment_id}-{n:02d}" for n in range(1, count + 1)]
        if isinstance(count, int) and 2 <= count <= 10
        else []
    )
    if not expected_ids or plan.get("run_ids") != expected_ids:
        raise ValueError("Frozen repeat identities or count are invalid.")
    return envelope


def _scope(
    runner: ProjectRunner, stage_id: str, source_paths: list[str] | None
) -> tuple[RunPlan, list[dict]]:
    stage = next((s for s in runner.pipeline.stages if s.id == stage_id), None)
    if (
        not stage
        or not stage.enabled
        or not stage.prompt_ref
        or stage.input_source != "raw_transcripts"
        or stage.input_grouping != "per_file"
        or stage.group_by_network
        or stage.include_original_transcript
    ):
        raise ValueError(
            "Choose an enabled per-transcript coding stage that reads original transcripts."
        )
    if runner._previous_llm_stage(stage) is not None:
        raise ValueError("Repeated coding currently supports the first coding stage only.")
    original = runner.build_run_plan()
    available = {
        i.path.replace("\\", "/"): i for i in original.discovered_inputs if i.kind == "transcript"
    }
    selected = (
        sorted({p.replace("\\", "/") for p in source_paths})
        if source_paths is not None
        else sorted(available)
    )
    if not selected or any(p not in available for p in selected):
        raise ValueError("Select at least one existing transcript from this study.")
    # The legacy engine uses source stems for artifact filenames.
    stems = [Path(p).stem.casefold() for p in selected]
    if len(stems) != len(set(stems)):
        raise ValueError(
            "Selected transcripts have duplicate file stems; use uniquely named imports."
        )
    inputs = [available[p] for p in selected]
    planned = [
        p
        for p in original.planned_stage_runs
        if p.stage_id == stage_id and p.input_path.replace("\\", "/") in selected
    ]
    if not planned:
        raise ValueError("The selected coding stage has no planned requests.")
    plan = original.model_copy(update={"discovered_inputs": inputs, "planned_stage_runs": planned})
    codebook_text = (
        runner.codebook.model_dump_json(indent=2)
        if runner.codebook
        else runner._load_reference_file("codebook")
    )
    if stage.use_codebook and not codebook_text:
        raise ValueError("Import the coding stage's codebook before preparing repeats.")
    codebook_label = (
        f"{runner.codebook.name} Codebook" if runner.codebook else "CFIR Construct Code Book"
    )
    suffix = (
        f"\n\n---\n\n{codebook_label}:\n\n{codebook_text}"
        if stage.use_codebook and codebook_text
        else ""
    )
    prompt = get_prompt_text(
        resolve_repo_path(runner.repo_root, runner.framework.prompt_set),
        stage.prompt_ref,
        runner.repo_root,
    )
    partitions = runner._generic_codebook_partitions(stage)
    calls = []
    for item in inputs:
        text = transcript_to_text(runner.repo_root / item.path)
        if stage.domain_iterations:
            prompts = {}
            for domain in runner.framework.domains:
                parts = [prompt.replace("{CFIR_DOMAIN}", domain), "---", f"Transcript:\n\n{text}"]
                if suffix:
                    parts.append(f"{codebook_label}:\n\n{codebook_text}")
                prompts[f"{item.path}::{domain}"] = "\n\n".join(parts)
        elif partitions:
            prompts = {
                f"{item.path}::{name}": (
                    f"{prompt}\n\n---\n\n{runner._method_policy_instruction(name)}"
                    f"\n\n---\n\nTranscript:\n\n{text}"
                    f"\n\n---\n\n{codebook_label}:\n\n{book}"
                )
                for name, book in partitions.items()
            }
        else:
            prompts = {item.path: f"{prompt}\n\n---\n\nTranscript:\n\n{text}{suffix}"}
        for label, user_prompt in prompts.items():
            calls.append(
                dict(
                    stage_id=stage_id,
                    input_label=label,
                    source_path=item.path,
                    system_prompt=_API_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                )
            )
    if len(calls) != len(planned):
        raise ValueError("Request forecast does not match the selected coding plan.")
    return plan, calls


def _budget(runner: ProjectRunner, calls: list[dict], repeats: int, root: Path) -> dict:
    provider = runner.project.provider
    if provider.name not in {"mock", "openai", "anthropic"}:
        raise ValueError("Repeated coding supports OpenAI, Anthropic and the synthetic local mock.")
    if provider.name == "mock" and runner.project.data_classification != "synthetic":
        raise ValueError("Mock repeated coding is available only for synthetic studies.")
    cost = runner._build_cost_controller(run_id="repeat-preflight", artifact_root=root)
    if provider.name != "mock" and cost is None:
        raise ValueError("Configure provider pricing and an absolute spending ceiling first.")
    if cost and cost.unresolved_requests():
        raise ValueError("Prior request usage is unresolved; reconcile it before repeated coding.")
    per_repeat = (
        sum(
            cost.estimate_usd(system_prompt=c["system_prompt"], user_prompt=c["user_prompt"])
            for c in calls
        )
        if cost
        else 0.0
    )
    spent = cost.project_cost_usd() if cost else 0.0
    ceiling = cost.policy.absolute_limit_usd if cost else 0.0
    estimate = per_repeat * repeats
    if cost and spent + estimate > ceiling:
        raise CostLimitExceeded(
            "The remaining repeats exceed the study's remaining spending ceiling."
        )
    return dict(
        estimated_cost_usd=estimate,
        estimated_cost_per_repeat_usd=per_repeat,
        spent_usd=spent,
        absolute_limit_usd=ceiling,
        remaining_budget_usd=max(ceiling - spent, 0),
        remaining_repeats=repeats,
        pricing=cost.snapshot.model_dump(mode="json") if cost else None,
    )


def prepare_repeats(
    project_path: Path,
    *,
    repeat_count: int,
    stage_id: str,
    source_paths: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Prepare immutable plans and a conservative forecast; never contact a provider."""
    if (
        isinstance(repeat_count, bool)
        or not isinstance(repeat_count, int)
        or not 2 <= repeat_count <= 10
    ):
        raise ValueError("Choose between 2 and 10 coding repeats.")
    runner = ProjectRunner(project_path)
    study = StudyWorkspace(runner.repo_root).managed_study_root(project_path)
    scoped, calls = _scope(runner, stage_id, source_paths)
    identifier = "repeat-" + uuid.uuid4().hex
    root = study / "experiments" / identifier
    budget = _budget(runner, calls, repeat_count, root)
    plan = dict(
        schema_version="repeated-coding-v1",
        experiment_id=identifier,
        project_id=runner.project.project_id,
        created_at_utc=utc_now(),
        repeat_count=repeat_count,
        stage_id=stage_id,
        run_ids=[f"{identifier}-{n:02d}" for n in range(1, repeat_count + 1)],
        configuration_fingerprint=scoped.configuration_fingerprint,
        provider=runner.project.provider.model_dump(mode="json"),
        run_plan=scoped.model_dump(mode="json"),
        request_hashes=[
            dict(
                stage_id=c["stage_id"],
                input_label=c["input_label"],
                source_path=c["source_path"],
                sha256=snapshot_identity(c),
            )
            for c in calls
        ],
        budget_at_preparation=budget,
    )
    envelope = dict(plan_id=snapshot_identity(plan), plan=plan)
    if not dry_run:
        _write_new(root / "plan.json", envelope)
        _save_status(
            root, dict(status="prepared", completed_run_ids=[], active_run_id=None, error=None)
        )
    return envelope


def _current(project_path: Path, experiment_id: str) -> tuple[ProjectRunner, dict, list[dict]]:
    envelope = read_repeat_plan(project_path, experiment_id)
    plan = envelope["plan"]
    runner = ProjectRunner(project_path)
    if (
        plan["project_id"] != runner.project.project_id
        or plan["configuration_fingerprint"] != runner.configuration_lock.fingerprint_sha256
        or plan["provider"] != runner.project.provider.model_dump(mode="json")
    ):
        raise ValueError(
            "Configuration changed after preparation; create a new repeated-coding plan."
        )
    scoped, calls = _scope(
        runner, plan["stage_id"], [i["path"] for i in plan["run_plan"]["discovered_inputs"]]
    )
    hashes = [
        dict(
            stage_id=c["stage_id"],
            input_label=c["input_label"],
            source_path=c["source_path"],
            sha256=snapshot_identity(c),
        )
        for c in calls
    ]
    if scoped.model_dump(mode="json") != plan["run_plan"] or hashes != plan["request_hashes"]:
        raise ValueError(
            "Sources or coding prompts changed after preparation; "
            "create a new repeated-coding plan."
        )
    return runner, envelope, calls


def _completed(root: Path, artifacts: Path, plan: dict, runner: ProjectRunner) -> list[str]:
    completed = []
    for run_id in plan["run_ids"]:
        receipt = root / "completed" / f"{run_id}.json"
        if not receipt.exists():
            continue
        value = _read(receipt)
        run_root = artifacts / run_id
        if value.get("run_id") != run_id or value.get("plan_id") != snapshot_identity(plan):
            raise ValueError("A completed repeat receipt belongs to another run or plan.")
        required = set(_assert_finished(runner, run_root, plan)) | {"evidence_review/index.json"}
        if set(value.get("hashes", {})) != required:
            raise ValueError("A completed repeat receipt is missing its preserved outputs.")
        for name, digest in value["hashes"].items():
            path = (artifacts / run_id / name).resolve()
            if (
                not path.is_relative_to((artifacts / run_id).resolve())
                or not path.exists()
                or sha256_for_file(path) != digest
            ):
                raise ValueError(
                    "A completed repeat's preserved outputs changed; execution is blocked."
                )
        completed.append(run_id)
    return completed


def repeat_preflight(project_path: Path, experiment_id: str) -> dict:
    runner, envelope, calls = _current(project_path, experiment_id)
    plan = envelope["plan"]
    root = experiment_root(project_path, experiment_id)
    artifacts = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    completed = _completed(root, artifacts, plan, runner)
    budget = _budget(runner, calls, plan["repeat_count"] - len(completed), root)
    return dict(
        **envelope,
        **budget,
        call_count_per_repeat=len(calls),
        remaining_call_allowance=len(calls) * budget["remaining_repeats"],
        completed_run_ids=completed,
    )


class _ScopedRunner(ProjectRunner):
    """Restrict discovery and check exact prompts before the durable request wrapper."""

    def __init__(
        self, project_path: Path, source_paths: list[str], request_hashes: list[dict]
    ) -> None:
        super().__init__(project_path)
        self.selected = {str((self.repo_root / p).resolve()) for p in source_paths}
        self.expected_requests = {(c["stage_id"], c["input_label"]): c for c in request_hashes}

    def _transcript_files(self) -> list[Path]:
        return [p for p in super()._transcript_files() if str(p.resolve()) in self.selected]

    def _complete(self, **kwargs):
        expected = self.expected_requests.get((kwargs["stage_id"], kwargs["input_label"]))
        actual = dict(
            stage_id=kwargs["stage_id"],
            input_label=kwargs["input_label"],
            source_path=expected["source_path"] if expected else "",
            system_prompt=kwargs.get("system_prompt", _API_SYSTEM_PROMPT),
            user_prompt=kwargs["user_prompt"],
        )
        if expected is None or snapshot_identity(actual) != expected["sha256"]:
            raise ValueError("The coding request differs from its approved frozen forecast.")
        return super()._complete(**kwargs)


def _assert_finished(runner: ProjectRunner, run_root: Path, plan: dict) -> list[str]:
    manifest_path = run_root / "run_manifest.json"
    manifest = _read(manifest_path)
    if (
        manifest.get("run_id") != run_root.name
        or manifest.get("project_id") != plan["project_id"]
        or manifest.get("configuration_fingerprint") != plan["configuration_fingerprint"]
    ):
        raise ValueError("The repeat manifest differs from its frozen study configuration.")
    if (
        manifest["status"] not in {"completed", "awaiting_review"}
        or manifest.get("structured_output_failure_count")
        or manifest.get("pending_gate") not in {None, plan["stage_id"]}
    ):
        raise ValueError(
            "Coding stopped before producing all valid outputs; "
            "review this repeat before continuing."
        )
    expected = {i["path"]: i for i in plan["run_plan"]["discovered_inputs"]}
    found = set()
    for rel in manifest["artifact_paths"]:
        path = (run_root / rel).resolve()
        if not path.is_relative_to(run_root.resolve()):
            raise ValueError("Repeat artifact points outside its run.")
        artifact = StageArtifact.model_validate(_read(path))
        source = expected.get(artifact.input_path)
        if (
            not source
            or artifact.stage_id != plan["stage_id"]
            or artifact.run_id != run_root.name
            or artifact.parsed_output is None
            or artifact.structured_output_valid is False
        ):
            raise ValueError("Repeat contains an incomplete or unexpected coding artifact.")
        allowed = {
            source["sha256"],
            sha256_for_text(transcript_to_text(runner.repo_root / source["path"])),
        }
        if artifact.input_sha256 not in allowed:
            raise ValueError("Repeat artifact does not match its frozen transcript.")
        found.add(artifact.input_path)
    if found != set(expected):
        raise ValueError("Coding did not complete every selected transcript.")
    from qualframe.study_progress import transcript_progress

    progress = transcript_progress(run_root, run_root / "__unused_review__", [], runner.repo_root)
    if not progress or not all(row["completed"] for row in progress):
        raise ValueError("Repeat coding has incomplete or malformed domain/partition outputs.")
    return [
        "run_manifest.json",
        "run_plan.json",
        "analysis_configuration_lock.json",
        *manifest["artifact_paths"],
    ]


def execute_repeats(
    project_path: Path,
    experiment_id: str,
    *,
    plan_id: str,
    actor: str,
    rationale: str,
    live_confirmed: bool = False,
    resume: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Run sequentially, stopping on failure and preserving every prior request/output."""
    preview = repeat_preflight(project_path, experiment_id)
    plan = preview["plan"]
    root = experiment_root(project_path, experiment_id)
    if plan_id != preview["plan_id"]:
        raise ValueError("Review the current repeated-coding preflight before starting.")
    if not actor.strip() or not rationale.strip():
        raise ValueError("Repeated coding requires a researcher identity and reason.")
    live = plan["provider"]["name"] != "mock"
    if live and not live_confirmed:
        raise ValueError("Confirm governed provider transfer and spending for these repeats.")
    if live and not os.getenv(plan["provider"]["api_key_env"] or ""):
        raise ValueError("Enter the configured API key for this app session.")
    if (root / "attempts").exists() and not resume:
        raise ValueError("This experiment was already started. Use explicit resume to continue it.")
    if dry_run:
        return root
    # Exclusive OS lock also prevents overlapping execution outside the browser.
    lock = _acquire_execution_lock(root / "execution.lock")
    try:
        preview = repeat_preflight(project_path, experiment_id)
        if preview["plan_id"] != plan_id:
            raise ValueError("Review the current repeated-coding preflight before starting.")
        if (root / "attempts").exists() and not resume:
            raise ValueError(
                "This experiment was already started. Use explicit resume to continue it."
            )
    except Exception:
        lock.close()
        raise
    status = dict(
        status="running",
        completed_run_ids=preview["completed_run_ids"],
        active_run_id=None,
        error=None,
    )
    try:
        _write_new(
            root / "attempts" / f"{uuid.uuid4().hex}.json",
            dict(
                plan_id=plan_id,
                actor=actor.strip(),
                rationale=rationale.strip(),
                governance_confirmed=live_confirmed if live else None,
                resume=resume,
                preflight=preview,
                started_at_utc=utc_now(),
            ),
        )
        _save_status(root, status)
        for run_id in plan["run_ids"]:
            fresh = repeat_preflight(project_path, experiment_id)
            if run_id in fresh["completed_run_ids"]:
                continue
            status["active_run_id"] = run_id
            _save_status(root, status)
            if progress_callback:
                progress_callback(run_id)
            runner = _ScopedRunner(
                project_path,
                [i["path"] for i in plan["run_plan"]["discovered_inputs"]],
                plan["request_hashes"],
            )
            run_root = (
                resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"]) / run_id
            )
            frozen = RunPlan.model_validate(plan["run_plan"])
            if (run_root / "run_plan.json").exists():
                if _read(run_root / "run_plan.json") != plan["run_plan"]:
                    raise ValueError("A repeat run plan changed after preparation.")
            else:
                if run_root.exists():
                    raise ValueError("Repeat run directory already exists without its frozen plan.")
                runner.save_run_plan(frozen, run_id)
            # A manifest completed just before interruption can be recognized without rerunning it.
            if not (run_root / "run_manifest.json").exists():
                runner.execute_run_plan(frozen, run_id, stage_filter=[plan["stage_id"]])
            files = _assert_finished(runner, run_root, plan)
            _current(project_path, experiment_id)
            index = run_root / "evidence_review" / "index.json"
            if not index.exists():
                write_evidence_review_index(project_manifest_path=project_path, run_id=run_id)
            files.append("evidence_review/index.json")
            _write_new(
                root / "completed" / f"{run_id}.json",
                dict(
                    run_id=run_id,
                    plan_id=plan_id,
                    hashes={p: sha256_for_file(run_root / p) for p in files},
                    completed_at_utc=utc_now(),
                ),
            )
            status["completed_run_ids"].append(run_id)
            _save_status(root, status)
        status.update(status="completed", active_run_id=None, completed_at_utc=utc_now())
        _save_status(root, status)
    except Exception as exc:
        status.update(status="stopped", error=str(exc), stopped_at_utc=utc_now())
        _save_status(root, status)
        raise
    finally:
        lock.close()
    return root
