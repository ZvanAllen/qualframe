from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from qualframe.config import (
    load_codebook_spec,
    load_cost_policy_spec,
    load_framework_spec,
    load_method_spec,
    load_pipeline_spec,
    load_project_manifest,
    load_prompt_set,
    load_pricing_snapshot_spec,
    load_stage_output_spec,
    resolve_repo_path,
)
from qualframe.configuration_lock import create_configuration_lock, run_can_resume, write_configuration_lock
from qualframe.cost_control import CostController
from qualframe.directed_analysis import parsed_assignment_policy_issues, partition_codebook
from qualframe.governance import approved_gate_ids
from qualframe.io.excel_io import REQUIRED_COLUMNS, discover_workbooks, validate_workbook, workbook_to_text
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.response_parser import coding_response_schema, parse_markdown_tables, parse_model_output
from qualframe.io.transcript_io import (
    codebook_xlsx_to_text,
    discover_transcripts,
    participant_id,
    transcript_to_text,
)
from qualframe.models import (
    DiscoveredInput,
    PlannedStageRun,
    RunManifest,
    RunPlan,
    StageArtifact,
    StageSpec,
    WorkbookValidationResult,
)
from qualframe.prompts import get_prompt_text
from qualframe.providers import build_provider
from qualframe.providers.base import LLMProvider, LLMResponse, LLMUsage, estimate_tokens
from qualframe.qa.rules import ReviewQueueItem, run_qa_on_artifact
from qualframe.qa.inventory import write_run_qa_inventory
from qualframe.structured_output import scoped_contract_sha256, validate_stage_output

# Injected into every LLM call so the model returns markdown tables instead of
# ChatGPT-era "download link" or code-execution responses.
_API_SYSTEM_PROMPT = (
    "You are being called via API, not through a chat interface. "
    "When the task instructs you to return a download link or produce an Excel file, "
    "instead return the complete workbook content as markdown tables. "
    "Use '## Sheet: <name>' as a heading for each worksheet, "
    "followed by a pipe-delimited markdown table with a header row and separator row. "
    "Do not output Python code. Do not reference file paths or sandbox environments."
)


