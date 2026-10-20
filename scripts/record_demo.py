"""Record only the six fictional demo interviews for offline replay.

A preset supplies model settings and prices. Credentials must already be in the
process environment; this script never reads a .env file.

Use one --state-dir for every cell of an experiment. Its synthetic study, shared
spending limit, request records and run configurations survive interruption.
Resume the same cell with identical options and --resume. Uncertain, incomplete
or unpriced responses stop execution and are never automatically resent.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import yaml  # noqa: E402

from qualframe.app_workspace import ensure_workspace  # noqa: E402
from qualframe.config import load_codebook_spec, resolve_repo_path  # noqa: E402
from qualframe.cost_control import (  # noqa: E402
    CostController, UnresolvedRequest, append_cost_approval, approved_cost_thresholds, request_lock,
)
from qualframe.decision_style import get_stage_prompt_path  # noqa: E402
from qualframe.directed_analysis import partition_codebook  # noqa: E402
from qualframe.io.files import sha256_for_file, sha256_for_text  # noqa: E402
from qualframe.io.transcript_io import transcript_to_text  # noqa: E402
from qualframe.models import MethodPolicyUpdate, RunPlan  # noqa: E402
from qualframe.pipeline import project_runner as runner_module  # noqa: E402
from qualframe.pipeline.project_runner import ProjectRunner  # noqa: E402
from qualframe.provider_setup import ProviderSetup, save_provider_setup  # noqa: E402
from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens  # noqa: E402
from qualframe.providers.recorded_provider import recording_key, transcript_from_prompt  # noqa: E402
from qualframe.study_setup import StudyWorkspace  # noqa: E402

DATASET = REPO_ROOT / "demo/datasets/ai-scribe"
DIVISIONS = {"full_codebook": "full_codebook", "top_level_categories": "per_top_level_category"}
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")


class IllustrativeProvider(LLMProvider):
    """Hand-written positive codings, reserved for the original find/whole demo."""

    name = "illustrative"

    def __init__(self, codings: dict[str, list[dict]]) -> None:
        self.codings = codings

    def complete(self, *, system_prompt, user_prompt, attachments=None, response_schema=None):
        match = re.search(r"Participant (P\d\d),", transcript_from_prompt(user_prompt) or "")
        rows = self.codings.get(match.group(1), []) if match else []
        text = json.dumps({"codings": rows}, ensure_ascii=False, indent=1)
        return LLMResponse(text=text, model="illustrative", provider=self.name,
                           usage=LLMUsage(input_tokens=estimate_tokens(user_prompt), output_tokens=estimate_tokens(text)))


def _write_json(path: Path, value: Any) -> None:
    """Replace a state document atomically, after flushing its contents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _responses(run_root: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((run_root / "requests").glob("*.json"))]


def _completed_count(run_root: Path) -> int:
    return sum(row.get("response", {}).get("status") == "completed"
               and bool(row.get("response", {}).get("text", "").strip()) for row in _responses(run_root))


class RecordingRunner(ProjectRunner):
    """The ordinary runner persists hosted responses before this progress hook."""

    recording_name: str
    expected_requests: int
    recording_root: Path

    def _complete(self, **kwargs) -> LLMResponse:
        response = super()._complete(**kwargs)
        controller = kwargs.get("cost_controller")
        if controller is not None and response.usage is None:
            raise UnresolvedRequest("Provider usage is missing; the saved response cannot be followed by another request.")
        if controller is None:
            # Offline illustrative responses do not have a cost-controller request record.
            key = recording_key(kwargs["user_prompt"])
            _write_json(self.recording_root / "requests" / f"{key}.json", {
                "request_id": key, "input_label": kwargs["input_label"],
                "response": dataclasses.asdict(response), "elapsed_seconds": 0,
            })
        count = _completed_count(self.recording_root)
        spend = controller.project_cost_usd() if controller is not None else 0
        print(f"{self.recording_name}: {count}/{self.expected_requests} responses saved; "
              f"shared recorded spend USD {spend:.6f}", flush=True)
        return response


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--illustrative", type=Path, help="Original hand-written codings JSON; no model")
    parser.add_argument("--preset")
    parser.add_argument("--provider", choices=["openai", "anthropic", "openai_compatible"])
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--input-rate", type=float)
    parser.add_argument("--output-rate", type=float)
    parser.add_argument("--limit-usd", type=float, default=1.0, help="Total new spending across this state directory")
    parser.add_argument("--coding-style", choices=["find_passages", "decide_each_code"], default="find_passages")
    parser.add_argument("--codebook-division", choices=list(DIVISIONS), default="full_codebook")
    parser.add_argument("--state-dir", type=Path, help="Durable workspace shared by every recording cell")
    parser.add_argument("--resume", action="store_true", help="Continue the same cell with unchanged options")
    parser.add_argument("--yes", action="store_true", help="Confirm sending fictional interviews with the stated total limit")
    return parser


