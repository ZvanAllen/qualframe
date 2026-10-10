# ruff: noqa: E501
"""Preparation controls for a future, separately approved synthesis run."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

from qualframe.reviewed_analysis import snapshot_identity
from qualframe.synthesis_plan import PROMPT_PATH


def render_synthesis_preparation(app, root, snapshot, fresh: bool) -> str:
    e = html.escape
    identity = snapshot["snapshot_id"]
    body = "<section><h2>Prepare synthesis</h2><p>Organize reviewed passages into a plan and inspect the instructions. This step saves inputs locally. It sends no API requests and creates no findings.</p>"
    if fresh and snapshot["payload"]["evidence"]:
        body += f'''<form method="post" action="/analysis/prepare-synthesis"><input type="hidden" name="run_id" value="{e(root.name)}"><input type="hidden" name="snapshot" value="{e(identity)}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><label>Summary scope<select name="grouping"><option value="per_transcript">One scope per transcript</option><option value="selected_cohort">Combine the selected transcripts</option></select></label><button>Prepare synthesis plan</button></form>'''
    else:
        body += "<p>A current snapshot with retained evidence is needed to prepare a plan.</p>"
    if fresh and snapshot["payload"]["evidence"]:
        body += render_metadata_controls(app, root, snapshot)
    body += "<p>Use the configured provider to generate proposals from a prepared plan, then review each summary against its cited passages.</p>"
    body += f'<details><summary>Version 1 synthesis instructions</summary><pre class="source-preview">{e((app.repo_root / PROMPT_PATH).read_text(encoding="utf-8"))}</pre></details>'
    plans = sorted(
        (root / "analysis").glob("synthesis-plan-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in plans:
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan.get("snapshot_id") != identity:
            continue
        if path.stem != "synthesis-plan-" + snapshot_identity(plan):
            body += "<p>A stored plan has changed and cannot be used. Preserve it for inspection and prepare a new plan.</p>"
            continue
        scopes = "".join(
            f"<li>{e(call['input']['scope'] if plan['grouping'] != 'per_transcript' else Path(call['input']['scope']).name)}: {len(call['input']['evidence'])} retained proposals</li>"
            for call in plan["calls"]
        )
        body += f"<h3>Prepared plan · {len(plan['calls'])} scope(s)</h3><p>{'Inputs match the current snapshot.' if fresh else 'Earlier inputs: review changes require a new snapshot and plan.'} The plan preserves the selected inputs.</p><ul>{scopes}</ul><p>{app._file_link(path, 'Download synthesis input plan')}</p>"
        body += render_metadata_plan(plan)
        from qualframe.synthesis_workspace import execution_controls

        body += execution_controls(app, root, snapshot_identity(plan))
        for status_path in sorted((root / "analysis" / "synthesis").glob("*/status.json")):
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status["plan_id"] == snapshot_identity(plan):
                link = "/synthesis?" + urlencode(dict(run_id=root.name, job=status["job_id"]))
                body += f'<p><a href="{e(link)}">Open synthesis: {e(status["status"].replace("_", " "))}</a></p>'
    return body + "</section>"


def render_metadata_controls(app, root: Path, snapshot: dict) -> str:
    from qualframe.metadata_synthesis import read_metadata_catalog

    e = html.escape
    try:
        catalog = read_metadata_catalog(
            app.runner.project_manifest_path, snapshot["payload"]["source_paths"]
        )
    except (OSError, ValueError) as exc:
        return (
            f'<p>Metadata scopes: {e(str(exc))} <a href="/imports">Open the source library</a>.</p>'
        )
    if not catalog["fields"]:
        return "<p>The imported metadata has no grouping columns beyond source_filename.</p>"
    body = "<details><summary>Group summaries using imported metadata</summary><p>Choose one field and the values to include. Values are case-sensitive; surrounding spaces are trimmed. Each transcript belongs to one scope. These scopes do not establish participant counts or prevalence.</p>"
    for field in catalog["fields"]:
        values = sorted(
            {row["values"][field] for row in catalog["sources"] if row["values"][field]}
        )
        missing = [row for row in catalog["sources"] if not row["values"][field]]
        body += f'''<form method="post" action="/analysis/prepare-synthesis"><input type="hidden" name="run_id" value="{e(root.name)}"><input type="hidden" name="snapshot" value="{e(snapshot["snapshot_id"])}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><input type="hidden" name="grouping" value="metadata"><input type="hidden" name="metadata_field" value="{e(field)}"><input type="hidden" name="metadata_value" value=""><fieldset><legend>Group by {e(field)}</legend><p>{len(missing)} selected transcript(s) have a missing value.</p>'''
        for value in values:
            count = sum(row["values"][field] == value for row in catalog["sources"])
            body += f'<label><input type="checkbox" name="metadata_value" value="{e(value)}" checked> {e(value)} ({count} transcript(s))</label>'
        body += f"""<label>Missing values for {e(field)}<select name="missing_policy"><option value="error">Require a value for every selected transcript</option><option value="exclude">Exclude transcripts with missing values</option><option value="separate">Include a separate missing-value scope</option></select></label><button>Prepare scopes by {e(field)}</button></fieldset></form>"""
    return body + "</details>"


def render_metadata_plan(plan: dict) -> str:
    from qualframe.metadata_synthesis import metadata_group_matrix

    e = html.escape
    grouping = plan.get("metadata_grouping")
    if not grouping:
        return ""
    missing_labels = dict(
        error="Every selected transcript needs a value",
        exclude="Missing values excluded",
        separate="Missing values form a separate scope",
    )
    body = f"<p>Metadata field: <strong>{e(grouping['field'])}</strong>. {missing_labels[grouping['missing_policy']]}. {len(plan['included_sources'])} transcript(s) included; {len(plan['excluded_sources'])} excluded.</p><details><summary>Frozen metadata scope membership</summary>"
    for group in grouping["groups"]:
        body += (
            f"<h4>{e(group['label'])}</h4><ul>"
            + "".join(f"<li>{e(Path(path).name)}</li>" for path in group["source_paths"])
            + "</ul>"
        )
    if plan["excluded_sources"]:
        reasons = {
            row["source_path"]: row["reason"].replace("_", " ")
            for row in grouping["excluded_sources"]
        }
        body += (
            "<h4>Excluded transcripts</h4><ul>"
            + "".join(
                f"<li>{e(Path(path).name)}: {e(reasons.get(path, 'outside the reviewed snapshot'))}</li>"
                for path in plan["excluded_sources"]
            )
            + "</ul>"
        )
    body += '</details><details><summary>Code-by-metadata-group matrix</summary><p>Cells count distinct retained source spans for each code. A zero means no retained passage in this snapshot; it does not establish absence. These are not participant frequencies or independent observations.</p><div class="progress-table"><table><thead><tr><th>Code</th>'
    groups = grouping["groups"]
    body += "".join(f"<th>{e(group['label'])}</th>" for group in groups) + "</tr></thead><tbody>"
    matrix = metadata_group_matrix(plan)
    codes = {cell["code_id"]: cell["code_label"] for cell in matrix}
    cells = {(cell["code_id"], cell["group_id"]): cell for cell in matrix}
    for code, label in sorted(codes.items()):
        body += f"<tr><th>{e(label)}</th>"
        for group in groups:
            cell = cells[(code, group["group_id"])]
            if not cell["evidence"]:
                body += "<td>0</td>"
                continue
            body += f"<td><details><summary>{cell['distinct_spans']} span(s)</summary>"
            for item in cell["evidence"]:
                link = "/analysis?" + urlencode(
                    dict(
                        run_id=plan["run_id"],
                        snapshot=plan["snapshot_id"],
                        code=code,
                        source=item["source_path"],
                    )
                )
                body += f'<p><a href="{e(link)}">{e(Path(item["source_path"]).name)}</a></p><blockquote>{e(item["exact_text"])}</blockquote>'
            body += "</details></td>"
        body += "</tr>"
    return body + "</tbody></table></div></details>"
