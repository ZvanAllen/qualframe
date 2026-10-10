# ruff: noqa: E501
"""Detailed raw-span benchmark inside the local researcher workspace."""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import urlencode

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.benchmark_reporting import (
    benchmark_bundle_directory,
    benchmark_csv,
    write_benchmark_bundle,
)
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import raw_coding_payload

LABELS = {
    "exact": "Exact span F1",
    "iou_0_25": "Overlap F1 at 0.25",
    "iou_0_50": "Overlap F1 at 0.50",
    "iou_0_75": "Overlap F1 at 0.75",
}


def _pair(app, left_id: str, right_id: str) -> tuple[Path, dict]:
    app._managed_project_path()
    available = app.list_runs()
    if left_id not in available or right_id not in available:
        raise ValueError("Choose two coding runs from this study in Compare runs.")
    left_root = app._run_root(app.artifacts_dir, left_id)
    right_root = app._run_root(app.artifacts_dir, right_id)
    report = build_benchmark_report(
        raw_coding_payload(app.repo_root, left_root), raw_coding_payload(app.repo_root, right_root)
    )
    return left_root, report


def _value(value: float | None) -> str:
    return "Undefined" if value is None else f"{value:.1%}"


def _passage(reference: dict, run_id: str, originals: dict[str, dict]) -> str:
    e = html.escape
    identifier = reference["record_ids"][0]
    original = originals[identifier]
    link = "/evidence?" + urlencode(dict(run_id=run_id, item=identifier))
    return f'<p><a href="{e(link)}">{e(Path(reference["source"]).name)} / {reference["start"]}-{reference["end"]}</a></p><blockquote>{e(original["exact_text"])}</blockquote>'


def _code_details(
    row: dict, left_id: str, right_id: str, originals: dict[str, dict[str, dict]]
) -> str:
    measure = row["measures"]["iou_0_50"]
    e = html.escape
    if row.get("ambiguous_code_id"):
        return "<p>Ambiguous duplicate code ID in the frozen catalog. It has no included spans. See catalog diagnostics below.</p>"
    body = f"<p>At IoU 0.50: {measure['matched_spans']} matched span pairs; {measure['unmatched_left_count']} unmatched in the first run and {measure['unmatched_right_count']} in the second. Matched fractions: {_value(measure['matched_fraction_left'])} first, {_value(measure['matched_fraction_right'])} second.</p>"
    diagnostics = measure["boundary_diagnostics"]
    if diagnostics["matched_pairs"]:
        body += f"<p>Matched pairs only: median IoU {_value(diagnostics['median_iou'])}; median absolute start/end differences {diagnostics['median_absolute_start_difference']} / {diagnostics['median_absolute_end_difference']} characters. These diagnostics exclude unmatched spans.</p>"
    for match in measure["matches"][:8]:
        body += f"<h4>Matched pair / IoU {_value(match['iou'])}</h4><p>First run</p>" + _passage(
            match["left"], left_id, originals["left"]
        )
        body += "<p>Second run</p>" + _passage(match["right"], right_id, originals["right"])
    for side, run_id, label in [
        ("left", left_id, "First run unmatched"),
        ("right", right_id, "Second run unmatched"),
    ]:
        for reference in measure[f"unmatched_{side}"][:8]:
            body += f"<h4>{e(label)}</h4>" + _passage(reference, run_id, originals[side])
    if any(len(measure[key]) > 8 for key in ["matches", "unmatched_left", "unmatched_right"]):
        body += "<p>Showing up to eight examples in each category. The saved JSON includes every match and unmatched source reference at every threshold.</p>"
    return body


def _downloads(app, left_root: Path, report: dict) -> str:
    root = benchmark_bundle_directory(report, left_root / "benchmarks")
    path = root / "report.json"
    if not path.exists():
        return ""
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if snapshot_identity(saved) != snapshot_identity(report):
            raise ValueError("report identity mismatch")
        csv_path = root / "by_code.csv"
        if csv_path.read_bytes() != benchmark_csv(report).encode("utf-8"):
            raise ValueError("per-code CSV mismatch")
    except (OSError, ValueError, TypeError) as exc:
        return f'<p class="review-guidance">Saved benchmark files could not be verified: {html.escape(str(exc))}. Preserve them for inspection.</p>'
    return (
        "<p>"
        + app._file_link(path, "Download frozen benchmark JSON")
        + " / "
        + app._file_link(csv_path, "Download per-code CSV")
        + "</p>"
    )