def _setup(args: argparse.Namespace) -> ProviderSetup | None:
    if args.illustrative:
        if args.provider or args.preset or args.resume or args.state_dir:
            raise ValueError("Illustrative recording cannot use a provider, durable state or --resume.")
        if args.coding_style != "find_passages" or args.codebook_division != "full_codebook":
            raise ValueError("The existing handwritten coding is only a find-passages/whole-codebook illustration.")
        return None
    preset: dict = {}
    checked_on = datetime.now(timezone.utc).date().isoformat()
    if args.preset:
        catalogue = yaml.safe_load((REPO_ROOT / "config/model_presets.yaml").read_text(encoding="utf-8"))
        presets = {row["id"]: row for row in catalogue["presets"]}
        if args.preset not in presets:
            raise ValueError(f"Unknown preset: {args.preset}")
        preset = presets[args.preset]
        checked_on = catalogue["checked_on"]

    def pick(name: str, default=None):
        value = getattr(args, name, None)
        return value if value is not None else preset.get(name, default)

    if not pick("provider") or not pick("model"):
        raise ValueError("Give --illustrative, --preset, or --provider and --model.")
    if not args.yes:
        raise ValueError("Add --yes only after approving the fictional requests and total spending limit.")
    reasoning = pick("reasoning_effort")
    return ProviderSetup(
        provider=pick("provider"), model=pick("model"), max_tokens=pick("max_tokens", 16000),
        temperature=None if reasoning else pick("temperature"),
        api_mode="responses" if reasoning or preset.get("api_mode") == "responses" else "chat_completions",
        reasoning_effort=reasoning, absolute_limit_usd=args.limit_usd,
        input_rate=pick("input_rate", 0), output_rate=pick("output_rate", 0),
        pricing_date=checked_on, pricing_source=preset.get("pricing_source", ""),
        governance_confirmed=True, base_url=pick("base_url"),
    )


def _dataset_hashes() -> dict[str, str]:
    files = [DATASET / "codebook.yaml", DATASET / "metadata.csv", *sorted((DATASET / "transcripts").rglob("*.txt"))]
    return {p.relative_to(DATASET).as_posix(): sha256_for_file(p) for p in files}


def _new_state(root: Path, args: argparse.Namespace, setup: ProviderSetup | None) -> dict:
    if any(p.name != ".recording.lock" for p in root.iterdir()):
        raise ValueError("A new recording state needs an empty directory; existing workspace was not changed.")
    ensure_workspace(root, app_root=REPO_ROOT)
    created = StudyWorkspace(root).create_from_dataset(
        dataset_root=DATASET, title="Fictional demo recordings", study_id="demo-recordings")
    manifest = yaml.safe_load((root / created.project_manifest_path).read_text(encoding="utf-8"))
    identity = {key: manifest.get(key) for key in ("project_id", "paths", "framework", "pipeline", "metadata_file")}
    return {
        "schema_version": 1, "project_manifest_path": created.project_manifest_path, "study_identity": identity,
        "absolute_limit_usd": args.limit_usd,
        "max_tokens": setup.max_tokens if setup else None,
        "dataset_hashes": _dataset_hashes(), "active_recording": None, "recordings": {},
    }


