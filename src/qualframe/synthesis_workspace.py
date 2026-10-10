# ruff: noqa: E501
"""Background synthesis controls and a focused, evidence-linked summary reviewer."""

from __future__ import annotations

import html
import json
import threading
import uuid
from pathlib import Path
from urllib.parse import urlencode

from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.synthesis_execution import current_plan, execute_synthesis, synthesis_preflight
from qualframe.synthesis_review import job_root, latest_summary_actions, read_job


def start_synthesis_job(app, run_id: str, form: dict[str, list[str]]) -> str:
    from qualframe.dashboard import ExecutionJob

    if form.get("study_identity", [""])[0] != app.runner.project.project_id:
        raise ValueError("This tab belongs to another study.")
    root = app._run_root(app.artifacts_dir, run_id)
    project = app._managed_project_path()

    def get(key: str) -> str:
        return form.get(key, [""])[0]

    plan_id = get("plan_id")
    identifier = "synthesis-" + uuid.uuid4().hex
    options = dict(
        fingerprint=get("fingerprint"),
        actor=get("reviewer"),
        rationale=get("rationale"),
        live_confirmed=get("live_confirmed") == "yes",
        job_id=identifier,
    )
    execute_synthesis(project, root, plan_id, dry_run=True, **options)
    with app._job_lock:
        if any(job.status == "running" for job in app._jobs.values()):
            raise ValueError("Wait for the current job before starting synthesis.")
        app._jobs[identifier] = ExecutionJob(run_id=identifier)

    def work():
        try:
            target = execute_synthesis(project, root, plan_id, **options)
            status = json.loads((target / "status.json").read_text(encoding="utf-8"))["status"]
        except Exception as exc:
            with app._job_lock:
                app._jobs[identifier].status = "failed"
                app._jobs[identifier].error = str(exc)
        else:
            with app._job_lock:
                app._jobs[identifier].status = status

    threading.Thread(target=work, name=identifier, daemon=True).start()
    return identifier


def execution_controls(app, root: Path, plan_id: str) -> str:
    e = html.escape
    try:
        runner = ProjectRunner(app._managed_project_path())
        preview = synthesis_preflight(runner, root, plan_id)
    except (ValueError, OSError, RuntimeError) as exc:
        return f'<p class="review-guidance">Synthesis cannot start: {e(str(exc))}</p>'
    profile = app.review_dir / "reviewer.json"
    reviewer = (
        json.loads(profile.read_text(encoding="utf-8")).get("name", "") if profile.exists() else ""
    )
    live = preview["provider"]["name"] != "mock"
    approval = (
        '<label class="check"><input type="checkbox" name="live_confirmed" value="yes" required>I approve sending this reviewed evidence and codebook to the configured provider, within the displayed spending ceiling.</label>'
        if live
        else "<p>This synthetic test uses a deterministic local fixture.</p>"
    )
    return f'''<p><strong>{e(preview["provider"]["name"])} · {e(preview["provider"]["model"] or "mock")}</strong> · {preview["call_count"]} requests · conservative request allowance USD {preview["estimated_cost_usd"]:.4f}. Study spend USD {preview["spent_usd"]:.4f}; ceiling USD {preview["absolute_limit_usd"]:.2f}. Actual charges depend on returned usage.</p><form method="post" action="/synthesis/start"><input type="hidden" name="run_id" value="{e(root.name)}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><input type="hidden" name="plan_id" value="{e(plan_id)}"><input type="hidden" name="fingerprint" value="{e(preview["configuration_fingerprint"])}"><label>Researcher name<input name="reviewer" value="{e(reviewer)}" required></label><label>Reason for this synthesis<input name="rationale" required></label>{approval}<button>{"Generate proposed summaries" if live else "Generate synthetic summaries"}</button></form>'''


