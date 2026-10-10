"""Source-level review screen for explicit empty coding responses."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

from qualframe.empty_output_review import (
    _digest,
    _within,
    append_empty_output_action,
    empty_output_state,
    load_empty_output_actions,
)
from qualframe.io.transcript_io import transcript_to_text


def handle_empty_output_action(app, form: dict[str, list[str]]) -> tuple[str, str]:
    def required(key: str) -> str:
        value = form.get(key, [""])[0].strip()
        if not value:
            raise ValueError("Missing field: " + key)
        return value

    app._managed_project_path()
    if required("study_identity") != app.runner.project.project_id:
        raise ValueError(
            "This page belongs to another study. Reopen the current study before deciding."
        )
    run_id = required("run_id")
    root = app._run_root(app.artifacts_dir, run_id)
    decision = required("decision")
    if decision == "confirm_empty" and form.get("source_checked", [""])[0] != "yes":
        raise ValueError(
            "Confirm that you reviewed the source transcript and codebook "
            "before accepting zero proposals."
        )
    action = append_empty_output_action(
        repo_root=app.repo_root,
        run_root=root,
        review_root=app.review_dir / run_id,
        source_path=required("source"),
        expected_binding=required("binding"),
        decision=decision,
        reviewer=required("reviewer"),
        rationale=required("rationale"),
    )
    profile = app.review_dir / "reviewer.json"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps({"name": action["reviewer"]}), encoding="utf-8")
    labels = {
        "confirm_empty": "Confirmed this transcript's zero-proposal coding output.",
        "needs_recoding": "Recorded that this transcript needs a new coding run.",
        "defer": "Deferred this transcript's empty-output review.",
    }
    return run_id, labels[decision]


def render_empty_output_review(app, run_id: str, source_path: str, message: str = "") -> str:
    app._managed_project_path()
    root = app._run_root(app.artifacts_dir, run_id)
    app._selected_run = run_id
    review = app.review_dir / run_id
    state = empty_output_state(app.repo_root, root, review, source_path)
    e = html.escape
    back = "/?" + urlencode({"run_id": run_id})
    body = f'<p><a href="{e(back)}">Back to study progress</a></p>'
    if message:
        body += f'<p role="status">{e(message)}</p>'
    body += (
        "<p>The coding response proposed no passages. This is a result to inspect, "
        "not proof that the codebook concepts are absent.</p>"
    )
    if not state.get("empty_eligible"):
        issue = state.get("empty_issue") or "This transcript is not ready for empty-output review."
        body += f'<p class="review-guidance">{e(issue)}</p>'
    else:
        binding = state["empty_binding"]
        text = transcript_to_text(_within(app.repo_root, binding["source_path"]))
        index = json.loads((root / "evidence_review/index.json").read_text(encoding="utf-8"))
        codes = "".join(
            f"<dt>{e(code['label'])}</dt><dd>{e(code.get('definition', ''))}</dd>"
            for code in index.get("codebook", {}).get("codes", [])
        )
        raw = ""
        for artifact in binding["artifacts"]:
            response = json.loads(_within(root, artifact["path"]).read_text(encoding="utf-8"))
            raw += (
                '<article><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
                + e(response["response_text"])
                + "</pre></article>"
            )
        profile = app.review_dir / "reviewer.json"
        reviewer = (
            json.loads(profile.read_text(encoding="utf-8")).get("name", "")
            if profile.exists()
            else ""
        )
        latest = state.get("empty_action")
        if latest:
            body += (
                f"<p>Latest recorded decision: {e(latest['decision'].replace('_', ' '))} "
                f"by {e(latest['reviewer'])}. Current status: "
                f"{e(state['empty_state'].replace('_', ' '))}.</p>"
            )
        body += f"""
<div class="grid">
<section class="card"><h2>{e(Path(source_path).name)}</h2>
<pre style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:65vh;overflow:auto"
>{e(text)}</pre></section>
<section class="card"><h2>Review the empty coding result</h2>
<p>Read the transcript with the codebook, then confirm this result, request new coding,
or decide later. Confirming allows this transcript into a reviewed snapshot with zero
retained passages.</p>
<details open><summary>Original model output</summary>{raw}</details>
<details><summary>Codebook</summary><dl>{codes}</dl></details>
<form method="post" action="/empty-output/review">
<input type="hidden" name="run_id" value="{e(run_id)}">
<input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">
<input type="hidden" name="source" value="{e(binding["source_path"])}">
<input type="hidden" name="binding" value="{e(_digest(binding))}">
<label>Researcher name<input name="reviewer" value="{e(reviewer)}" required></label>
<label>Reason for this decision<textarea name="rationale" required></textarea></label>
<label class="check"><input type="checkbox" name="source_checked" value="yes">
I reviewed this transcript with the codebook and agree that no coded passages should
be retained from this output.</label>
<div class="inline">
<button name="decision" value="confirm_empty">Confirm zero proposals</button>
<button name="decision" value="needs_recoding">Needs new coding</button>
<button name="decision" value="defer">Decide later</button>
</div></form></section></div>"""
    history = [a for a in load_empty_output_actions(review) if a["source_path"] == state["path"]]
    if history:
        items = "".join(
            f"<li>{e(a['timestamp_utc'])} · {e(a['reviewer'])} · "
            f"{e(a['decision'].replace('_', ' '))}: {e(a['rationale'])}</li>"
            for a in history
        )
        body += (
            f"<details><summary>Decision history ({len(history)})</summary>"
            f"<ol>{items}</ol></details>"
        )
    return app._render_workspace_page(
        title="Review empty coding output",
        intro="Confirm a complete zero-proposal response against its source transcript.",
        body=body,
    )