def _validate_study(root: Path, project: Path, state: dict) -> None:
    if project.resolve() != (root / "studies/demo-recordings/project.yaml").resolve():
        raise ValueError("The recorder's project location changed; no request was sent.")
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    identity = {key: data.get(key) for key in state["study_identity"]}
    if identity != state["study_identity"] or data.get("data_classification") != "synthetic":
        raise ValueError("The shared study identity or ledger/source paths changed; no request was sent.")
    for key in ("method", "codebook"):
        if data.get(key) and not (root / data[key]).resolve().is_relative_to(project.parent.resolve() / "config"):
            raise ValueError("The recorder's configuration must stay inside its synthetic study.")
    runner = ProjectRunner(project)
    original = sorted((p.name, sha256_for_text(transcript_to_text(p)))
                      for p in (DATASET / "transcripts").rglob("*.txt"))
    copied = sorted((p.name, sha256_for_text(transcript_to_text(p))) for p in runner._transcript_files())
    if copied != original or runner.codebook != load_codebook_spec(DATASET / "codebook.yaml"):
        raise ValueError("Copied study inputs differ from the fictional dataset; no request was sent.")


def _configure(root: Path, project: Path, args: argparse.Namespace, setup: ProviderSetup | None) -> None:
    workspace = StudyWorkspace(root)
    runner = ProjectRunner(project)
    method = runner.method
    assert method is not None
    workspace.update_method_policy(
        project_manifest_path=project,
        update=MethodPolicyUpdate(
            segmentation_strategy=method.segmentation.strategy, context_unit=method.context.unit,
            context_before=method.context.before, context_after=method.context.after,
            coding_cardinality=method.coding.cardinality, allow_overlapping_spans=method.coding.allow_overlapping_spans,
            coding_decision_style=args.coding_style, partition_strategy=DIVISIONS[args.codebook_division],
        ), actor="record_demo.py", rationale="Record fictional demo comparison cell",
    )
    if setup is not None:
        folder = save_provider_setup(workspace, project, setup, actor="record_demo.py",
                                     rationale="Record fictional demo comparison cell", use_environment_key=True)
        # These are newly created configuration files; no prior run uses them yet.
        policy_path = folder / "cost.yaml"
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        policy.update(notification_adapter="none", notification_recipient_env=None)
        policy_path.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")


def _expected(runner: ProjectRunner) -> tuple[dict[str, str], dict]:
    stages = [s for s in runner.pipeline.stages if s.enabled and s.prompt_ref]
    if len(stages) != 1 or not runner.codebook or not runner.method:
        raise ValueError("Recording requires the single-stage fictional directed coding pipeline.")
    stage = stages[0]
    if stage.input_source != "raw_transcripts" or stage.input_grouping != "per_file" or stage.domain_iterations:
        raise ValueError("Recording requires one directed coding stage over the fictional transcripts.")
    prompt_path = get_stage_prompt_path(runner.repo_root,
                                       resolve_repo_path(runner.repo_root, runner.framework.prompt_set), stage, runner.method)
    groups = partition_codebook(runner.codebook, runner.method.partitioning)
    expected: dict[str, str] = {}
    hashes = []
    for path in runner._transcript_files():
        transcript = transcript_to_text(path)
        hashes.append({"file": path.name, "sha256": sha256_for_text(transcript)})
        for partition in groups:
            key = recording_key(f"Codebook partition for this request: {partition}.\n\nTranscript:\n\n{transcript}")
            assert key is not None
            expected[f"{path.relative_to(runner.repo_root)}::{partition}"] = key
    if len(set(expected.values())) != len(expected):
        raise ValueError("Duplicate transcript/partition recording keys are not supported.")
    return expected, {
        "prompt_sha256": sha256_for_text(prompt_path.read_text(encoding="utf-8")),
        "prompt_file": prompt_path.relative_to(runner.repo_root).as_posix(),
        "codebook_sha256": sha256_for_text(runner.codebook.model_dump_json(indent=2)),
        "transcripts": sorted(hashes, key=lambda row: row["file"]),
    }


