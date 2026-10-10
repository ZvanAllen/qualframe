"""Plain-language study status for navigation and the study overview.

Everything here is read from engine records on disk; nothing is inferred.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from qualframe.config import resolve_repo_path
from qualframe.evidence_review import latest_evidence_action_by_record, load_evidence_review_records
from qualframe.workspace_ui import Step


@dataclass
class ReviewCounts:
    total: int = 0
    resolved: int = 0
    by_decision: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return self.total - self.resolved


@dataclass
class StudyStatus:
    transcripts: int
    groups: int
    codes: int
    codebook_label: str
    has_reference_codebook: bool
    model_configured: bool
    completed_runs: list[str]
    review_run: str | None
    review: ReviewCounts
    exported: bool
    snapshot: bool

    @property
    def sources_done(self) -> bool:
        return self.transcripts > 0

    @property
    def codebook_done(self) -> bool:
        return self.codes > 0 or self.has_reference_codebook

    @property
    def coding_done(self) -> bool:
        return bool(self.completed_runs)

    @property
    def review_done(self) -> bool:
        return self.review.total > 0 and self.review.remaining == 0

    @property
    def results_done(self) -> bool:
        return self.exported or self.snapshot


def review_counts(app, run_id: str) -> ReviewCounts:
    index = app.artifacts_dir / run_id / "evidence_review/index.json"
    if not index.exists():
        return ReviewCounts()
    records = load_evidence_review_records(index)
    actions = latest_evidence_action_by_record(app.review_dir / run_id)
    counts: dict[str, int] = {}
    resolved = 0
    for record in records:
        decision = actions[record.record_id].decision if record.record_id in actions else "unreviewed"
        counts[decision] = counts.get(decision, 0) + 1
        if decision not in {"unreviewed", "defer"}:
            resolved += 1
    return ReviewCounts(total=len(records), resolved=resolved, by_decision=counts)


def completed_runs(app) -> list[str]:
    runs = []
    for run_id in app.list_runs():
        manifest = app.artifacts_dir / run_id / "run_manifest.json"
        if manifest.exists():
            try:
                status = json.loads(manifest.read_text(encoding="utf-8")).get("status")
            except (OSError, ValueError):
                continue
            if status in {"completed", "awaiting_review"}:
                runs.append(run_id)
    return runs


def review_run(app) -> str | None:
    """The run whose review the navigation points at: the selected run if reviewable, else the newest."""
    runs = [r for r in app.list_runs() if (app.artifacts_dir / r / "evidence_review/index.json").exists()]
    preferred = getattr(app, "_selected_run", None)
    if preferred in runs:
        return preferred
    return runs[0] if runs else None


def study_status(app) -> StudyStatus:
    runner = app.runner
    files = runner._transcript_files()
    groups = {path.parent.name for path in files}
    if runner.codebook is not None:
        codes = len(runner.codebook.codes)
        label = f"{runner.codebook.name} (version {runner.codebook.version})"
        reference = False
    else:
        reference_dir = resolve_repo_path(app.repo_root, runner.project.paths.get("reference", "data/reference"))
        reference = any((reference_dir / f"codebook{ext}").exists() for ext in (".xlsx", ".txt", ".docx", ".md"))
        codes = 0
        label = "CFIR reference workbook" if reference else "No codebook yet"
    runs = completed_runs(app)
    target = review_run(app)
    counts = review_counts(app, target) if target else ReviewCounts()
    exported = bool(target) and any((app.exports_dir / target).glob("reviewed_evidence_package.*"))
    snapshot = bool(target) and any((app.artifacts_dir / target / "analysis").glob("snapshot-*.json"))
    provider = runner.project.provider.name
    return StudyStatus(
        transcripts=len(files), groups=len(groups), codes=codes, codebook_label=label,
        has_reference_codebook=reference, model_configured=bool(provider),
        completed_runs=runs, review_run=target, review=counts, exported=exported, snapshot=snapshot,
    )


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def study_steps(app, status: StudyStatus | None = None) -> list[Step]:
    status = status or study_status(app)
    review_url = "/evidence?" + urlencode({"run_id": status.review_run}) if status.review_run else "/review"
    results_url = "/analysis?" + urlencode({"run_id": status.review_run}) if status.review_run else "/results"
    review_detail = (
        f"{status.review.resolved} of {status.review.total} decided" if status.review.total
        else "Nothing to review yet"
    )
    results_detail = (
        "Exported" if status.exported else "Snapshot saved" if status.snapshot
        else "Available after review" if not status.review_done else "Ready to export"
    )
    run_detail = (
        _plural(len(status.completed_runs), "run") if status.completed_runs else "Not run yet"
    )
    raw = [
        Step("imports", "Sources", "/imports",
             _plural(status.transcripts, "transcript") if status.transcripts else "Add transcripts",
             "done" if status.sources_done else "todo"),
        Step("codebook", "Codebook", "/codebook",
             _plural(status.codes, "code") if status.codes else ("CFIR workbook" if status.has_reference_codebook else "Add a codebook"),
             "done" if status.codebook_done else "todo"),
        Step("configure", "Run coding", "/configure", run_detail, "done" if status.coding_done else "todo"),
        Step("evidence", "Review", review_url, review_detail, "done" if status.review_done else "todo"),
        Step("analysis", "Results", results_url, results_detail, "done" if status.results_done else "todo"),
    ]
    marked: list[Step] = []
    next_assigned = False
    for step in raw:
        if step.state != "done" and not next_assigned:
            step = Step(step.key, step.label, step.url, step.detail, "next")
            next_assigned = True
        marked.append(step)
    return marked


def next_action(app, status: StudyStatus) -> tuple[str, str, str]:
    """Return (heading, explanation, url) for the one thing to do next."""
    if not status.sources_done:
        return ("Add your transcripts", "Import interview transcripts as Word or text files.", "/imports")
    if not status.codebook_done:
        return ("Add your codebook", "Import the codes you will apply, from Excel or a QualFrame file.", "/codebook")
    if not status.coding_done:
        return ("Run AI coding", "Choose a model, check the cost estimate, and start coding.", "/configure")
    if status.review.total and not status.review_done:
        url = "/evidence?" + urlencode({"run_id": status.review_run})
        return (
            "Continue reviewing",
            f"{status.review.remaining} of {status.review.total} coding proposals still need your decision.",
            url,
        )
    if status.review_done and not status.results_done:
        url = "/analysis?" + urlencode({"run_id": status.review_run})
        return ("See and export results", "Every proposal has a decision. Explore codes by transcript and export.", url)
    if status.results_done:
        url = "/analysis?" + urlencode({"run_id": status.review_run})
        return ("Explore your results", "Review is complete. Revisit results, or compare with another model run.", url)
    return ("Prepare the review", "Coding finished. Prepare the proposals for review.", "/configure")


def workspace_relative(app, path: Path) -> str:
    try:
        return path.resolve().relative_to(app.repo_root).as_posix()
    except ValueError:
        return str(path)
