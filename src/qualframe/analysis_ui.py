"""Results: reviewed coding by code and transcript, every count linked to its passages. No model calls."""

from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import urlencode

from qualframe.config import resolve_repo_path
from qualframe.io.transcript_io import transcript_to_text
from qualframe.reviewed_analysis import load_snapshot, snapshot_freshness, evidence_matrix
from qualframe.study_progress import transcript_progress
from qualframe.ui_kit import friendly_time, plural

e = html.escape


def _level(count: int, top: int) -> int:
    if count <= 0 or top <= 0:
        return 0
    return min(4, 1 + int(3 * count / top)) if top > 1 else 2


def _ordered_codes(codes: list[dict]) -> list[tuple[dict, int]]:
    ids = {c["id"] for c in codes}
    children: dict[str | None, list[dict]] = {}
    for code in codes:
        parent = code.get("parent_id") if code.get("parent_id") in ids else None
        children.setdefault(parent, []).append(code)
    ordered: list[tuple[dict, int]] = []

    def walk(items: list[dict], depth: int) -> None:
        for code in items:
            ordered.append((code, depth))
            walk(children.get(code["id"], []), depth + 1)

    walk(children.get(None, []), 0)
    return ordered


def render_analysis(
    app,
    run_id: str,
    snapshot_id: str = "",
    code_id: str = "",
    source_path: str = "",
    message: str = "",
) -> str:
    app._managed_project_path()
    root = app._run_root(app.artifacts_dir, run_id)
    app._selected_run = run_id
    review = app.review_dir / run_id
    paths = sorted((root / "analysis").glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    selected = (
        next((p for p in paths if p.stem == "snapshot-" + snapshot_id), None) if snapshot_id
        else (paths[0] if paths else None)
    )
    if snapshot_id and selected is None:
        raise ValueError("The requested results snapshot is not available in this run.")
    reviewer = app.researcher or "Unnamed researcher"
    progress = transcript_progress(root, review, [], app.repo_root)
    eligible = [row for row in progress if row["reviewed"]]
    hidden = (f'<input type="hidden" name="run_id" value="{e(run_id)}">'
              f'<input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">'
              f'<input type="hidden" name="reviewer" value="{e(reviewer)}">')
    body = f'<div class="message" role="status">{e(message)}</div>' if message else ""

    def freeze_form(label: str, css: str = "") -> str:
        all_sources = "".join(f'<input type="hidden" name="source" value="{e(row["path"])}">' for row in eligible)
        return f'<form method="post" action="/analysis/freeze">{hidden}{all_sources}<button{css}>{e(label)}</button></form>'

    choose = ""
    if eligible:
        current = set(load_snapshot(selected)["payload"]["source_paths"]) if selected else {row["path"] for row in eligible}
        boxes = "".join(
            f'<label class="check"><input type="checkbox" name="source" value="{e(row["path"])}"'
            f'{" checked" if row["path"] in current else ""}{"" if row["reviewed"] else " disabled"}>'
            f'<span>{e(Path(row["path"]).name)}{"" if row["reviewed"] else " (review not finished)"}</span></label>'
            for row in progress)
        choose = (f'<details><summary>Choose which transcripts to include</summary><form method="post" action="/analysis/freeze">'
                  f'{hidden}{boxes}<button class="secondary">Update results with these transcripts</button></form></details>')
    empty_links = "".join(
        f'<li><a href="/empty-output?{e(urlencode({"run_id": run_id, "source": row["path"]}))}">Confirm that {e(Path(row["path"]).name)} has no codes</a></li>'
        for row in progress if row.get("empty_eligible"))
    if empty_links:
        body += f'<div class="notice"><p>Some transcripts received no proposals. Confirm them before they count as reviewed:</p><ul>{empty_links}</ul></div>'

    if not selected:
        if eligible:
            body += (f'<div class="next-up"><div><h2>Review finished for {len(eligible)} of {plural(len(progress), "transcript")}</h2>'
                     '<p>Show the results to see your kept codes by transcript. The results are saved as a snapshot so they can be cited and reproduced.</p></div>'
                     f'{freeze_form("Show results")}</div>{choose}')
        else:
            body += (f'<div class="next-up"><div><h2>Nothing reviewed yet</h2><p>Results appear once every proposal in a transcript has a decision.</p></div>'
                     f'<a class="button" href="/evidence?{e(urlencode({"run_id": run_id}))}">Continue review</a></div>')
        return app._render_workspace_page(title="Results", intro="Your reviewed coding, by code and transcript.", body=body, active="analysis")

    snapshot = load_snapshot(selected)
    payload = snapshot["payload"]
    fresh, status = snapshot_freshness(snapshot, app.repo_root, root, review)
    exports = sorted((app.exports_dir / run_id).glob("reviewed_evidence_package.*")) if (app.exports_dir / run_id).exists() else []
    export_links = " ".join(app._file_link(p, "Download " + p.suffix.lstrip(".").upper()) for p in exports)
    state = (f'<p class="status done">Current snapshot: matches your latest decisions.</p>' if fresh else
             f'<div class="notice"><p>Earlier snapshot. Your decisions changed after these results were saved; changes detected: {e(status)}</p>{freeze_form("Update results", " class=secondary")}</div>')
    body += f'''<div class="results-bar">{state}<div class="actions">
<form method="post" action="/export-evidence"><input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="return_to" value="analysis"><button>Export to Excel</button></form>
{export_links}<a href="/methods?{e(urlencode({"run_id": run_id}))}">Methods record</a>{app._file_link(selected, "Download snapshot (JSON)")}</div></div>'''

    sources = [s.replace("\\", "/") for s in payload["source_paths"]]
    cells = evidence_matrix(payload)
    groups: dict[str, list[str]] = {}
    for source in sources:
        groups.setdefault(Path(source).parent.name, []).append(source)
    ordered_sources = [s for members in groups.values() for s in members]
    counts = {
        key: len({(i["span"]["start_offset"], i["span"]["end_offset"]) for i in items})
        for key, items in cells.items()
    }
    top = max(counts.values(), default=0)
    group_head = "".join(f'<th colspan="{len(members)}" class="group-head">{e(name)}</th>' for name, members in groups.items())
    source_head = "".join(f'<th class="source-head" title="{e(Path(s).name)}">{e(Path(s).stem)}</th>' for s in ordered_sources)
    rows = ""
    all_codes = payload["codebook"].get("codes", [])
    parents = {c.get("parent_id") for c in all_codes if c.get("parent_id")}
    for code, depth in _ordered_codes(all_codes):
        if code["id"] in parents and not any(counts.get((code["id"], s), 0) for s in ordered_sources):
            # A category with no passages of its own: a heading for the codes beneath it.
            rows += (f'<tr class="category-row depth-{min(depth, 2)}"><th scope="rowgroup" '
                     f'colspan="{len(ordered_sources) + 2}">{e(code["label"])}</th></tr>')
            continue
        row_total = 0
        cells_html = ""
        for source in ordered_sources:
            n = counts.get((code["id"], source), 0)
            row_total += n
            if n:
                query = urlencode({"run_id": run_id, "snapshot": snapshot["snapshot_id"], "code": code["id"], "source": source})
                active = " current" if code["id"] == code_id and source == source_path else ""
                cells_html += f'<td class="cell q{_level(n, top)}{active}"><a href="/analysis?{e(query)}#passages" aria-label="{n} passages">{n}</a></td>'
            else:
                cells_html += '<td class="cell q0">·</td>'
        total_query = urlencode({"run_id": run_id, "snapshot": snapshot["snapshot_id"], "code": code["id"]})
        total = f'<a href="/analysis?{e(total_query)}#passages">{row_total}</a>' if row_total else "0"
        rows += (f'<tr class="depth-{min(depth, 2)}"><th scope="row">{e(code["label"])}</th>{cells_html}'
                 f'<td class="total">{total}</td></tr>')
    body += f'''<section class="matrix-section"><div class="section-head"><h2>Codes by transcript</h2><span class="muted">{plural(len(sources), "transcript")}, {plural(len(payload["evidence"]), "kept passage")}</span></div>
<p class="muted">Each number counts the passages you kept for that code. It is not a measure of how many people said something or how important it is. Select a number to read the passages.</p>
<div class="matrix-wrap"><table class="matrix"><thead><tr><th></th>{group_head}<th></th></tr><tr><th>Code</th>{source_head}<th>Total</th></tr></thead><tbody>{rows}</tbody></table></div></section>'''

    if code_id:
        wanted = [s for s in ordered_sources if not source_path or s == source_path.replace("\\", "/")]
        items = [item for s in wanted for item in cells.get((code_id, s), [])]
        label = next((c["label"] for c in payload["codebook"].get("codes", []) if c["id"] == code_id), code_id)
        where = f" in {Path(source_path).stem}" if source_path else " across all transcripts"
        passages = ""
        texts: dict[str, str] = {}
        for item in items:
            query = urlencode({"run_id": run_id, "item": item["record_id"]})
            span = item["span"]
            quote = f'<mark>{e(span["exact_text"])}</mark>'
            if span.get("context_start_offset") is not None and (
                    span["context_start_offset"] < span["start_offset"] or span["context_end_offset"] > span["end_offset"]):
                if item["source_path"] not in texts:
                    texts[item["source_path"]] = transcript_to_text(resolve_repo_path(app.repo_root, item["source_path"]))
                text = texts[item["source_path"]]
                if text[span["start_offset"]:span["end_offset"]] == span["exact_text"]:
                    quote = (e(text[span["context_start_offset"]:span["start_offset"]]) + quote
                             + e(text[span["end_offset"]:span["context_end_offset"]]))
            passages += (f'<article class="passage"><blockquote class="with-context">{quote}</blockquote>'
                         f'<p class="muted">{e(Path(item["source_path"]).stem)}. <a href="/evidence?{e(query)}">Open in review</a></p></article>')
        body += (f'<section id="passages"><h2>{e(label)}{e(where)}</h2>'
                 f'{passages or "<p>No kept passages here.</p>"}</section>')

    rejected = len(payload["rejected"])
    body += f'''<section><details><summary>About these results</summary>
<p>Saved by {e(snapshot["created_by"])} on {e(friendly_time(snapshot["created_at_utc"]))}. {plural(len(payload["evidence"]), "passage")} kept, {plural(rejected, "proposal")} rejected, {plural(len(payload["absences"]), "no-evidence decision")}, {plural(len(payload.get("empty_output_decisions", [])), "transcript")} confirmed as having no codes.</p>
<p>{len(payload["source_paths"])} included transcripts; {len(payload.get("excluded_source_paths", []))} excluded.</p></details>{choose}</section>'''
    from qualframe.synthesis_ui import render_synthesis_preparation

    body += f'<details class="review-details"><summary>Draft summaries with a model (optional)</summary>{render_synthesis_preparation(app, root, snapshot, fresh)}</details>'
    return app._render_workspace_page(title="Results", intro="Your reviewed coding, by code and transcript.", body=body, active="analysis", wide=True)