def _guard_attempts(run_root: Path, controller: CostController | None) -> None:
    if controller is not None and controller.unresolved_requests():
        raise UnresolvedRequest("Shared recording state has unresolved usage; reconcile it before continuing. No request was sent.")
    responses = _responses(run_root)
    if controller is not None:
        ledger = {r["request_id"]: r for r in _read_rows(controller.ledger_path)
                  if r.get("project_id") == controller.project_id and r.get("run_id") == controller.run_id}
        saved = {r["request_id"]: r for r in responses}
        if set(ledger) != set(saved):
            raise ValueError("Paid ledger entries and saved response records differ; nothing will be resent.")
        for request_id, row in saved.items():
            usage = (row.get("response") or {}).get("usage")
            if usage is not None and any(usage.get(key, 0) != ledger[request_id].get(key, 0) for key in USAGE_FIELDS):
                raise ValueError("Saved response usage differs from its ledger record; no request was sent.")
    for row in responses:
        response = row.get("response")
        if not isinstance(response, dict) or response.get("status") != "completed" or not response.get("text", "").strip():
            raise ValueError("A prior request failed or returned incomplete/empty output. It will not be automatically resent.")
        if controller is not None and response.get("usage") is None:
            raise ValueError("A prior response has no provider usage. Recording cannot continue automatically.")


