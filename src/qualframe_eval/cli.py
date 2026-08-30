"""CLI entry point for QualFrame evaluation (qualframe-eval)."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="qualframe-eval",
    help="Evaluation layer for comparing multi-model CFIR pipeline outputs.",
    no_args_is_help=True,
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
