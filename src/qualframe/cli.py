from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env", override=False)

from qualframe.config import (
    load_analysis_plan_spec,
    load_codebook_spec,
    load_cost_policy_spec,
    load_disagreement_spec,
    load_framework_spec,
    load_method_spec,
    load_pipeline_spec,
    load_project_manifest,
    load_prompt_set,
    load_pricing_snapshot_spec,
    load_review_policy_spec,
    resolve_repo_path,
)
from qualframe.configuration_lock import create_configuration_lock
from qualframe.cost_control import (
    CostApprovalRequired,
    CostLimitExceeded,
    append_cost_approval,
)
from qualframe.adjudication import append_adjudication_action
from qualframe.dashboard import serve_dashboard
from qualframe.governance import append_gate_action, append_release_action, approved_gate_ids
from qualframe.io.export import export_run
from qualframe.io.transcript_io import participant_id
from qualframe.models import CostPauseRecord, StageArtifact
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.prompts import list_prompt_files
from qualframe.qa.disagreement import detect_disagreements, write_disagreement_records

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("validate-config")
def validate_config(project_yaml: Path) -> None:
    """Validate the project and every configured analysis asset."""
    project = load_project_manifest(project_yaml.resolve())
    repo_root = project_yaml.resolve().parents[2]

    framework_path = resolve_repo_path(repo_root, project.framework)
    pipeline_path = resolve_repo_path(repo_root, project.pipeline)

    framework = load_framework_spec(framework_path)
    pipeline = load_pipeline_spec(pipeline_path)

    if not framework.prompt_set:
        raise typer.BadParameter("Framework spec does not define a prompt_set.")
    prompt_set_path = resolve_repo_path(repo_root, framework.prompt_set)
    prompt_set = load_prompt_set(prompt_set_path)

    optional_assets = [
        ("Method", project.method, load_method_spec),
        ("Codebook", project.codebook, load_codebook_spec),
        ("Review policy", project.review_policy, load_review_policy_spec),
        ("Analysis plan", project.analysis_plan, load_analysis_plan_spec),
        ("Cost policy", project.cost_policy, load_cost_policy_spec),
        ("Pricing snapshot", project.pricing_snapshot, load_pricing_snapshot_spec),
    ]
    loaded_optional: list[tuple[str, object]] = []
    for label, configured_path, loader in optional_assets:
        if configured_path:
            loaded_optional.append(
                (label, loader(resolve_repo_path(repo_root, configured_path)))
            )
    configuration_lock = create_configuration_lock(project_yaml.resolve())

    console.print("[green]Config OK[/green]")
    console.print(f"Project: {project.project_id}")
    console.print(f"Framework: {framework.id}")
    console.print(f"Pipeline: {pipeline.id}")
    console.print(f"Prompt set: {prompt_set.id}")
    for label, asset in loaded_optional:
        console.print(f"{label}: {getattr(asset, 'id')}")
    console.print(f"Configuration: {configuration_lock.fingerprint_sha256}")


@app.command("list-prompts")
def list_prompts(prompt_set_yaml: Path) -> None:
    """List stage ids and prompt files for a prompt set."""
    prompt_files = list_prompt_files(prompt_set_yaml.resolve())
    for stage_id, file_path in prompt_files.items():
        console.print(f"{stage_id}: {file_path}")