def _info_and_texts(runner: RecordingRunner, args: argparse.Namespace, cell: dict,
                    expected: dict[str, str], provenance: dict, controller: CostController | None) -> tuple[dict, dict[str, str]]:
    _guard_attempts(runner.recording_root, controller)
    rows = _responses(runner.recording_root)
    labels = [row["input_label"] for row in rows]
    if len(labels) != len(set(labels)) or set(labels) != set(expected):
        raise ValueError("Saved request records do not exactly cover the expected transcript/partition requests.")
    texts = {expected[row["input_label"]]: row["response"]["text"] for row in rows}
    usage = dict.fromkeys(USAGE_FIELDS, 0)
    cost = None
    if controller is not None:
        latest = {r["request_id"]: r for r in _read_rows(controller.ledger_path)
                  if r.get("project_id") == runner.project.project_id and r.get("run_id") == cell["run_id"]}
        if set(latest) != {row["request_id"] for row in rows} or any(r.get("cost_is_estimated") for r in latest.values()):
            raise ValueError("Every saved response needs settled provider usage in the shared ledger before export.")
        for record in latest.values():
            for key in USAGE_FIELDS:
                usage[key] += record.get(key, 0)
        cost = round(sum(row["calculated_cost_usd"] for row in latest.values()), 8)
    else:
        for row in rows:
            for key in USAGE_FIELDS:
                usage[key] += (row["response"].get("usage") or {}).get(key, 0)
    settings = runner.project.provider.model_dump(exclude_none=True, exclude={"api_key_env"})
    if cell["options"]["provider_setup"]:
        rates = cell["options"]["provider_setup"]
        settings["prices_usd_per_million"] = {"input": rates["input_rate"], "output": rates["output_rate"],
                                              "checked_on": rates["pricing_date"]}
    manifest = json.loads((runner.recording_root / "run_manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "completed":
        raise ValueError("The coding run did not complete; no public recording was exported.")
    info = {
        "id": args.name, "label": args.label, "kind": "illustrative" if args.illustrative else "model",
        "description": ("Hand-written example codings for demonstrating the software. Not output from a model."
                        if args.illustrative else f"Responses recorded from {args.label} over the fictional demo transcripts."),
        "dataset": DATASET.name, "recorded_at_utc": manifest["completed_at_utc"],
        "status": "completed", "complete": True, "requests": len(rows), "completed_requests": len(rows),
        "expected_requests": len(expected), "total_requests": len(expected),
        "coding_style": args.coding_style, "codebook_division": args.codebook_division,
        "partition_strategy": DIVISIONS[args.codebook_division], "provider_settings": settings,
        "method_policy": runner.method.model_dump(mode="json", exclude={"id", "version", "name"}),
        "returned_models": sorted({row["response"]["model"] for row in rows}),
        "configuration_fingerprint": cell["configuration_fingerprint"],
        "reported_usage": {"input_tokens": usage["input_tokens"] + usage["cached_input_tokens"] + usage["cache_write_tokens"],
                           "output_tokens": usage["output_tokens"] + usage["reasoning_tokens"]},
        "usage_breakdown": usage, "response_status": ["completed"],
        "actual_cost_usd": cost, "estimated_cost_usd": cost,
        "cost_source": "provider_usage_ledger" if controller is not None else "illustrative_no_charge",
        "cost_is_estimated": controller is None,
        "elapsed_request_seconds": round(sum(row.get("elapsed_seconds", 0) for row in rows), 6),
        "qa_failure_count": manifest["qa_failure_count"], "no_decision_count": manifest.get("no_decision_count", 0),
        "response_sha256": {key: sha256_for_text(value) for key, value in sorted(texts.items())},
        **provenance,
    }
    return info, texts


def _export(target: Path, info: dict, texts: dict[str, str]) -> None:
    if target.exists():
        saved = json.loads((target / "recording.json").read_text(encoding="utf-8"))
        files = {p.stem: p.read_text(encoding="utf-8") for p in (target / "responses").glob("*.txt")}
        if saved != info or files != texts:
            raise ValueError("Existing recording differs from the saved completed run; nothing was overwritten.")
        return  # Recover a crash after export but before the state was marked complete.
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        (staged / "responses").mkdir()
        for key, value in texts.items():
            (staged / "responses" / f"{key}.txt").write_text(value, encoding="utf-8", newline="\n")
        _write_json(staged / "recording.json", info)
        staged.rename(target)
    finally:
        if staged.exists():
            if not staged.resolve().is_relative_to(target.parent.resolve()) or not staged.name.startswith(f".{target.name}-"):
                raise ValueError("Unexpected export staging directory; it was preserved.")
            shutil.rmtree(staged)


def record(args: argparse.Namespace, root: Path, setup: ProviderSetup | None) -> dict:
    root = root.expanduser().resolve()
    if root.is_relative_to((REPO_ROOT / "demo/recordings").resolve()):
        raise ValueError("Private recording state must remain outside public demo recordings.")
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "recording_state.json"
    target = REPO_ROOT / "demo/recordings" / args.name
    with request_lock(root / ".recording.lock"):
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else _new_state(root, args, setup)
        _write_json(state_path, state)
        if state["absolute_limit_usd"] != args.limit_usd or state["max_tokens"] != (setup.max_tokens if setup else None):
            raise ValueError("Shared spending and output-token limits cannot change within a recording state.")
        if state["dataset_hashes"] != _dataset_hashes():
            raise ValueError("The fictional dataset changed; existing recordings will not be resumed or mixed.")
        options = {"label": args.label, "coding_style": args.coding_style, "codebook_division": args.codebook_division,
                   "provider_setup": setup.model_dump(mode="json") if setup else None}
        project = root / state["project_manifest_path"]
        _validate_study(root, project, state)
        cell = state["recordings"].get(args.name)
        if state["active_recording"] not in {None, args.name}:
            raise ValueError("Finish or resolve the active recording before starting another cell.")
        if cell:
            if not args.resume:
                raise ValueError("This cell already has saved state. Use unchanged options and --resume.")
            if cell["options"] != options:
                raise ValueError("Resume requires exactly the original provider, style, division and label.")
            if cell["status"] == "completed":
                # Completed cells are immutable; --resume never sends another request.
                return json.loads((target / "recording.json").read_text(encoding="utf-8"))
        else:
            if args.resume:
                raise ValueError("No saved recording exists to resume.")
            if target.exists():
                raise ValueError("This recording folder already exists; choose a new name.")
            _configure(root, project, args, setup)
        runner = RecordingRunner(project)
        if runner.project.data_classification != "synthetic":
            raise ValueError("Only the recorder's synthetic study is allowed.")
        run_id = cell["run_id"] if cell else f"record-{args.name}"
        run_root = resolve_repo_path(root, runner.project.paths["artifacts"]) / run_id
        expected, provenance = _expected(runner)
        runner.recording_name, runner.recording_root, runner.expected_requests = args.name, run_root, len(expected)
        controller = runner._build_cost_controller(run_id=run_id, artifact_root=run_root)
        if controller is not None:
            if controller.policy.absolute_limit_usd != state["absolute_limit_usd"] or controller.policy.notification_adapter != "none":
                raise ValueError("The saved shared budget or notification policy changed; no request was sent.")
        _guard_attempts(run_root, controller)
        if cell:
            plan = RunPlan.model_validate_json((run_root / "run_plan.json").read_text(encoding="utf-8"))
            if runner.configuration_lock.fingerprint_sha256 != cell["configuration_fingerprint"]:
                raise ValueError("Saved configuration changed; no request was sent.")
        else:
            plan = runner.build_run_plan()
            runner.save_run_plan(plan, run_id)
            cell = {"run_id": run_id, "status": "running", "options": options,
                    "configuration_fingerprint": plan.configuration_fingerprint}
            state["recordings"][args.name] = cell
            (run_root / "recording_project.yaml").write_bytes(project.read_bytes())
        state["active_recording"] = args.name
        cell["status"] = "running"
        _write_json(state_path, state)
        if controller is not None:
            threshold = controller.policy.approval_increment_usd
            if threshold not in approved_cost_thresholds(controller.approvals_path, controller.project_id):
                append_cost_approval(controller.approvals_path, project_id=controller.project_id, run_id=run_id,
                                     threshold_usd=threshold, decision="approve", reviewer="record_demo.py --yes",
                                     rationale="Explicit recording authorization within the shared absolute limit")
        original_build = runner_module.build_provider
        if args.illustrative:
            runner_module.build_provider = lambda config: IllustrativeProvider(json.loads(args.illustrative.read_text(encoding="utf-8")))
        try:
            print(f"{args.name}: {_completed_count(run_root)}/{len(expected)} responses already saved", flush=True)
            manifest_path = run_root / "run_manifest.json"
            if not manifest_path.exists():
                runner.execute_run_plan(plan, run_id)
            info, texts = _info_and_texts(runner, args, cell, expected, provenance, controller)
            _export(target, info, texts)
            cell.update(status="completed", completed_requests=len(expected), actual_cost_usd=info["actual_cost_usd"])
            state["active_recording"] = None
            _write_json(state_path, state)
            return info
        except BaseException as exc:
            cell.update(status="stopped", stop_reason=type(exc).__name__, completed_requests=_completed_count(run_root))
            _write_json(state_path, state)
            print(f"{args.name}: stopped; saved requests and shared budget remain in --state-dir", flush=True)
            raise
        finally:
            runner_module.build_provider = original_build


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.name):
        parser.error("Use letters, numbers, hyphens and underscores for --name.")
    if args.resume and not args.state_dir:
        parser.error("--resume requires the original --state-dir.")
    try:
        setup = _setup(args)
    except ValueError as exc:
        parser.error(str(exc))
    root = args.state_dir or Path(tempfile.mkdtemp(prefix="qualframe-record-"))
    try:
        info = record(args, root, setup)
    except BaseException:
        if not args.state_dir:
            print(f"Recording state retained at {root}; use --state-dir to inspect or resume it.", flush=True)
        raise
    else:
        if not args.state_dir:
            if not root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) or not root.name.startswith("qualframe-record-"):
                raise ValueError("Unexpected temporary workspace location; it was preserved.")
            shutil.rmtree(root)
    print(f"Saved {info['requests']} responses to demo/recordings/{args.name}; "
          f"recorded cost USD {info['actual_cost_usd'] if info['actual_cost_usd'] is not None else 'not applicable'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
