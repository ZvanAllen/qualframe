# ruff: noqa: E501
"""Browser preparation, bounded dispatch and progress for repeated coding."""

from __future__ import annotations

import html
import json
import threading
from pathlib import Path
from urllib.parse import urlencode

from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.repeat_execution import (
    execute_repeats,
    experiment_root,
    prepare_repeats,
    read_repeat_plan,
    repeat_preflight,
)


def _get(form: dict[str, list[str]], key: str) -> str:
    return form.get(key, [""])[0]


def _identity(app, form: dict[str, list[str]]) -> None:
    if _get(form, "study_identity") != app.runner.project.project_id:
        raise ValueError("This tab belongs to another study. Reopen repeated coding first.")


def prepare_repeat_form(app, form: dict[str, list[str]]) -> str:
    _identity(app, form)
    envelope = prepare_repeats(
        app._managed_project_path(),
        repeat_count=int(_get(form, "repeat_count")),
        stage_id=_get(form, "stage_id"),
        source_paths=form.get("source", []),
    )
    return envelope["plan"]["experiment_id"]


def start_repeat_job(app, form: dict[str, list[str]]) -> str:
    from qualframe.dashboard import ExecutionJob

    _identity(app, form)
    project = app._managed_project_path()
    identifier = _get(form, "experiment")
    options = dict(
        plan_id=_get(form, "plan_id"),
        actor=_get(form, "reviewer"),
        rationale=_get(form, "rationale"),
        live_confirmed=_get(form, "live_confirmed") == "yes",
        resume=_get(form, "resume") == "yes",
    )
    execute_repeats(project, identifier, dry_run=True, **options)
    with app._job_lock:
        if any(job.status == "running" for job in app._jobs.values()):
            raise ValueError("Wait for the current study job before starting repeated coding.")
        app._jobs[identifier] = ExecutionJob(run_id=identifier)

    def progress(run_id):
        with app._job_lock:
            app._jobs[identifier].progress.append(f"Coding repeat: {run_id}")

    def work():
        try:
            execute_repeats(project, identifier, progress_callback=progress, **options)
        except Exception as exc:
            with app._job_lock:
                app._jobs[identifier].status = "stopped"
                app._jobs[identifier].error = str(exc)
        else:
            with app._job_lock:
                app._jobs[identifier].status = "completed"

    threading.Thread(target=work, name=identifier, daemon=True).start()
    return identifier