@app.command("run")
def run(
    project_yaml: Path,
    dry_run: bool = typer.Option(True, help="Save a run plan only."),
    stage: list[str] = typer.Option([], help="Run only these stage ID(s). Repeat to include multiple. Omit to run all."),
    transcript: str = typer.Option("", help="Run only this transcript stem (e.g. 1A). Useful for incremental testing."),
    resume_run_id: str = typer.Option("", help="Resume a crashed run by reusing its run ID. Skips already-completed artifacts."),
) -> None:
    """Validate inputs, build a run plan, and optionally execute it."""
    runner = ProjectRunner(project_yaml.resolve())

    # --- validation ---
    validation_results = runner.validate_inputs()
    if not validation_results:
        if runner.pipeline.mode == "transcript_first":
            console.print("[dim]Transcript-first project — workbook validation skipped.[/dim]")
        else:
            console.print("[yellow]No workbooks found — nothing to validate.[/yellow]")
    else:
        all_valid = True
        for result in validation_results:
            label = Path(result.path).name
            if result.valid:
                console.print(f"[green]OK[/green]  {label}")
            else:
                all_valid = False
                console.print(f"[red]FAIL[/red] {label}")
                for domain in result.missing_domain_sheets:
                    console.print(f"    [red]missing sheet for domain:[/red] {domain}")
                for sheet, cols in result.column_issues.items():
                    console.print(f"    [red]missing columns in '{sheet}':[/red] {', '.join(cols)}")
        if not all_valid:
            console.print("[red]Validation failed — fix workbooks before running.[/red]")
            raise typer.Exit(code=1)
        console.print("[green]All workbooks valid.[/green]")

    # --- plan ---
    run_id = resume_run_id.strip() or runner._make_run_id()
    if resume_run_id.strip():
        console.print(f"[dim]Resuming run {run_id} — completed artifacts will be skipped.[/dim]")
    plan = runner.build_run_plan()
    plan_path = runner.save_run_plan(plan, run_id)
    console.print(f"[green]Saved run plan[/green] to {plan_path}")

    if dry_run:
        console.print(f"[dim]Dry-run complete (run_id={run_id}). Pass --no-dry-run to execute.[/dim]")
        return

    # --- execute ---
    stage_filter = list(stage) or None
    transcript_filter = transcript.strip() or None
    if stage_filter:
        console.print(f"[dim]Stage filter: {', '.join(stage_filter)}[/dim]")
    if transcript_filter:
        console.print(f"[dim]Transcript filter: {transcript_filter}[/dim]")
    active_runs = [
        r for r in plan.planned_stage_runs
        if (not stage_filter or r.stage_id in stage_filter)
        and (
            not transcript_filter
            or r.input_path.startswith("outputs_from:")
            or participant_id(r.input_path) == transcript_filter
        )
    ]
    total = len(plan.planned_stage_runs)
    shown = len(active_runs)
    suffix = f" ({total - shown} skipped by filter)" if shown < total else ""
    console.print(f"[cyan]Executing {shown} stage run(s){suffix}...[/cyan]")
    try:
        manifest_path = runner.execute_run_plan(
            plan,
            run_id,
            stage_filter=stage_filter,
            transcript_filter=transcript_filter,
        )
    except CostApprovalRequired as exc:
        console.print(
            f"[yellow]Run paused before model request at the "
            f"USD {exc.pause.threshold_usd:.2f} approval boundary.[/yellow]\n"
            f"Pause record: {exc.path}\n"
            f"Approve locally, then resume run {run_id}."
        )
        return
    except CostLimitExceeded as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    import json as _json
    manifest = _json.loads(manifest_path.read_text())
    qa_count = manifest.get("qa_failure_count", 0)
    if manifest.get("status") == "blocked_validation":
        console.print(
            "[red]Run blocked by structured-output validation.[/red]\n"
            f"Manifest: {manifest_path}"
        )
        return
    if manifest.get("status") == "awaiting_review":
        console.print(
            f"[yellow]Run paused at enforced review gate: {manifest.get('pending_gate')}[/yellow]\n"
            f"Manifest: {manifest_path}"
        )
        return
    if qa_count:
        console.print(
            f"[green]Run complete.[/green] Manifest: {manifest_path}\n"
            f"[yellow]{qa_count} QA failure(s) written to review_queue/{run_id}/[/yellow]"
        )
    else:
        console.print(f"[green]Run complete — all QA checks passed.[/green] Manifest: {manifest_path}")


