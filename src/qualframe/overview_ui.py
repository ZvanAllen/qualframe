"""Study overview: where the study stands and the one thing to do next."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from qualframe.study_status import next_action, review_counts, study_status, study_steps
from qualframe.ui_kit import e, notices, plural, provider_display, run_model, run_time_from_id, friendly_time

_CLASSIFICATION = {"synthetic": "Synthetic (demo or test data)", "deidentified": "De-identified research data",
                   "sensitive": "Sensitive research data"}


def _run_rows(app) -> str:
    rows = []
    for run_id in app.list_runs():
        root = app.artifacts_dir / run_id
        manifest_path = root / "run_manifest.json"
        provider, model = run_model(root)
        when = ""
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                when = friendly_time(data.get("completed_at_utc"))
                state = {"completed": "Coding finished", "awaiting_review": "Coding finished",
                         "blocked_validation": "Needs attention"}.get(data.get("status"), data.get("status", ""))
            except (OSError, ValueError):
                state = "Unreadable record"
        elif (root / "cost_pause.json").exists():
            state = "Paused at spending limit"
        elif (root / "requests").exists():
            state = "Incomplete"
        else:
            state = "Planned, not started"
        job = app._job_snapshot(run_id)
        if job is not None and job.status == "running":
            state = "Running now"
        counts = review_counts(app, run_id)
        review = f"{counts.resolved} of {counts.total} decided" if counts.total else "—"
        links = [f'<a href="/?{e(urlencode({"run_id": run_id}))}">Details</a>']
        if counts.total:
            links.insert(0, f'<a href="/evidence?{e(urlencode({"run_id": run_id}))}">Review</a>')
        label = provider_display(provider, model) if provider else "Not run yet"
        rows.append(
            f'<tr><td><strong>{e(label)}</strong><small>{e(when or run_time_from_id(run_id) or run_id)}</small></td>'
            f'<td>{e(state)}</td><td>{e(review)}</td><td class="row-links">{" ".join(links)}</td></tr>'
        )
    if not rows:
        return '<p class="muted">No coding runs yet.</p>'
    return ('<div class="progress-table"><table><thead><tr><th>Model</th><th>Status</th><th>Review</th><th></th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def render_overview(app, message: str = "") -> str:
    status = study_status(app)
    steps = study_steps(app, status)
    heading, explanation, url = next_action(app, status)
    items = []
    for index, step in enumerate(steps, start=1):
        mark = "&#10003;" if step.state == "done" else str(index)
        items.append(
            f'<li class="step {e(step.state)}"><span class="step-mark" aria-hidden="true">{mark}</span>'
            f'<div><strong>{e(step.label)}</strong><p>{e(step.detail)}</p></div>'
            f'<a href="{e(step.url)}">{"Open" if step.state == "done" else "Go"}</a></li>'
        )
    project = app.runner.project
    provider = project.provider
    method = app.runner.method.name if app.runner.method else "Reference workflow"
    details = (
        f'<dl><dt>Data</dt><dd>{e(_CLASSIFICATION.get(project.data_classification or "", "Not classified"))}</dd>'
        f'<dt>Codebook</dt><dd>{e(status.codebook_label)}</dd>'
        f'<dt>Method</dt><dd>{e(method)}</dd>'
        f'<dt>Model</dt><dd>{e(provider_display(provider.name, provider.model))}</dd>'
        f'<dt>Study folder</dt><dd><code>{e(str(app.runner.project_manifest_path.parent))}</code></dd></dl>'
    )
    body = f'''{notices(message)}
<div class="next-up"><div><h2>{e(heading)}</h2><p>{e(explanation)}</p></div><a class="button" href="{e(url)}">{e(heading)}</a></div>
<div class="overview-cols"><div>
<h2 class="sr-heading">Steps</h2><ol class="checklist">{"".join(items)}</ol>
<section class="runs"><div class="section-head"><h2>Coding runs</h2><a href="/configure">New run</a></div>{_run_rows(app)}</section>
</div><section class="study-details"><h2>About this study</h2>{details}</section></div>'''
    groups = f", {plural(status.groups, 'group')}" if status.groups > 1 else ""
    intro = f"{plural(status.transcripts, 'transcript')}{groups}, {plural(status.codes, 'code') if status.codes else 'no codebook yet'}."
    return app._render_workspace_page(title=project.title or project.project_id, intro=intro, body=body, active="overview")