def render_repeats(app, experiment_id: str = "", message: str = "") -> str:
    e = html.escape
    project = app._managed_project_path()
    runner = ProjectRunner(project)
    study = app.study_workspace.managed_study_root(project)
    body = f'<p role="status">{e(message)}</p>' if message else ""
    body += '<p><a href="/compare">Compare two runs</a> · <a href="/stability">View stability across runs</a></p>'
    body += "<p>Repeat the same coding configuration on the same selected transcripts. Each repeat creates a separate set of model proposals. Repetition can describe stability; agreement alone does not establish qualitative validity.</p>"
    if not experiment_id:
        stages = [
            s
            for s in runner.pipeline.stages
            if s.enabled
            and s.prompt_ref
            and s.input_source == "raw_transcripts"
            and s.input_grouping == "per_file"
            and runner._previous_llm_stage(s) is None
        ]
        options = "".join(
            f'<option value="{e(s.id)}">{e(s.description or s.id)}</option>' for s in stages
        )
        sources = [i for i in runner.build_run_plan().discovered_inputs if i.kind == "transcript"]
        choices = "".join(
            f'<label class="check"><input type="checkbox" name="source" value="{e(i.path)}" checked>{e(Path(i.path).name)}</label>'
            for i in sources
        )
        body += f'''<section class="card"><h2>Prepare a repeat plan</h2><p>Current provider: <strong>{e(runner.project.provider.name)} · {e(runner.project.provider.model or "local fixture")}</strong>. Change provider settings in study setup before preparing a new configuration.</p><form method="post" action="/repeats/prepare"><input type="hidden" name="study_identity" value="{e(runner.project.project_id)}"><label>Coding stage<select name="stage_id" required>{options}</select></label><label>Number of repeats<input type="number" name="repeat_count" min="2" max="10" value="3" required></label><fieldset><legend>Transcripts in every repeat</legend>{choices or "<p>Import transcripts in study setup first.</p>"}</fieldset><button {"" if options and choices else "disabled"}>Prepare costed repeat plan</button></form><p>Preparation sends no model requests and creates no human review decisions.</p></section>'''
    else:
        envelope = read_repeat_plan(project, experiment_id)
        plan = envelope["plan"]
        root = experiment_root(project, experiment_id)
        status = json.loads((root / "status.json").read_text(encoding="utf-8"))
        job = app._job_snapshot(experiment_id)
        running = bool(job and job.status == "running")
        preview = None
        problem = ""
        try:
            preview = repeat_preflight(project, experiment_id)
        except (ValueError, OSError, RuntimeError) as exc:
            problem = str(exc)
        completed = preview["completed_run_ids"] if preview else status.get("completed_run_ids", [])
        shown_status = (
            "running"
            if running
            else (
                "interrupted — review and resume"
                if status["status"] == "running"
                else status["status"]
            )
        )
        refresh = "/repeats?" + urlencode(dict(experiment=experiment_id))
        body += f'<section class="card"><h2>Repeat progress</h2><p><strong>{e(shown_status.capitalize())}</strong> · <a href="{e(refresh)}">Refresh progress</a> · <a href="/repeats">Prepare another plan</a></p><p>{e(plan["provider"]["name"])} · {e(plan["provider"]["model"] or "local fixture")} · {len(plan["run_plan"]["discovered_inputs"])} transcripts per repeat</p><label for="repeat-progress">{len(completed)} of {plan["repeat_count"]} repeats complete</label><progress id="repeat-progress" max="{plan["repeat_count"]}" value="{len(completed)}"></progress>'
        if status.get("error") or (job and job.error):
            body += f'<p class="review-guidance">Stopped: {e((job.error if job else "") or status.get("error", ""))}</p>'
        if problem:
            body += f'<p class="review-guidance">Execution is blocked: {e(problem)}</p>'
        if preview:
            body += f'<p>Remaining conservative allowance: <strong>USD {preview["estimated_cost_usd"]:.4f}</strong> for up to {preview["remaining_call_allowance"]} requests. Study spend: USD {preview["spent_usd"]:.4f}; remaining budget: USD {preview["remaining_budget_usd"]:.4f}; absolute ceiling: USD {preview["absolute_limit_usd"]:.2f}.</p><p class="muted">The allowance includes the configured maximum output for each remaining request. A partially completed repeat is conservatively counted in full; existing completed transcript artifacts are preserved on resume. If interruption occurred partway through one transcript, its domain or partition requests restart; prior responses and charges remain recorded.</p>'
        body += "<ol>"
        for n, run_id in enumerate(plan["run_ids"], 1):
            label = (
                "Complete; proposals available"
                if run_id in completed
                else (
                    "In progress"
                    if running and run_id == status.get("active_run_id")
                    else "Pending or stopped"
                )
            )
            link = (
                f'<a href="{e("/evidence?" + urlencode(dict(run_id=run_id)))}">Review coding proposals</a>'
                if run_id in completed
                else ""
            )
            body += f"<li>Repeat {n}: {e(label)} {link}</li>"
        body += "</ol>"
        report_url = "/stability?" + urlencode(dict(experiment=experiment_id))
        body += f'<p><a class="button" href="{e(report_url)}">View evaluation for this experiment</a></p>'
        if preview and preview["remaining_repeats"] and not running:
            profile = app.review_dir / "reviewer.json"
            reviewer = (
                json.loads(profile.read_text(encoding="utf-8")).get("name", "")
                if profile.exists()
                else ""
            )
            resume = (root / "attempts").exists()
            live = plan["provider"]["name"] != "mock"
            consent = (
                '<label class="check"><input type="checkbox" name="live_confirmed" value="yes" required>I confirm that this study permits sending the selected transcripts and codebook to this provider, and approve the remaining repeats within the displayed study ceiling.</label>'
                if live
                else "<p>This synthetic test uses a deterministic local fixture and incurs no provider charges.</p>"
            )
            body += f'''<form method="post" action="/repeats/{"resume" if resume else "start"}"><input type="hidden" name="study_identity" value="{e(runner.project.project_id)}"><input type="hidden" name="experiment" value="{e(experiment_id)}"><input type="hidden" name="plan_id" value="{e(envelope["plan_id"])}"><input type="hidden" name="resume" value="{"yes" if resume else "no"}"><label>Researcher name<input name="reviewer" value="{e(reviewer)}" required></label><label>Reason for these repeats<input name="rationale" required></label>{consent}<button>{"Resume remaining repeats" if resume else "Start coding repeats"}</button></form>'''
        body += "</section>"
    prepared = []
    for path in sorted(
        (study / "experiments").glob("repeat-*/plan.json"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    ):
        try:
            envelope = read_repeat_plan(project, path.parent.name)
            plan = envelope["plan"]
            link = "/repeats?" + urlencode(dict(experiment=path.parent.name))
            prepared.append(
                f'<li><a href="{e(link)}">{plan["repeat_count"]} repeats · {e(plan["provider"]["model"] or "local fixture")} · {e(plan["created_at_utc"][:16])}</a></li>'
            )
        except (ValueError, OSError, KeyError):
            continue
    if prepared:
        body += "<section><h2>Prepared experiments</h2><ul>" + "".join(prepared) + "</ul></section>"
    return app._render_workspace_page(
        title="Repeat coding",
        intro="Check stability across separate runs of one frozen configuration.",
        body=body,
    )
