"""Compare two coding runs: where they agree and where they differ. Read-only; no model calls."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import compare_raw_payloads, raw_coding_payload
from qualframe.ui_kit import provider_display, run_model, run_time_from_id, friendly_time

e = html.escape


def _run_label(app, run_id: str) -> str:
    provider, model = run_model(app.artifacts_dir / run_id)
    when = ""
    manifest = app.artifacts_dir / run_id / "run_manifest.json"
    try:
        when = friendly_time(json.loads(manifest.read_text(encoding="utf-8")).get("completed_at_utc"))
    except (OSError, ValueError):
        when = run_time_from_id(run_id)
    return f"{provider_display(provider, model)}, {when or run_id}"


def _run_setup(app, run_id: str, instruction_labels: dict[str, str]) -> dict[str, str]:
    """What a run was coded with: model, instructions version and coding options (from its lock)."""
    provider, model = run_model(app.artifacts_dir / run_id)
    setup = {"Model": provider_display(provider, model), "Instructions": "Not recorded", "Coding options": "Not recorded"}
    try:
        lock = json.loads((app.artifacts_dir / run_id / "analysis_configuration_lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return setup
    for asset in lock.get("assets", []):
        if asset.get("kind") == "prompt":
            sha = asset.get("sha256", "")
            setup["Instructions"] = instruction_labels.get(sha) or f"Instructions {sha[:12]}"
        elif asset.get("kind") == "method":
            stem = Path(asset.get("path", "")).stem
            number = stem.rsplit("_v", 1)[1] if "_v" in stem else ""
            setup["Coding options"] = (f"Version {number}" if number.isdigit() else "Standard") + f" ({asset.get('sha256', '')[:8]})"
    return setup


def render_comparison(app, left_id: str = "", right_id: str = "", message: str = "") -> str:
    app._managed_project_path()
    runs = [r for r in app.list_runs() if (app.artifacts_dir / r / "evidence_review/index.json").exists()]
    labels = {r: _run_label(app, r) for r in runs}
    body = f'<div class="message" role="status">{e(message)}</div>' if message else ""
    tools = ('<p class="muted">More: <a href="/repeats">repeat a run several times</a> to see how stable a model is, '
             'or <a href="/stability">evaluate a set of repeated runs</a>.</p>')
    if len(runs) < 2:
        body += ('<div class="next-up"><div><h2>Code the study a second time</h2>'
                 '<p>Comparing two runs shows where models (or the same model on two tries) agree and where they differ, '
                 'passage by passage. Disagreements are often the places most worth a careful human read.</p></div>'
                 '<a class="button" href="/configure">Run another model</a></div>' + tools)
        return app._render_workspace_page(title="Compare runs", intro="See where two coding runs agree and differ.", body=body, active="compare")
    left_id = left_id or runs[0]
    right_id = right_id or next(r for r in runs if r != left_id)
    if left_id not in runs or right_id not in runs:
        raise ValueError("Select two coding runs from this study.")
    options = lambda selected: "".join(
        f'<option value="{e(r)}"{" selected" if r == selected else ""}>{e(labels[r])}</option>' for r in runs)
    body += (f'<form method="get" action="/compare" class="inline compare-picker"><label>Run A<select name="left">{options(left_id)}</select></label>'
             f'<label>Run B<select name="right">{options(right_id)}</select></label><button class="secondary">Compare</button></form>')
    left_root = app._run_root(app.artifacts_dir, left_id)
    right_root = app._run_root(app.artifacts_dir, right_id)
    report = compare_raw_payloads(raw_coding_payload(app.repo_root, left_root), raw_coding_payload(app.repo_root, right_root))
    pct = lambda value: "n/a" if value is None else f"{value:.0%}"
    summary = report["summary"]
    excluded = len(report["left"]["excluded"]) + len(report["right"]["excluded"])
    try:
        from qualframe.coding_instructions import instruction_versions

        instruction_labels = {v.sha256: v.label for v in instruction_versions(app.repo_root, app._managed_project_path())}
    except (OSError, ValueError):
        instruction_labels = {}
    left_setup, right_setup = _run_setup(app, left_id, instruction_labels), _run_setup(app, right_id, instruction_labels)
    setup_rows = "".join(
        f'<tr{" class=differs" if left_setup[k] != right_setup[k] else ""}><th>{e(k)}</th><td>{e(left_setup[k])}</td><td>{e(right_setup[k])}</td></tr>'
        for k in left_setup)
    differs = [k.lower() for k in left_setup if left_setup[k] != right_setup[k]]
    body += (f'<section><div class="section-head"><h2>What differs</h2><span class="muted">'
             f'{e("Different " + " and ".join(differs)) if differs else "Same model, instructions and options: a repeat run"}</span></div>'
             f'<table class="setup-compare"><thead><tr><th></th><th>Run A</th><th>Run B</th></tr></thead><tbody>{setup_rows}</tbody></table></section>')
    body += f'''<section><div class="section-head"><h2>Agreement</h2><span class="muted">Original model proposals, before your review</span></div>
<div class="agreement">
<div><strong>{pct(summary["code_jaccard"])}</strong><span>Codes in common</span><small>Of the codes either run applied to a transcript, the share both applied.</small></div>
<div><strong>{pct(summary["coverage_jaccard"])}</strong><span>Same text, same code</span><small>Overlap of the transcript text each run coded with the same code.</small></div>
<div><strong>{pct(summary["exact_span_jaccard"])}</strong><span>Identical passages</span><small>Same code and exactly the same start and end. Small boundary shifts count as different.</small></div>
</div>
<p class="muted">Neither run is treated as correct. Agreement describes consistency, not accuracy.{f" {excluded} proposal{'' if excluded == 1 else 's'} could not be located in the transcript and are left out of these figures." if excluded else ""}</p></section>'''
    quotes = {
        (i["source"], i["code_id"], i["start"], i["end"]): i["exact_text"]
        for side in ["left", "right"] for i in report[side]["included"]
    }
    code_labels = {c["id"]: c["label"] for c in report["left"]["codebook"]["codes"]}
    rows = ""
    for row in report["transcripts"]:
        columns = ""
        for title, key in ((f"Only in run A", "left_only_spans"), (f"Only in run B", "right_only_spans")):
            items = "".join(
                f'<li><span class="code-tag">{e(code_labels.get(code, code))}</span><blockquote>{e(quotes.get((row["source"], code, start, end), ""))}</blockquote></li>'
                for code, start, end in row[key])
            columns += f'<div><h3>{title} <span class="muted">({len(row[key])})</span></h3><ul class="diff-list">{items or "<li class=muted>Nothing</li>"}</ul></div>'
        rows += (f'<details class="diff-row"><summary><span class="diff-name">{e(Path(row["source"]).stem)}</span>'
                 f'<span>{pct(row["code_jaccard"])} codes in common</span><span>{pct(row["coverage_jaccard"])} same text</span>'
                 f'<span>{len(row["left_only_spans"]) + len(row["right_only_spans"])} differences</span></summary>'
                 f'<div class="diff-cols">{columns}</div></details>')
    saved = left_root / "comparisons" / f"comparison-{snapshot_identity(report)}.json"
    download = app._file_link(saved, "Download saved comparison (JSON)") if saved.exists() else ""
    benchmark_url = "/benchmark?" + urlencode(dict(left=left_id, right=right_id))
    body += f'''<section><h2>Transcript by transcript</h2><p class="muted">Open a transcript to see the passages only one run coded. Run A: {e(labels[left_id])}. Run B: {e(labels[right_id])}.</p>{rows}</section>
<section><h2>Keep a record</h2><p>Save this comparison with both runs' configuration fingerprints so it can be cited and reproduced.</p>
<div class="actions"><form method="post" action="/comparison/save"><input type="hidden" name="run_id" value="{e(left_id)}"><input type="hidden" name="right_id" value="{e(right_id)}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><button class="secondary">Save comparison</button></form>
<a href="{e(benchmark_url)}">Detailed span benchmark</a> {download}</div>
<details><summary>Proposals left out, and configuration details</summary><pre class="source-preview">{e(json.dumps({"run_a_excluded": report["left"]["excluded"], "run_b_excluded": report["right"]["excluded"], "run_a_configuration": report["left"]["configuration_fingerprint"], "run_b_configuration": report["right"]["configuration_fingerprint"]}, indent=2))}</pre></details></section>{tools}'''
    return app._render_workspace_page(title="Compare runs", intro="See where two coding runs agree and differ.", body=body, active="compare")
