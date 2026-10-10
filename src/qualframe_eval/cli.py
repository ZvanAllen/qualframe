"""CLI entry point for QualFrame evaluation (qualframe-eval)."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="qualframe-eval",
    help="Evaluation layer for comparing multi-model CFIR pipeline outputs.",
    no_args_is_help=True,
)


@app.command()
def compare(
    project_yaml: Path,
    left: str = typer.Option(..., help="First indexed coding run ID."),
    right: str = typer.Option(..., help="Second indexed coding run ID."),
    dry_run: bool = typer.Option(False, help="Validate and calculate without writing a report."),
) -> None:
    """Compare two raw coding runs locally; never submit provider requests."""
    from qualframe.config import resolve_repo_path
    from qualframe.pipeline.project_runner import ProjectRunner
    from qualframe.reviewed_analysis import _within
    from qualframe.run_comparison import write_comparison

    runner = ProjectRunner(project_yaml.resolve())
    root = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    try:
        if any(
            not value
            or Path(value).name != value
            or value in {".", ".."}
            or "/" in value
            or chr(92) in value
            for value in [left, right]
        ):
            raise ValueError("Choose run IDs, not paths.")
        path = write_comparison(
            runner.repo_root, _within(root, left), _within(root, right), dry_run=dry_run
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        ("Validated comparison; would write: " if dry_run else "Saved comparison: ") + str(path)
    )


@app.command()
def stability(
    project_yaml: Path,
    runs: list[str] = typer.Option(..., "--run", help="Run ID; repeat for 2 to 10 runs."),
    dry_run: bool = typer.Option(False, help="Calculate without saving."),
) -> None:
    """Describe overlap across repeated runs, retaining failures and undefined scores."""
    from qualframe.config import resolve_repo_path
    from qualframe.pipeline.project_runner import ProjectRunner
    from qualframe.repeat_comparison import write_repeat_report

    runner = ProjectRunner(project_yaml.resolve())
    root = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    try:
        if any(
            not r or Path(r).name != r or r in {".", ".."} or "/" in r or chr(92) in r for r in runs
        ):
            raise ValueError("Choose run IDs, not paths.")
        path = write_repeat_report(
            runner.repo_root, root, [root / r for r in runs], dry_run=dry_run
        )
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        ("Validated evaluation; would write: " if dry_run else "Saved evaluation: ") + str(path)
    )


@app.command()
def benchmark(
    project_yaml: Path,
    left: str = typer.Option(..., help="First indexed coding run ID."),
    right: str = typer.Option(..., help="Second indexed coding run ID."),
    dry_run: bool = typer.Option(False, help="Calculate without saving a report."),
) -> None:
    """Score exact and overlap span agreement; save local HTML, JSON and CSV."""
    from qualframe.benchmark_reporting import write_run_benchmark
    from qualframe.config import resolve_repo_path
    from qualframe.pipeline.project_runner import ProjectRunner

    runner = ProjectRunner(project_yaml.resolve())
    root = resolve_repo_path(runner.repo_root, runner.project.paths["artifacts"])
    try:
        if any(
            not r or Path(r).name != r or r in {".", ".."} or "/" in r or chr(92) in r
            for r in (left, right)
        ):
            raise ValueError("Choose run IDs, not paths.")
        path = write_run_benchmark(runner.repo_root, root / left, root / right, dry_run=dry_run)
    except (ValueError, OSError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        ("Validated benchmark; would write: " if dry_run else "Saved benchmark: ") + str(path)
    )


@app.command()
def run(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
    models: list[str] = typer.Option(..., help="Model run IDs to compare (repeat for each)."),
) -> None:
    """Run the full evaluation pipeline across all specified model runs."""
    raise NotImplementedError("qualframe-eval run is not yet implemented.")


@app.command()
def normalize(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
) -> None:
    """Normalize artifact workbooks from all model runs to a canonical schema."""
    raise NotImplementedError("qualframe-eval normalize is not yet implemented.")


@app.command()
def metrics(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
) -> None:
    """Compute deterministic comparison metrics across model runs."""
    raise NotImplementedError("qualframe-eval metrics is not yet implemented.")


@app.command()
def judge(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
) -> None:
    """Run blinded AI rubric evaluation against normalized workbooks."""
    raise NotImplementedError("qualframe-eval judge is not yet implemented.")


@app.command(name="seeded-errors")
def seeded_errors(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
) -> None:
    """Run the seeded-error validation challenge set against the AI evaluator."""
    raise NotImplementedError("qualframe-eval seeded-errors is not yet implemented.")


@app.command()
def report(
    project_dir: str = typer.Option(..., help="Path to the project directory."),
) -> None:
    """Generate manuscript-ready comparison tables and summary report."""
    raise NotImplementedError("qualframe-eval report is not yet implemented.")