def render_benchmark(app, left_id: str = "", right_id: str = "", message: str = "") -> str:
    e = html.escape
    app._managed_project_path()
    body = f'<p role="status">{e(message)}</p>' if message else ""
    back = (
        "/compare?" + urlencode(dict(left=left_id, right=right_id))
        if left_id and right_id
        else "/compare"
    )
    body += f'<p><a href="{e(back)}">Back to pairwise comparison</a> / <a href="/stability">Evaluate repeated runs</a></p>'
    if not left_id or not right_id:
        body += "<section><h2>Choose two coding runs first</h2><p>Open a compatible pair in Compare runs, then select Detailed span benchmark.</p></section>"
    else:
        left_root, report = _pair(app, left_id, right_id)
        identity = snapshot_identity(report)
        body += f'<section><h2>Exact and overlapping coded passages</h2><p>First run: <strong>{e(left_id)}</strong><br>Second run: <strong>{e(right_id)}</strong></p><p>These scores describe agreement between raw model proposals. Human edits and assumed test acceptance are excluded. Viewing this report makes no API requests.</p><div class="cards">'
        for key, label in LABELS.items():
            item = report["summary"][key]
            body += f'<div class="card"><div class="label">{label}</div><div class="value">{_value(item["f1_dice"])}</div><p>{item["matched_spans"]} matched pairs<br>{item["left_spans"]} first / {item["right_spans"]} second spans</p></div>'
        body += "</div><p>A match needs the same transcript and code; each passage can match only one passage in the other run. IoU means intersection divided by union of the two spans. F1 is twice the matched pairs divided by total spans. Thresholds are sensitivity choices, not qualitative correctness cutoffs.</p></section>"
        rows = ""
        for side, label in [("left", "First run"), ("right", "Second run")]:
            item = report["validity"][side]
            rows += f"<tr><th>{label}</th><td>{item['included_proposals']}</td><td>{item['excluded_proposals']} / {item['assessed_proposals']} ({_value(item['excluded_fraction'])})</td><td>{item['valid_absence_declarations']}</td><td>{item['duplicate_proposals']}</td><td>{item['unique_labelled_spans']}</td></tr>"
        body += f'<section><h2>What entered these scores</h2><div class="progress-table"><table><thead><tr><th>Run</th><th>Included proposals</th><th>Excluded / assessed</th><th>Absence declarations</th><th>Duplicates</th><th>Unique spans</th></tr></thead><tbody>{rows}</tbody></table></div><p>{e(report["validity_policy"])}</p></section>'
        originals = {
            side: {item["record_id"]: item for item in report["inputs"][side]["included"]}
            for side in ("left", "right")
        }
        rows, empty = "", []
        for row in sorted(
            report["by_code"], key=lambda item: (item["code_label"].casefold(), item["code_id"])
        ):
            if (
                not row["left_spans"]
                and not row["right_spans"]
                and not row.get("ambiguous_code_id")
            ):
                empty.append(row)
                continue
            scores = "".join(
                f"<td>{_value(row['measures'][name]['f1_dice'])}</td>" for name in LABELS
            )
            details = _code_details(row, left_id, right_id, originals)
            rows += f"<tr><th>{e(row['code_label'])}<br><code>{e(row['code_id'])}</code></th><td>{row['left_spans']} / {row['right_spans']}</td>{scores}<td><details><summary>Inspect passages</summary>{details}</details></td></tr>"
        body += f'<section><h2>By code</h2><p>First / second span counts are deduplicated within each code. Exact boundary agreement and overlapping evidence answer different questions.</p><div class="progress-table"><table><thead><tr><th>Code</th><th>Spans</th><th>Exact F1</th><th>IoU 0.25 F1</th><th>IoU 0.50 F1</th><th>IoU 0.75 F1</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>'
        if empty:
            body += (
                f"<details><summary>{len(empty)} codes with no spans in either run</summary><p>Scores are undefined. This does not establish that the construct is absent.</p><ul>"
                + "".join(f"<li>{e(row['code_label'])} / {e(row['code_id'])}</li>" for row in empty)
                + "</ul></details>"
            )
        macro = report["macro_by_code"]["iou_0_50"]
        body += f"<p>Macro per-code F1 at IoU 0.50: {_value(macro['mean_f1_dice'])} across {macro['defined_codes']} defined codes; {macro['undefined_codes']} undefined. It weights defined codes equally. The scorecards pool counts across codes.</p></section>"
        diagnostics = report.get("codebook_diagnostics", {})
        if diagnostics.get("duplicate_code_id_count"):
            items = "".join(
                f"<li>{e(item['code_id'])}: {e(', '.join(item['labels']))} / {item['entry_count']} entries; {'ambiguous definitions; no included spans' if item['ambiguous'] else 'identical duplicate entries; counted once'}.</li>"
                for item in diagnostics["duplicate_ids"]
            )
            body += f"<section><h2>Frozen catalog diagnostics</h2><p>{diagnostics['duplicate_code_id_count']} duplicated code ID(s). The original catalog is preserved; each ID contributes one per-code row.</p><ul>{items}</ul></section>"
        body += f'<section><h2>Preserve this benchmark</h2><p>Save an immutable local JSON, CSV and display report. The JSON retains source-linked matches, offsets, all thresholds and original input identities.</p><form method="post" action="/benchmark/save"><input type="hidden" name="run_id" value="{e(left_id)}"><input type="hidden" name="right_id" value="{e(right_id)}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><input type="hidden" name="report_id" value="{e(identity)}"><button>Save frozen span benchmark</button></form>{_downloads(app, left_root, report)}<details><summary>Matching policy and interpretation</summary><p>{e(report["matching_policy"]["tie_policy"])}</p><p>{e(report["empty_policy"])}</p><p>{e(report["limitations"])}</p></details></section>'
    return app._render_workspace_page(
        title="Detailed span benchmark",
        intro="Inspect exact boundaries, partial overlap and unmatched coding proposals.",
        body=body,
    )


def save_benchmark_form(app, form: dict[str, list[str]]) -> tuple[str, str]:
    def required(name: str) -> str:
        value = form.get(name, [""])[0].strip()
        if not value:
            raise ValueError(f"Missing benchmark field: {name}.")
        return value

    app._managed_project_path()
    if required("study_identity") != app.runner.project.project_id:
        raise ValueError("This tab belongs to another study. Reopen the benchmark.")
    left_id, right_id = required("run_id"), required("right_id")
    root, report = _pair(app, left_id, right_id)
    if required("report_id") != snapshot_identity(report):
        raise ValueError(
            "Benchmark inputs changed after display. Reopen and inspect the report before saving."
        )
    written = write_benchmark_bundle(report, root / "benchmarks")
    return left_id, f"Saved frozen span benchmark {written.parent.name[10:22]}."