def render_synthesis_review(
    app, run_id: str, job_id: str, item_id: str = "", message: str = ""
) -> str:
    app._managed_project_path()
    app._selected_run = run_id
    root = app._run_root(app.artifacts_dir, run_id)
    target = job_root(root, job_id)
    e = html.escape
    url = "/synthesis?" + urlencode(dict(run_id=run_id, job=job_id))
    body = f'<p role="status">{e(message)}</p>' if message else ""
    body += f'<p><a href="/analysis?{e(urlencode(dict(run_id=run_id)))}">Back to analyzed evidence</a> · <a href="{e(url)}">Refresh status</a></p>'
    if not (target / "status.json").exists():
        job = app._job_snapshot(job_id)
        if job is None:
            raise ValueError("Unknown synthesis job.")
        body += f"<p>{e(job.error or 'Starting synthesis. Refresh to check progress.')}</p>"
        return app._render_workspace_page(
            title="Review proposed summaries",
            intro="Assess interpretation against its supporting evidence.",
            body=body,
        )
    status, plan, records = read_job(target)
    fresh = True
    try:
        current_plan(ProjectRunner(app._managed_project_path()), root, status["plan_id"])
    except (ValueError, OSError) as exc:
        fresh = False
        body += f'<p class="review-guidance">Earlier evidence: {e(str(exc))}. Historical proposals remain readable; new decisions and export require current evidence.</p>'
    actions = latest_summary_actions(target)
    label = status["status"].replace("_", " ")
    if records and all(
        actions.get(r["statement_id"], {}).get("decision") in {"accept", "edit", "reject"}
        for r in records
    ):
        label = "Review complete"
    body += f"<p>{e(label)} · {len(status['completed_groups'])}/{len(plan['calls'])} scopes completed · recorded cost USD {status.get('cost_usd', 0):.4f}</p>"
    if status["error"]:
        body += f'<p class="review-guidance">{e(status["error"])}</p><p>Prior responses and charges are preserved. No automatic retry was sent.</p>'
    if records:
        pending = [
            r
            for r in records
            if actions.get(r["statement_id"], {}).get("decision")
            not in {"accept", "edit", "reject"}
        ]
        item = (
            next((r for r in records if r["statement_id"] == item_id), None)
            if item_id
            else (pending or records)[0]
        )
        if item is None:
            raise ValueError("Unknown proposed summary.")
        call = next(c for c in plan["calls"] if c["group_id"] == item["group_id"])
        code = next(c for c in call["input"]["codes"] if c["id"] == item["code_id"])
        code_labels = {
            c["id"]: c["label"] for group in plan["calls"] for c in group["input"]["codes"]
        }
        options = "".join(
            f'<option value="{e(record["statement_id"])}" {"selected" if record["statement_id"] == item["statement_id"] else ""}>{i + 1}. {e(code_labels[record["code_id"]])} · {e(actions.get(record["statement_id"], {}).get("decision", "unreviewed"))}</option>'
            for i, record in enumerate(records)
        )
        body += f'<form method="get" action="/synthesis" class="inline"><input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="job" value="{e(job_id)}"><label>Summary<select name="item">{options}</select></label><button>Open summary</button></form>'
        action = actions.get(item["statement_id"])
        proposal = action.get("edited") if action and action.get("edited") else item
        quotes = ""
        choices = ""
        for evidence in call["input"]["evidence"]:
            if evidence["code_id"] != item["code_id"]:
                continue
            cited = evidence["evidence_id"] in proposal["evidence_ids"]
            quotes += f"<article><p><strong>{e(Path(evidence['source_path']).name)}</strong> · {'Cited' if cited else 'Available for this code'}</p><blockquote>{e(evidence['exact_text'])}</blockquote></article>"
            choices += f'<label class="check"><input type="checkbox" name="evidence_id" value="{e(evidence["evidence_id"])}" {"checked" if cited else ""}>{e(Path(evidence["source_path"]).name)}: {e(evidence["exact_text"][:160])}</label>'
        profile = app.review_dir / "reviewer.json"
        reviewer = (
            json.loads(profile.read_text(encoding="utf-8")).get("name", "")
            if profile.exists()
            else ""
        )
        disabled = "" if fresh else "disabled"
        fields = f'<input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="job" value="{e(job_id)}"><input type="hidden" name="item" value="{e(item["statement_id"])}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">'
        body += f'''<section><h2>{e(code["label"])}</h2><p>{e(call["input"]["scope"] if plan["grouping"] == "selected_cohort" else Path(call["input"]["scope"]).name)}</p><p>These are proposed interpretations. Citation checks establish source membership; assess whether the passages support the meaning.</p><div class="cards synthesis-cards"><div class="card"><h3>Supporting passages</h3>{quotes}</div><div class="card"><h3>{"Reviewed summary" if action and action.get("edited") else "Proposed summary"}</h3><p>{e(proposal["text"])}</p><p class="muted">{"Previous decision: " + e(action["decision"]) if action else "Awaiting your decision"}</p><form method="post" action="/synthesis/review">{fields}<label>Researcher name<input name="reviewer" value="{e(reviewer)}" required></label><label>Review note<input name="rationale"></label><div class="summary-actions"><button name="decision" value="accept" {disabled}>Accept and next</button><button name="decision" value="reject" {disabled}>Reject and next</button><button name="decision" value="defer" {disabled}>Decide later</button></div><details><summary>Edit summary or supporting passages</summary><label>Reviewed summary<textarea name="edited_text">{e(proposal["text"])}</textarea></label>{choices}<button name="decision" value="edit" {disabled}>Save changes and next</button></details></form></div></div><label for="summary-progress">{len(records) - len(pending)} of {len(records)} summaries resolved</label><progress id="summary-progress" max="{len(records)}" value="{len(records) - len(pending)}"></progress></section>'''
        if not pending and fresh:
            body += f'<section><h2>Review complete</h2><form method="post" action="/synthesis/export">{fields}<button>Export reviewed synthesis</button></form></section>'
    elif status["status"] == "no_statements":
        body += "<p>The model returned no statements. This is not evidence of construct absence. Inspect the reviewed inputs before deciding whether a new synthesis is warranted.</p>"
    for path in sorted(target.glob("reviewed-synthesis-*.json")):
        body += f"<p>{app._file_link(path, 'Download reviewed synthesis JSON')}</p>"
    return app._render_workspace_page(
        title="Review proposed summaries",
        intro="Assess interpretation against its supporting evidence.",
        body=body,
    )