class ProjectRunner:
    def __init__(self, project_manifest_path: Path) -> None:
        self.project_manifest_path = project_manifest_path.resolve()
        self.repo_root = self.project_manifest_path.parents[2]
        self.project = load_project_manifest(self.project_manifest_path)
        # Set to code only some transcripts (a test run); recorded in the run plan.
        self.transcript_sample: set[str] | None = None
        self.framework = load_framework_spec(resolve_repo_path(self.repo_root, self.project.framework))
        self.pipeline = load_pipeline_spec(resolve_repo_path(self.repo_root, self.project.pipeline))
        self.prompt_set = load_prompt_set(resolve_repo_path(self.repo_root, self.framework.prompt_set))
        self.method = (
            load_method_spec(resolve_repo_path(self.repo_root, self.project.method))
            if self.project.method
            else None
        )
        self.codebook = (
            load_codebook_spec(resolve_repo_path(self.repo_root, self.project.codebook))
            if self.project.codebook
            else None
        )
        self.configuration_lock = create_configuration_lock(self.project_manifest_path)
        self.structured_output_spec = (
            load_stage_output_spec(
                resolve_repo_path(self.repo_root, self.project.structured_output.spec)
            )
            if self.project.structured_output.enforce
            else None
        )
        self._structured_output_failure_count = 0

    def _build_cost_controller(
        self,
        *,
        run_id: str,
        artifact_root: Path,
    ) -> CostController | None:
        configured = (self.project.cost_policy, self.project.pricing_snapshot)
        if not any(configured):
            return None
        if not all(configured):
            raise ValueError(
                "Cost control requires both cost_policy and pricing_snapshot."
            )
        if not self.project.provider.model:
            raise ValueError(
                "Cost-controlled execution requires an explicit provider model."
            )
        policy = load_cost_policy_spec(
            resolve_repo_path(self.repo_root, self.project.cost_policy or "")
        )
        snapshot = load_pricing_snapshot_spec(
            resolve_repo_path(self.repo_root, self.project.pricing_snapshot or "")
        )
        logs_root = resolve_repo_path(
            self.repo_root, self.project.paths.get("logs", "logs")
        )
        return CostController(
            project_id=self.project.project_id,
            run_id=run_id,
            artifact_root=artifact_root,
            logs_root=logs_root,
            policy=policy,
            pricing_snapshot=snapshot,
            provider=self.project.provider.name,
            model=self.project.provider.model,
            max_output_tokens=self.project.provider.max_tokens,
        )

    def _complete(
        self,
        *,
        provider: LLMProvider,
        cost_controller: CostController | None,
        stage_id: str,
        input_label: str,
        user_prompt: str,
        system_prompt: str = _API_SYSTEM_PROMPT,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        cost_prompt = system_prompt + (json.dumps(response_schema) if response_schema else "")
        identity = sha256_for_text("\x00".join(
            (system_prompt, user_prompt, json.dumps(response_schema, sort_keys=True) if response_schema else "")))
        if cost_controller is not None:
            # A resumed run reuses answers it already paid for: the same request in the same run.
            saved = self._saved_responses(cost_controller.artifact_root / "requests").get((input_label, identity))
            if saved is not None:
                return saved
        request_id = ""
        estimated_cost = 0.0
        if cost_controller is not None:
            request_id, estimated_cost = cost_controller.preflight(
                stage_id=stage_id,
                input_label=input_label,
                system_prompt=cost_prompt,
                user_prompt=user_prompt,
            )
        started = time.monotonic()
        try:
            response = provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                **({"response_schema": response_schema} if response_schema is not None else {}),
            )
        except Exception as exc:
            reason = " ".join(str(exc).split())[:400] or type(exc).__name__
            if cost_controller is not None:
                attempts = cost_controller.artifact_root / "requests"
                attempts.mkdir(parents=True, exist_ok=True)
                (attempts / f"{request_id}.json").write_text(json.dumps({
                    "request_id": request_id, "status": "usage_unresolved",
                    "input_label": input_label, "prompt_sha256": identity,
                    "error_type": type(exc).__name__, "error_message": reason,
                    "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                    "cause_errno": getattr(exc.__cause__, "errno", None),
                    "cause_winerror": getattr(exc.__cause__, "winerror", None),
                    "elapsed_seconds": time.monotonic() - started,
                }, indent=2), encoding="utf-8")
            raise RuntimeError(
                f"Provider request failed ({reason}); no automatic retry was sent. "
                "The coding saved so far is kept. Confirm on this run's details page whether the failed "
                "request was charged, then resume the run."
            ) from exc
        if cost_controller is not None:
            attempts = cost_controller.artifact_root / "requests"
            attempts.mkdir(parents=True, exist_ok=True)
            (attempts / f"{request_id}.json").write_text(json.dumps({
                "request_id": request_id, "input_label": input_label, "prompt_sha256": identity,
                "response": dataclasses.asdict(response),
                "elapsed_seconds": time.monotonic() - started,
            }, indent=2), encoding="utf-8")
            cost_controller.record_response(
                request_id=request_id,
                estimated_cost_usd=estimated_cost,
                stage_id=stage_id,
                input_label=input_label,
                system_prompt=cost_prompt,
                user_prompt=user_prompt,
                response=response,
            )
        self._check_prompt_was_read(provider, response, system_prompt + user_prompt, input_label)
        if response.status != "completed" or not response.text.strip():
            if (response.finish_reason or "") in {"max_tokens", "length", "max_output_tokens"}:
                raise RuntimeError(
                    f"The model reached its output limit ({self.project.provider.max_tokens:,} tokens) while coding "
                    f"{input_label}; usage was recorded. Raise the maximum output tokens in the model settings, "
                    "or send one codebook category per request (Coding options), then start a new run."
                )
            raise RuntimeError("Provider returned incomplete or empty output; usage was recorded. Review before resuming.")
        return response

    def _saved_responses(self, requests_dir: Path) -> dict[tuple[str, str], LLMResponse]:
        """Completed answers already recorded for this run, by request label and prompt identity.

        Read once per run folder. Only complete, non-empty answers whose prompt matches exactly are
        reused, so a resumed run does not pay twice for requests it finished before stopping.
        """
        cache = self.__dict__.setdefault("_saved_response_cache", {})
        key = str(requests_dir)
        if key not in cache:
            found: dict[tuple[str, str], LLMResponse] = {}
            for path in sorted(requests_dir.glob("*.json")) if requests_dir.exists() else []:
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    raw = record.get("response")
                    if not isinstance(raw, dict) or not record.get("input_label") or not record.get("prompt_sha256"):
                        continue
                    usage = raw.get("usage")
                    response = LLMResponse(**{**raw, "usage": LLMUsage(**usage) if isinstance(usage, dict) else None})
                except (OSError, ValueError, TypeError):
                    continue
                if response.status == "completed" and response.text.strip():
                    found[(record["input_label"], record["prompt_sha256"])] = response
            cache[key] = found
        return cache[key]

    @staticmethod
    def _check_prompt_was_read(provider: LLMProvider, response: LLMResponse, prompt: str, input_label: str) -> None:
        """Stop when a compatible endpoint reports reading far fewer tokens than were sent.

        Local servers such as Ollama drop the start of a prompt that is longer than the model's
        context window, without an error. Coding would then cover only part of the transcript.
        """
        if getattr(provider, "name", "") != "openai_compatible" or response.usage is None:
            return
        read = response.usage.input_tokens + response.usage.cached_input_tokens
        sent = estimate_tokens(prompt)
        if 0 < read < 0.5 * sent:
            raise RuntimeError(
                f"The model read about {read:,} tokens of a request of about {sent:,} while coding {input_label}, "
                "so it probably saw only part of the transcript. Increase the model's context length "
                "(for Ollama, Settings > Context length, or num_ctx), then start a new run."
            )

    def _record_run_settings(self, artifact_root: Path, run_id: str) -> None:
        """Human-readable model settings for methods reporting; never includes credentials.

        Written once per run (a resumed run keeps the settings it started with).
        """
        path = artifact_root / "run_settings.json"
        if path.exists():
            return
        from qualframe import __version__

        settings = self.project.provider.model_dump(exclude={"api_key_env"})
        path.write_text(json.dumps({
            "run_id": run_id,
            "qualframe_version": __version__,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "provider": settings,
            "method_id": self.method.id if self.method else None,
            "codebook_id": self.codebook.id if self.codebook else None,
            "codebook_version": self.codebook.version if self.codebook else None,
        }, indent=2), encoding="utf-8")

    def _make_run_id(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _generic_codebook_partitions(self, stage: StageSpec) -> dict[str, str]:
        if (
            stage.domain_iterations
            or stage.input_source != "raw_transcripts"
            or not stage.use_codebook
            or self.method is None
            or self.codebook is None
        ):
            return {}
        groups = partition_codebook(self.codebook, self.method.partitioning)
        return {
            group_name: self.codebook.model_copy(update={"codes": entries}).model_dump_json(
                indent=2
            )
            for group_name, entries in groups.items()
        }

    def _method_policy_instruction(self, partition_name: str) -> str:
        if self.method is None:
            return ""
        coding = (
            "Assign exactly one code per meaning unit."
            if self.method.coding.cardinality == "single_label"
            else "Multiple code assignments per meaning unit are permitted when supported."
        )
        overlap = (
            "Evidence spans may overlap."
            if self.method.coding.allow_overlapping_spans
            else "Do not return overlapping evidence spans."
        )
        return (
            "Configured analysis policy:\n"
            f"- Segmentation strategy: {self.method.segmentation.strategy}.\n"
            f"- Context window: {self.method.context.before} {self.method.context.unit} before and "
            f"{self.method.context.after} {self.method.context.unit} after the exact evidence.\n"
            f"- {coding}\n- {overlap}\n"
            f"- Codebook partition for this request: {partition_name}."
        )

    def _previous_llm_stage(self, current_stage: StageSpec) -> StageSpec | None:
        """Return the last enabled stage with a prompt_ref before current_stage."""
        prev = None
        for s in self.pipeline.stages:
            if s.id == current_stage.id:
                break
            if s.enabled and s.prompt_ref:
                prev = s
        return prev

    def _bundle_inputs(self, inputs: list[tuple[str, str]]) -> str:
        """Concatenate multiple (label, text) inputs with clear separators."""
        parts = [f"### Source: {label}\n\n{text}" for label, text in inputs]
        return "\n\n---\n\n".join(parts)

    def _network_for_label(self, label: str) -> str:
        """Return the AMN network for a transcript label path.

        Expects paths like ``data/raw/transcripts/ON AMN/1A_....docx``.
        Returns the immediate parent folder name (e.g. ``ON AMN``), or
        ``_ungrouped`` if the path has no recognisable network subfolder.
        """
        norm_label = label.replace("\\", "/")
        transcripts_rel = self.project.paths.get("raw_transcripts", "data/raw/transcripts").replace("\\", "/")
        try:
            rel = Path(norm_label).relative_to(transcripts_rel)
            if len(rel.parts) >= 2:
                return rel.parts[0]
        except ValueError:
            pass
        parent = Path(norm_label).parent.name
        return parent if parent else "_ungrouped"

    def _load_reference_file(self, name_stem: str) -> str | None:
        """Return the text content of a reference file matching name_stem (no extension).

        Searches ``data/reference/`` for ``<name_stem>.xlsx``, ``.docx``, ``.txt``, or ``.md``.
        Returns None if not found.
        """
        ref_dir = resolve_repo_path(self.repo_root, self.project.paths.get("reference", "data/reference"))
        for ext in (".xlsx", ".docx", ".txt", ".md"):
            candidate = ref_dir / f"{name_stem}{ext}"
            if candidate.exists():
                if ext == ".xlsx":
                    return codebook_xlsx_to_text(candidate)
                if ext == ".docx":
                    return transcript_to_text(candidate)
                return candidate.read_text(encoding="utf-8", errors="replace")
        return None

    def _transcript_files(self) -> list[Path]:
        """Return all discovered transcript files across network subfolders."""
        transcripts_dir = resolve_repo_path(
            self.repo_root, self.project.paths.get("raw_transcripts", "data/raw/transcripts")
        )
        grouped = discover_transcripts(transcripts_dir)
        files = [f for files in grouped.values() for f in files]
        if self.transcript_sample:
            files = [f for f in files if f.relative_to(self.repo_root).as_posix() in self.transcript_sample]
        return files

    def _load_existing_artifact(self, artifact_path: Path) -> StageArtifact | None:
        """Return a StageArtifact loaded from disk, or None if the file does not exist."""
        if not artifact_path.exists():
            return None
        artifact = StageArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        contract_hash = scoped_contract_sha256(self.structured_output_spec)
        if contract_hash is not None and (
            artifact.structured_output_contract_sha256 != contract_hash
            or artifact.structured_output_schema_id != self.structured_output_spec.id
            or artifact.structured_output_valid is None
        ):
            raise ValueError(
                "Existing artifact was not validated under this scoped output contract. "
                "Use a new run ID; prior artifacts remain unchanged."
            )
        return artifact

    def _check_scoped_run_reuse(self, artifact_root: Path, plan: RunPlan) -> None:
        """Check before writing a plan or dispatching; opt-in contracts cannot adopt old runs."""
        if scoped_contract_sha256(self.structured_output_spec) is None:
            return
        if plan.configuration_fingerprint != self.configuration_lock.fingerprint_sha256:
            raise ValueError("Scoped output contracts require the current configuration-bound plan.")
        for filename, field in (
            ("run_plan.json", "configuration_fingerprint"),
            ("analysis_configuration_lock.json", "fingerprint_sha256"),
            ("run_manifest.json", "configuration_fingerprint"),
        ):
            path = artifact_root / filename
            if path.exists():
                stored = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(stored, dict) or stored.get(field) != plan.configuration_fingerprint:
                    raise ValueError(
                        "Existing run uses a different or unknown configuration. "
                        "Use a new run ID for the scoped contract; prior files remain unchanged."
                    )
        for path in sorted(artifact_root.glob("*/*_artifact.json")):
            self._load_existing_artifact(path)

    def _load_stage_outputs_from_disk(self, stage_id: str, artifact_root: Path) -> list[tuple[str, str]]:
        """Load (input_path, response_text) pairs for a stage from saved artifacts on disk.

        Used as a fallback when a previous stage was not executed in the current run
        (e.g. filtered out with --stage) but its artifacts already exist.
        """
        stage_dir = artifact_root / stage_id
        if not stage_dir.exists():
            return []
        outputs: list[tuple[str, str]] = []
        for artifact_path in sorted(stage_dir.glob("*_artifact.json")):
            artifact = self._load_existing_artifact(artifact_path)
            if artifact:
                outputs.append((artifact.input_path, artifact.response_text))
        return outputs

    def _filter_outputs_by_transcript(
        self,
        outputs: list[tuple[str, str]],
        transcript_filter: str | None,
    ) -> list[tuple[str, str]]:
        """Return only previous-stage outputs for the requested participant."""
        if not transcript_filter:
            return outputs
        return [(label, text) for label, text in outputs if (Path(label).stem == transcript_filter or participant_id(label) == transcript_filter)]

    def _save_artifact(
        self,
        artifact: StageArtifact,
        artifact_path: Path,
        artifact_root: Path,
        artifact_paths: list[str],
    ) -> None:
        if self.method is not None:
            artifact.evidence_location = self.method.evidence_location
        if self.structured_output_spec is not None:
            issues = validate_stage_output(
                artifact.stage_id, artifact.parsed_output, self.structured_output_spec,
            )
            artifact.structured_output_schema_id = self.structured_output_spec.id
            artifact.structured_output_contract_sha256 = scoped_contract_sha256(self.structured_output_spec)
            artifact.structured_output_valid = not issues
            artifact.structured_output_issues = issues
            if issues:
                self._structured_output_failure_count += 1
        artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        artifact_paths.append(str(artifact_path.relative_to(artifact_root)))

    def _artifact_qa(self, artifact: StageArtifact) -> list[ReviewQueueItem]:
        """Evaluate a saved artifact without rewriting it; fresh and resumed QA agree."""
        failures = []
        if artifact.structured_output_valid is False:
            failures.append(ReviewQueueItem(
                run_id=artifact.run_id, stage_id=artifact.stage_id,
                rule_id="structured_output_schema", row_index=None,
                row_data={"input_path": artifact.input_path},
                reason=" ".join(artifact.structured_output_issues)
                or "Stored artifact failed structured-output validation.",
            ))
        if self.method is not None and self.codebook is not None and artifact.parsed_output:
            issues = parsed_assignment_policy_issues(artifact.parsed_output, self.method, self.codebook)
            if issues:
                failures.append(ReviewQueueItem(
                    run_id=artifact.run_id, stage_id=artifact.stage_id,
                    rule_id="directed_method_policy", row_index=None,
                    row_data={"input_path": artifact.input_path}, reason=" ".join(issues),
                ))
        failures.extend(self._run_qa(artifact))
        return failures

    def validate_inputs(self) -> list[WorkbookValidationResult]:
        """Validate all discovered workbooks against the framework's domain and column requirements."""
        raw_workbooks_dir = resolve_repo_path(self.repo_root, self.project.paths["raw_workbooks"])
        return [
            validate_workbook(wb, REQUIRED_COLUMNS, self.framework.domains)
            for wb in discover_workbooks(raw_workbooks_dir)
        ]

    def build_run_plan(self) -> RunPlan:
        raw_workbooks_dir = resolve_repo_path(self.repo_root, self.project.paths["raw_workbooks"])
        discovered_files = discover_workbooks(raw_workbooks_dir)
        discovered_inputs = [
            DiscoveredInput(
                path=str(path.relative_to(self.repo_root)),
                kind="workbook",
                sha256=sha256_for_file(path),
            )
            for path in discovered_files
        ]

        transcript_files = self._transcript_files()  # single scan

        if self.pipeline.mode == "transcript_first":
            for t in transcript_files:
                discovered_inputs.append(DiscoveredInput(
                    path=str(t.relative_to(self.repo_root)),
                    kind="transcript",
                    sha256=sha256_for_file(t),
                ))

        planned_stage_runs: list[PlannedStageRun] = []
        for stage in self.pipeline.stages:
            if not stage.enabled:
                continue

            if stage.domain_iterations:
                for t in transcript_files:
                    rel = str(t.relative_to(self.repo_root))
                    for domain in self.framework.domains:
                        planned_stage_runs.append(PlannedStageRun(
                            stage_id=stage.id,
                            input_path=rel,
                            output_hint=f"artifacts/<run_id>/{stage.id}/{t.stem}_{domain}.json",
                            prompt_ref=stage.prompt_ref,
                            review_gate=stage.review_gate,
                            domain=domain,
                        ))
            elif stage.input_source == "raw_transcripts":
                if stage.input_grouping == "per_file":
                    partitions = self._generic_codebook_partitions(stage)
                    for transcript in transcript_files:
                        if partitions:
                            for partition_name in partitions:
                                planned_stage_runs.append(PlannedStageRun(
                                    stage_id=stage.id,
                                    input_path=str(transcript.relative_to(self.repo_root)),
                                    output_hint=(
                                        f"artifacts/<run_id>/{stage.id}/"
                                        f"{transcript.stem}_{partition_name}.json"
                                    ),
                                    prompt_ref=stage.prompt_ref,
                                    review_gate=stage.review_gate,
                                    domain=partition_name,
                                ))
                        else:
                            planned_stage_runs.append(PlannedStageRun(
                                stage_id=stage.id,
                                input_path=str(transcript.relative_to(self.repo_root)),
                                output_hint=(
                                    f"artifacts/<run_id>/{stage.id}/"
                                    f"{transcript.stem}_{stage.output_kind}.json"
                                ),
                                prompt_ref=stage.prompt_ref,
                                review_gate=stage.review_gate,
                            ))
                else:
                    planned_stage_runs.append(PlannedStageRun(
                        stage_id=stage.id,
                        input_path="transcript_bundle",
                        input_paths=[
                            str(transcript.relative_to(self.repo_root))
                            for transcript in transcript_files
                        ],
                        output_hint=f"artifacts/<run_id>/{stage.id}/bundle_{stage.output_kind}.json",
                        prompt_ref=stage.prompt_ref,
                        review_gate=stage.review_gate,
                    ))
            elif stage.input_source == "raw_workbooks":
                if stage.input_grouping == "per_file":
                    for wb in discovered_files:
                        planned_stage_runs.append(PlannedStageRun(
                            stage_id=stage.id,
                            input_path=str(wb.relative_to(self.repo_root)),
                            output_hint=f"artifacts/<run_id>/{stage.id}/{wb.stem}_{stage.output_kind}.json",
                            prompt_ref=stage.prompt_ref,
                            review_gate=stage.review_gate,
                        ))
                else:  # bundle_all
                    planned_stage_runs.append(PlannedStageRun(
                        stage_id=stage.id,
                        input_path="bundle",
                        input_paths=[str(wb.relative_to(self.repo_root)) for wb in discovered_files],
                        output_hint=f"artifacts/<run_id>/{stage.id}/bundle_{stage.output_kind}.json",
                        prompt_ref=stage.prompt_ref,
                        review_gate=stage.review_gate,
                    ))
            else:  # previous_stage
                prev = self._previous_llm_stage(stage)
                planned_stage_runs.append(PlannedStageRun(
                    stage_id=stage.id,
                    input_path=f"outputs_from:{prev.id}" if prev else "unknown",
                    output_hint=f"artifacts/<run_id>/{stage.id}/chained_{stage.output_kind}.json",
                    prompt_ref=stage.prompt_ref,
                    review_gate=stage.review_gate,
                ))

        return RunPlan(
            project_id=self.project.project_id,
            framework_id=self.framework.id,
            pipeline_id=self.pipeline.id,
            method_id=self.method.id if self.method else None,
            codebook_id=self.codebook.id if self.codebook else None,
            configuration_fingerprint=self.configuration_lock.fingerprint_sha256,
            mode=self.pipeline.mode,
            discovered_inputs=discovered_inputs,
            planned_stage_runs=planned_stage_runs,
            transcript_sample=sorted(self.transcript_sample) if self.transcript_sample else None,
        )

    def save_run_plan(self, plan: RunPlan, run_id: str) -> Path:
        artifact_root = resolve_repo_path(self.repo_root, self.project.paths["artifacts"]) / run_id
        self._check_scoped_run_reuse(artifact_root, plan)
        artifact_root.mkdir(parents=True, exist_ok=True)
        out_path = artifact_root / "run_plan.json"
        out_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        write_configuration_lock(
            self.configuration_lock,
            artifact_root / "analysis_configuration_lock.json",
        )
        return out_path

    def execute_run_plan(
        self,
        plan: RunPlan,
        run_id: str,
        stage_filter: list[str] | None = None,
        transcript_filter: str | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> Path:
        """Execute all planned stage runs with LLM calls and save artifacts.

        Args:
            stage_filter: If set, only stages whose id is in this list are executed.
            transcript_filter: If set, only transcripts whose participant ID matches
                are processed (useful for single-transcript incremental testing).

        Returns the path to the run_manifest.json written at completion.
        """
        if plan.configuration_fingerprint:
            current = create_configuration_lock(self.project_manifest_path)
            planned_root = resolve_repo_path(self.repo_root, self.project.paths["artifacts"]) / run_id
            if current.fingerprint_sha256 != plan.configuration_fingerprint and not run_can_resume(
                    self.project_manifest_path, planned_root, plan.configuration_fingerprint):
                raise ValueError("Study configuration changed after preflight. Create a new run plan; prior runs remain unchanged.")
        if plan.transcript_sample:
            self.transcript_sample = set(plan.transcript_sample)
            if not self._transcript_files():
                raise ValueError("None of the sampled transcripts are in the study; no request was sent.")
        if transcript_filter and not any(
            path.stem == transcript_filter or participant_id(path) == transcript_filter
            for path in self._transcript_files()
        ):
            raise ValueError("Transcript filter matched no sources; no request was sent.")
        artifact_root = resolve_repo_path(self.repo_root, self.project.paths["artifacts"]) / run_id
        self._check_scoped_run_reuse(artifact_root, plan)
        provider = build_provider(self.project.provider)
        prompt_set_path = resolve_repo_path(self.repo_root, self.framework.prompt_set)
        artifact_root.mkdir(parents=True, exist_ok=True)
        self._record_run_settings(artifact_root, run_id)
        cost_controller = self._build_cost_controller(
            run_id=run_id,
            artifact_root=artifact_root,
        )
        review_queue_root = resolve_repo_path(self.repo_root, self.project.paths["review_queue"]) / run_id

        workbook_files = discover_workbooks(
            resolve_repo_path(self.repo_root, self.project.paths["raw_workbooks"])
        )
        transcript_files = self._transcript_files()  # single filesystem scan
        codebook_text = (
            self.codebook.model_dump_json(indent=2)
            if self.codebook is not None
            else self._load_reference_file("codebook")
        )
        codebook_label = (
            f"{self.codebook.name} Codebook"
            if self.codebook is not None
            else "CFIR Construct Code Book"
        )

        stage_outputs: dict[str, list[tuple[str, str]]] = {}
        artifact_paths: list[str] = []
        self._structured_output_failure_count = 0
        enforce_gates = self.project.governance.enforce_review_gates
        approved_gates = approved_gate_ids(artifact_root) if enforce_gates else set()
        pending_gate: str | None = None

        for stage_index, stage in enumerate(self.pipeline.stages):
            if not stage.enabled or not stage.prompt_ref:
                continue
            if stage_filter and stage.id not in stage_filter:
                continue
            if enforce_gates:
                prior_unapproved = next(
                    (
                        prior
                        for prior in self.pipeline.stages[:stage_index]
                        if prior.enabled
                        and prior.prompt_ref
                        and prior.review_gate
                        and prior.id not in approved_gates
                    ),
                    None,
                )
                if prior_unapproved:
                    pending_gate = prior_unapproved.id
                    break
            if progress_callback:
                progress_callback(stage.id)

            prompt_text = get_prompt_text(prompt_set_path, stage.prompt_ref, self.repo_root)
            prompt_sha = sha256_for_text(prompt_text)
            stage_dir = artifact_root / stage.id
            stage_dir.mkdir(parents=True, exist_ok=True)

            codebook_suffix = (
                f"\n\n---\n\n{codebook_label}:\n\n{codebook_text}"
                if stage.use_codebook and codebook_text
                else ""
            )

            # --- domain_iterations: one LLM call per (transcript, domain); compile into one artifact ---
            if stage.domain_iterations:
                active_transcripts = [
                    t for t in transcript_files
                    if not transcript_filter or (t.stem == transcript_filter or participant_id(t) == transcript_filter)
                ]
                run_outputs: list[tuple[str, str]] = []
                for transcript_path in active_transcripts:
                    label = str(transcript_path.relative_to(self.repo_root))
                    artifact_path = stage_dir / f"{transcript_path.stem}_artifact.json"
                    existing = self._load_existing_artifact(artifact_path)
                    if existing:
                        if (
                            self.structured_output_spec is not None
                            and existing.structured_output_valid is False
                        ):
                            self._structured_output_failure_count += 1
                        artifact_paths.append(str(artifact_path.relative_to(artifact_root)))
                        run_outputs.append((label, existing.response_text))
                        continue

                    transcript_text = transcript_to_text(transcript_path)
                    compiled_output: dict[str, list[dict]] = {}
                    domain_response_texts: list[str] = []

                    for domain in self.framework.domains:
                        domain_prompt = prompt_text.replace("{CFIR_DOMAIN}", domain)
                        parts = [domain_prompt, "---", f"Transcript:\n\n{transcript_text}"]
                        if codebook_suffix:
                            parts.append(f"{codebook_label}:\n\n{codebook_text}")
                        user_prompt = "\n\n".join(parts)
                        response = self._complete(
                            provider=provider,
                            cost_controller=cost_controller,
                            stage_id=stage.id,
                            input_label=f"{label}::{domain}",
                            user_prompt=user_prompt,
                        )
                        domain_parsed = parse_markdown_tables(response.text)
                        domain_rows = (
                            domain_parsed.get(domain)
                            or domain_parsed.get("output")
                            or (next(iter(domain_parsed.values())) if domain_parsed else [])
                        )
                        compiled_output[domain] = domain_rows
                        domain_response_texts.append(f"## Sheet: {domain}\n\n{response.text}")

                    compiled_text = "\n\n".join(domain_response_texts)
                    artifact = StageArtifact(
                        run_id=run_id, stage_id=stage.id, input_path=label,
                        input_sha256=sha256_for_file(transcript_path),
                        prompt_ref=stage.prompt_ref, prompt_sha256=prompt_sha,
                        response_text=compiled_text, model=response.model, provider=response.provider,
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        parsed_output=compiled_output,
                    )
                    self._save_artifact(
                        artifact, stage_dir / f"{transcript_path.stem}_artifact.json",
                        artifact_root, artifact_paths,
                    )
                    run_outputs.append((label, compiled_text))
                stage_outputs[stage.id] = run_outputs
                if self._structured_output_failure_count:
                    break
                if enforce_gates and stage.review_gate and stage.id not in approved_gates:
                    pending_gate = stage.id
                    break
                continue

            # --- group_by_network: one LLM call per AMN network from previous stage outputs ---
            if stage.group_by_network:
                prev = self._previous_llm_stage(stage)
                prev_id = prev.id if prev else ""
                all_prev: list[tuple[str, str]] = (
                    stage_outputs.get(prev_id)
                    or self._load_stage_outputs_from_disk(prev_id, artifact_root)
                )
                all_prev = self._filter_outputs_by_transcript(all_prev, transcript_filter)
                network_inputs: dict[str, list[tuple[str, str]]] = {}
                for label, text in all_prev:
                    network_inputs.setdefault(self._network_for_label(label), []).append((label, text))

                network_run_outputs: list[tuple[str, str]] = []
                for network, net_inputs in sorted(network_inputs.items()):
                    artifact_path = stage_dir / f"{network.replace(' ', '_')}_artifact.json"
                    existing = self._load_existing_artifact(artifact_path)
                    if existing:
                        if (
                            self.structured_output_spec is not None
                            and existing.structured_output_valid is False
                        ):
                            self._structured_output_failure_count += 1
                        artifact_paths.append(str(artifact_path.relative_to(artifact_root)))
                        network_run_outputs.append((network, existing.response_text))
                        continue

                    bundle_text = self._bundle_inputs(net_inputs)
                    user_prompt = f"{prompt_text}\n\n---\n\nInput data:\n\n{bundle_text}{codebook_suffix}"
                    response = self._complete(
                        provider=provider,
                        cost_controller=cost_controller,
                        stage_id=stage.id,
                        input_label=network,
                        user_prompt=user_prompt,
                    )
                    artifact = StageArtifact(
                        run_id=run_id, stage_id=stage.id,
                        input_path=f"{network}({len(net_inputs)} participants)",
                        input_sha256=sha256_for_text(bundle_text),
                        prompt_ref=stage.prompt_ref, prompt_sha256=prompt_sha,
                        response_text=response.text, model=response.model, provider=response.provider,
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        parsed_output=parse_markdown_tables(response.text) or None,
                    )
                    self._save_artifact(
                        artifact, stage_dir / f"{network.replace(' ', '_')}_artifact.json",
                        artifact_root, artifact_paths,
                    )
                    network_run_outputs.append((network, response.text))
                stage_outputs[stage.id] = network_run_outputs
                if self._structured_output_failure_count:
                    break
                if enforce_gates and stage.review_gate and stage.id not in approved_gates:
                    pending_gate = stage.id
                    break
                continue

            # --- resolve inputs for bundle_all / per_file ---
            if stage.input_source == "previous_stage":
                prev = self._previous_llm_stage(stage)
                prev_id = prev.id if prev else ""
                inputs: list[tuple[str, str]] = (
                    stage_outputs.get(prev_id)
                    or self._load_stage_outputs_from_disk(prev_id, artifact_root)
                )
                inputs = self._filter_outputs_by_transcript(inputs, transcript_filter)
            elif stage.input_source == "raw_transcripts":
                inputs = [
                    (str(transcript.relative_to(self.repo_root)), transcript_to_text(transcript))
                    for transcript in transcript_files
                    if not transcript_filter or (transcript.stem == transcript_filter or participant_id(transcript) == transcript_filter)
                ]
            else:
                inputs = [
                    (str(wb.relative_to(self.repo_root)), workbook_to_text(wb))
                    for wb in workbook_files
                ]

            if stage.input_grouping == "bundle_all":
                artifact_path = stage_dir / "bundle_artifact.json"
                existing = self._load_existing_artifact(artifact_path)
                if existing:
                    if (
                        self.structured_output_spec is not None
                        and existing.structured_output_valid is False
                    ):
                        self._structured_output_failure_count += 1
                    artifact_paths.append(str(artifact_path.relative_to(artifact_root)))
                    stage_outputs[stage.id] = [("bundle", existing.response_text)]
                    if self._structured_output_failure_count:
                        break
                    if enforce_gates and stage.review_gate and stage.id not in approved_gates:
                        pending_gate = stage.id
                        break
                    continue

                bundle_text = self._bundle_inputs(inputs)
                user_prompt = f"{prompt_text}\n\n---\n\nInput data:\n\n{bundle_text}{codebook_suffix}"
                response = self._complete(
                    provider=provider,
                    cost_controller=cost_controller,
                    stage_id=stage.id,
                    input_label=f"bundle({len(inputs)} inputs)",
                    user_prompt=user_prompt,
                )
                artifact = StageArtifact(
                    run_id=run_id, stage_id=stage.id,
                    input_path=f"bundle({len(inputs)} inputs)",
                    input_sha256=sha256_for_text(bundle_text),
                    prompt_ref=stage.prompt_ref, prompt_sha256=prompt_sha,
                    response_text=response.text, model=response.model, provider=response.provider,
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    parsed_output=parse_markdown_tables(response.text) or None,
                )
                self._save_artifact(
                    artifact, stage_dir / "bundle_artifact.json",
                    artifact_root, artifact_paths,
                )
                stage_outputs[stage.id] = [("bundle", response.text)]

            else:  # per_file
                run_outputs = []
                for label, input_text in inputs:
                    artifact_path = stage_dir / f"{Path(label).stem}_artifact.json"
                    existing = self._load_existing_artifact(artifact_path)
                    if existing:
                        if (
                            self.structured_output_spec is not None
                            and existing.structured_output_valid is False
                        ):
                            self._structured_output_failure_count += 1
                        artifact_paths.append(str(artifact_path.relative_to(artifact_root)))
                        run_outputs.append((label, existing.response_text))
                        continue

                    generic_partitions = self._generic_codebook_partitions(stage)
                    if generic_partitions:
                        partition_texts: list[str] = []
                        combined_parsed: dict[str, list[dict[str, str]]] = {}
                        for partition_name, partition_codebook_text in generic_partitions.items():
                            method_instruction = self._method_policy_instruction(
                                partition_name
                            )
                            user_prompt = (
                                f"{prompt_text}\n\n---\n\n{method_instruction}"
                                f"\n\n---\n\nTranscript:\n\n{input_text}"
                                f"\n\n---\n\n{codebook_label}:\n\n"
                                f"{partition_codebook_text}"
                            )
                            schema = None
                            if '"codings"' in prompt_text and self.project.provider.name in {"openai", "anthropic"}:
                                partition_ids = [
                                    str(code.get("id")) for code in json.loads(partition_codebook_text).get("codes", [])
                                ]
                                schema = coding_response_schema(partition_ids)
                            response = self._complete(
                                provider=provider,
                                cost_controller=cost_controller,
                                stage_id=stage.id,
                                input_label=f"{label}::{partition_name}",
                                user_prompt=user_prompt,
                                response_schema=schema,
                            )
                            parsed_partition = parse_model_output(response.text)
                            if len(generic_partitions) == 1:
                                combined_parsed.update(parsed_partition)
                                partition_texts.append(response.text)
                            else:
                                for sheet, rows in parsed_partition.items():
                                    combined_parsed[f"{partition_name}: {sheet}"] = rows
                                partition_texts.append(
                                    f"## Partition: {partition_name}\n\n{response.text}"
                                )
                        response_text = "\n\n".join(partition_texts)
                        parsed_output = combined_parsed or None
                    elif stage.include_original_transcript:
                        transcript_text = transcript_to_text(self.repo_root / label)
                        user_prompt = (
                            f"{prompt_text}\n\n---\n\nRollup document:\n\n{input_text}"
                            f"\n\n---\n\nOriginal transcript:\n\n{transcript_text}{codebook_suffix}"
                        )
                        response = self._complete(
                            provider=provider,
                            cost_controller=cost_controller,
                            stage_id=stage.id,
                            input_label=label,
                            user_prompt=user_prompt,
                        )
                        response_text = response.text
                        parsed_output = parse_markdown_tables(response.text) or None
                    else:
                        input_label = (
                            "Transcript" if stage.input_source == "raw_transcripts" else "Workbook data"
                        )
                        user_prompt = (
                            f"{prompt_text}\n\n---\n\n{input_label}:\n\n"
                            f"{input_text}{codebook_suffix}"
                        )
                        response = self._complete(
                            provider=provider,
                            cost_controller=cost_controller,
                            stage_id=stage.id,
                            input_label=label,
                            user_prompt=user_prompt,
                        )
                        response_text = response.text
                        parsed_output = parse_model_output(response.text) or None
                    input_sha = (
                        sha256_for_file(self.repo_root / label)
                        if stage.input_source == "raw_workbooks"
                        else sha256_for_text(input_text)
                    )
                    artifact = StageArtifact(
                        run_id=run_id, stage_id=stage.id, input_path=label,
                        input_sha256=input_sha,
                        prompt_ref=stage.prompt_ref, prompt_sha256=prompt_sha,
                        response_text=response_text, model=response.model, provider=response.provider,
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                        parsed_output=parsed_output,
                    )
                    self._save_artifact(
                        artifact, stage_dir / f"{Path(label).stem}_artifact.json",
                        artifact_root, artifact_paths,
                    )
                    run_outputs.append((label, response_text))
                stage_outputs[stage.id] = run_outputs

            if self._structured_output_failure_count:
                break
            if enforce_gates and stage.review_gate and stage.id not in approved_gates:
                pending_gate = stage.id
                break

        qa = write_run_qa_inventory(
            run_id=run_id, artifact_root=artifact_root, review_root=review_queue_root,
            artifact_paths=artifact_paths, evaluate=self._artifact_qa,
        )
        artifact_paths = qa["artifact_paths"]
        self._structured_output_failure_count = (
            qa["structured_output_failure_count"] if self.structured_output_spec is not None else 0
        )

        manifest = RunManifest(
            run_id=run_id,
            project_id=plan.project_id,
            framework_id=plan.framework_id,
            pipeline_id=plan.pipeline_id,
            method_id=plan.method_id,
            codebook_id=plan.codebook_id,
            configuration_fingerprint=plan.configuration_fingerprint,
            configuration_assets=self.configuration_lock.assets,
            completed_at_utc=datetime.now(timezone.utc).isoformat(),
            artifact_paths=artifact_paths,
            qa_failure_count=qa["qa_failure_count"],
            qa_inventory_path=qa["qa_inventory_path"],
            qa_inventory_sha256=qa["qa_inventory_sha256"],
            status=(
                "blocked_validation"
                if self._structured_output_failure_count
                else "awaiting_review" if pending_gate else "completed"
            ),
            pending_gate=pending_gate,
            approved_gates=sorted(approved_gates),
            release_status="unreleased" if enforce_gates else "not_required",
            structured_output_failure_count=self._structured_output_failure_count,
            run_cost_usd=(
                cost_controller.run_cost_usd() if cost_controller is not None else None
            ),
            project_cost_usd=(
                cost_controller.project_cost_usd()
                if cost_controller is not None
                else None
            ),
            cost_ledger_path=(
                str(cost_controller.ledger_path.relative_to(self.repo_root))
                if cost_controller is not None
                else None
            ),
        )
        manifest_path = artifact_root / "run_manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest_path

    def _run_qa(self, artifact: StageArtifact) -> list[ReviewQueueItem]:
        rule = (
            self.structured_output_spec.stages.get(artifact.stage_id)
            if self.structured_output_spec is not None else None
        )
        scoped = rule is not None and rule.qa_rules is not None
        return run_qa_on_artifact(
            run_id=artifact.run_id,
            stage_id=artifact.stage_id,
            prompt_sha256=artifact.prompt_sha256,
            parsed_output=artifact.parsed_output,
            allowed_network_labels=self.framework.network_labels,
            required_columns=rule.required_columns if scoped else self.framework.required_columns or REQUIRED_COLUMNS,
            enabled_rules=rule.qa_rules if scoped else self.framework.qa_rules,
        )