@app.command("approve-cost")
def approve_cost(
    project_yaml: Path,
    run_id: str = typer.Option(..., help="Paused run ID."),
    decision: str = typer.Option(..., help="approve or stop"),
    reviewer: str = typer.Option(..., help="Reviewer identity recorded in the audit log."),
    rationale: str = typer.Option(..., help="Required decision rationale."),
) -> None:
    """Record a local decision for the cost boundary that paused a run."""
    runner = ProjectRunner(project_yaml.resolve())
    artifact_root = resolve_repo_path(
        runner.repo_root, runner.project.paths["artifacts"]
    ) / run_id
    pause_path = artifact_root / "cost_pause.json"
    if not pause_path.exists():
        raise typer.BadParameter(f"No cost pause exists for run {run_id}.")
    pause = CostPauseRecord.model_validate_json(
        pause_path.read_text(encoding="utf-8")
    )
    if pause.project_id != runner.project.project_id or pause.run_id != run_id:
        raise typer.BadParameter("Cost pause identity does not match this project and run.")
    logs_root = resolve_repo_path(
        runner.repo_root, runner.project.paths.get("logs", "logs")
    )
    try:
        action = append_cost_approval(
            logs_root / "cost_approvals.jsonl",
            project_id=pause.project_id,
            run_id=run_id,
            threshold_usd=pause.threshold_usd,
            decision=decision,
            reviewer=reviewer,
            rationale=rationale,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if action.decision == "approve":
        console.print(
            f"[green]Approved USD {action.threshold_usd:.2f} boundary[/green] "
            f"({action.action_id}). Resume run {run_id} to continue."
        )
    else:
        console.print(
            f"[yellow]Recorded stop at USD {action.threshold_usd:.2f} boundary[/yellow] "
            f"({action.action_id}). The run remains paused."
        )


@app.command("export")
def export(
    project_yaml: Path,
    run_id: str = typer.Option("", help="Run ID to export. Defaults to the latest run."),
) -> None:
    """Export parsed stage outputs from a completed run to .xlsx files."""
    runner = ProjectRunner(project_yaml.resolve())
    artifacts_dir = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    exports_dir = resolve_repo_path(runner.repo_root, runner.project.paths["exports"])

    if not run_id:
        runs = sorted(artifacts_dir.iterdir()) if artifacts_dir.exists() else []
        if not runs:
            console.print("[red]No runs found in artifacts directory.[/red]")
            raise typer.Exit(code=1)
        run_id = runs[-1].name
        console.print(f"[dim]No run_id specified — exporting latest: {run_id}[/dim]")

    artifact_root = artifacts_dir / run_id
    try:
        written = export_run(
            run_id,
            artifact_root,
            exports_dir,
            require_released=(
                runner.project.governance.enforce_review_gates
                and runner.project.governance.require_release_for_export
            ),
            require_validated=runner.project.structured_output.enforce,
        )
    except PermissionError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not written:
        console.print("[yellow]No parsed outputs found to export (run with --no-dry-run first).[/yellow]")
    else:
        console.print(f"[green]Exported {len(written)} file(s) to exports/{run_id}/[/green]")
        for path in written:
            console.print(f"  {path.name}")


@app.command("review-gate")
def review_gate(
    project_yaml: Path,
    run_id: str = typer.Option(..., help="Run ID containing the gate."),
    stage_id: str = typer.Option(..., help="Pipeline stage gate to review."),
    decision: str = typer.Option(..., help="approve or reject"),
    reviewer: str = typer.Option(..., help="Reviewer identity recorded in the audit log."),
    rationale: str = typer.Option(..., help="Required review rationale."),
) -> None:
    """Append an auditable approval or rejection for an enforced stage gate."""
    runner = ProjectRunner(project_yaml.resolve())
    if not runner.project.governance.enforce_review_gates:
        raise typer.BadParameter("This project does not enable enforced review gates.")
    stage = next((item for item in runner.pipeline.stages if item.id == stage_id), None)
    if not stage or not stage.review_gate:
        raise typer.BadParameter(f"Stage is not a configured review gate: {stage_id}")
    artifact_root = resolve_repo_path(
        runner.repo_root, runner.project.paths["artifacts"]
    ) / run_id
    stage_dir = artifact_root / stage_id
    if not any(stage_dir.glob("*_artifact.json")):
        raise typer.BadParameter("Gate cannot be reviewed before its stage artifacts exist.")
    try:
        action = append_gate_action(
            artifact_root,
            run_id=run_id,
            stage_id=stage_id,
            decision=decision,
            reviewer=reviewer,
            rationale=rationale,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(
        f"[green]Recorded {action.decision}[/green] for {stage_id} "
        f"({action.action_id}). Resume run {run_id} to continue."
    )


@app.command("release-run")
def release_run(
    project_yaml: Path,
    run_id: str = typer.Option(..., help="Completed run ID to release."),
    reviewer: str = typer.Option(..., help="Reviewer identity recorded in the audit log."),
    rationale: str = typer.Option(..., help="Required release rationale."),
) -> None:
    """Release a completed governed run for export."""
    runner = ProjectRunner(project_yaml.resolve())
    if not runner.project.governance.enforce_review_gates:
        raise typer.BadParameter("This project does not enable enforced review gates.")
    artifact_root = resolve_repo_path(
        runner.repo_root, runner.project.paths["artifacts"]
    ) / run_id
    required_gates = {
        stage.id
        for stage in runner.pipeline.stages
        if stage.enabled and stage.prompt_ref and stage.review_gate
    }
    missing = sorted(required_gates - approved_gate_ids(artifact_root))
    if missing:
        raise typer.BadParameter("Unapproved gates remain: " + ", ".join(missing))
    try:
        action = append_release_action(
            artifact_root,
            run_id=run_id,
            reviewer=reviewer,
            rationale=rationale,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]Run released[/green] ({action.action_id}). Export is now allowed.")


@app.command("detect-disagreements")
def detect_disagreement_command(
    project_yaml: Path,
    run_id: str = typer.Option(..., help="Run ID receiving the disagreement records."),
    left_artifact: Path = typer.Option(..., help="First artifact path relative to the run folder."),
    right_artifact: Path = typer.Option(..., help="Second artifact path relative to the run folder."),
    spec_yaml: Path = typer.Option(
        Path("config/disagreement/cfir_default.yaml"),
        help="Versioned disagreement specification.",
    ),
) -> None:
    """Compare two structured artifacts and route unresolved differences for review."""
    runner = ProjectRunner(project_yaml.resolve())
    artifact_root = (
        resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"]) / run_id
    ).resolve()

    def resolve_artifact(label: Path) -> Path:
        candidate = (artifact_root / label).resolve()
        if not candidate.is_relative_to(artifact_root):
            raise typer.BadParameter("Artifact path must remain inside the selected run folder.")
        if not candidate.exists():
            raise typer.BadParameter(f"Artifact not found: {label}")
        return candidate

    left_path = resolve_artifact(left_artifact)
    right_path = resolve_artifact(right_artifact)
    spec_path = spec_yaml if spec_yaml.is_absolute() else runner.repo_root / spec_yaml
    spec = load_disagreement_spec(spec_path.resolve())
    left = StageArtifact.model_validate_json(left_path.read_text(encoding="utf-8"))
    right = StageArtifact.model_validate_json(right_path.read_text(encoding="utf-8"))
    try:
        records = detect_disagreements(
            run_id=run_id,
            left=left,
            right=right,
            left_label=str(left_path.relative_to(artifact_root)),
            right_label=str(right_path.relative_to(artifact_root)),
            spec=spec,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    review_dir = resolve_repo_path(
        runner.repo_root, runner.project.paths["review_queue"]
    ) / run_id
    written = write_disagreement_records(records, review_dir)
    console.print(
        f"[green]Detected {len(records)} disagreement(s).[/green] "
        f"Wrote {len(written)} pending review record(s)."
    )


@app.command("adjudicate")
def adjudicate_command(
    project_yaml: Path,
    run_id: str = typer.Option(..., help="Run ID containing the review item."),
    item: Path = typer.Option(..., help="Review-item path relative to the run review queue."),
    decision: str = typer.Option(..., help="approve, edit, reject, or defer"),
    reviewer: str = typer.Option(..., help="Reviewer identity recorded in the audit log."),
    rationale: str = typer.Option(..., help="Required decision rationale."),
    edited_row_json: str = typer.Option("", help="JSON object required only for an edit decision."),
) -> None:
    """Append an auditable adjudication action without modifying the review item."""
    import json as _json

    runner = ProjectRunner(project_yaml.resolve())
    review_dir = resolve_repo_path(
        runner.repo_root, runner.project.paths["review_queue"]
    ) / run_id
    artifact_root = resolve_repo_path(
        runner.repo_root, runner.project.paths["artifacts"]
    ) / run_id
    edited_row = None
    if edited_row_json:
        try:
            edited_row = _json.loads(edited_row_json)
        except _json.JSONDecodeError as exc:
            raise typer.BadParameter(f"Invalid edited-row JSON: {exc}") from exc
        if not isinstance(edited_row, dict):
            raise typer.BadParameter("edited-row JSON must be an object.")
        edited_row = {str(key): str(value) for key, value in edited_row.items()}
    try:
        action = append_adjudication_action(
            review_dir=review_dir,
            artifact_root=artifact_root,
            run_id=run_id,
            item_path=review_dir / item,
            decision=decision,
            reviewer=reviewer,
            rationale=rationale,
            edited_row=edited_row,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    suffix = (
        f" Derived artifact: {action.derived_artifact_path}."
        if action.derived_artifact_path
        else ""
    )
    console.print(f"[green]Recorded {action.decision}[/green] ({action.action_id}).{suffix}")


@app.command("serve")
def serve_command(
    project_yaml: Path,
    port: int = typer.Option(8765, min=1, max=65535, help="Loopback port."),
) -> None:
    """Serve the single-user local review dashboard on 127.0.0.1 only."""
    serve_dashboard(project_yaml.resolve(), port=port)


if __name__ == "__main__":
    app()
