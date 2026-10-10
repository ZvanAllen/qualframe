"""Accessible multi-run report with explicit failed-run and pair denominators."""

from __future__ import annotations

import html
import json
from urllib.parse import urlencode

from qualframe.repeat_comparison import build_repeat_report
from qualframe.reviewed_analysis import snapshot_identity

LABELS = {
    "code_jaccard": "Code overlap",
    "exact_span_jaccard": "Exact passage overlap",
    "coverage_jaccard": "Coded-text overlap",
}
GROUP_LABELS = {
    "same_configuration": "Within the same frozen configuration",
    "different_configuration": "Between different frozen configurations",
    "unknown_configuration": "Configuration identity unavailable",
}


def render_stability(
    app, run_ids: list[str] | None = None, message: str = "", experiment_id: str = ""
) -> str:
    app._managed_project_path()
    e = html.escape
    available = app.list_runs()
    selected = run_ids or []
    experiment_context = None
    if experiment_id:
        from qualframe.repeat_comparison import experiment_report_scope

        selected, experiment_context = experiment_report_scope(
            app._managed_project_path(), experiment_id
        )
        available = list(dict.fromkeys(available + selected))
    if any(r not in available for r in selected):
        raise ValueError("Select runs from the current study.")
    body = f'<p role="status">{e(message)}</p>' if message else ""
    choices = "".join(
        f'<label><input type="checkbox" name="run" value="{e(r)}" {"checked" if r in selected else ""}> {e(r)}</label>'
        for r in available
    )
    body += f'<section><h2>Choose runs for an evaluation</h2><p>Choose 2 to 10 runs. Incomplete runs stay visible in the report. Comparisons require the same transcript cohort and codebook. No model requests are sent by this page.</p><p><a href="/repeats">Prepare repeated coding</a> · <a href="/compare">Inspect two runs</a></p><form action="/stability" method="get"><fieldset><legend>Include coding runs</legend>{choices or "<p>No coding runs yet.</p>"}</fieldset><button>Build evaluation report</button></form></section>'
    if experiment_context:
        body += "<p>This evaluation includes every planned repeat. Failed and not-started runs remain in its coverage counts. Changing the selection above creates a separate manual report.</p>"
    if selected:
        report = build_repeat_report(
            app.repo_root,
            [
                app.artifacts_dir / r if experiment_id else app._run_root(app.artifacts_dir, r)
                for r in selected
            ],
            experiment_context=experiment_context,
        )

        def pct(x: float | None) -> str:
            return "Undefined" if x is None else f"{x:.1%}"

        warnings = ""
        for failed in report["unavailable_runs"]:
            warnings += f"<li>{e(failed['run_id'])}: {e(failed['reason'])}</li>"
        for failed in report["incompatible_pairs"]:
            warnings += (
                f"<li>{e(failed['left'])} / {e(failed['right'])}: {e(failed['reason'])}</li>"
            )
        body += f'<section><h2>Report coverage</h2><div class="cards"><div class="card"><div class="label">Selected runs</div><div class="value">{report["selected_run_count"]}</div></div><div class="card"><div class="label">Usable runs</div><div class="value">{report["usable_run_count"]}</div></div><div class="card"><div class="label">Eligible pairs</div><div class="value">{report["eligible_pairs"]} / {report["possible_pairs"]}</div></div></div><ul>{warnings}</ul><p>{e(report["interpretation"])}</p></section>'
        rows = ""
        for p in report["runs"]:
            count = len(p["included"]) + len(p["excluded"])
            rate = len(p["excluded"]) / count if count else None
            models = sorted(
                {
                    f"{i.get('provider') or 'Unknown'} / {i.get('model') or 'Unknown'}"
                    for k in ("included", "excluded", "absences")
                    for i in p[k]
                }
            )
            rows += f"<tr><th>{e(p['run_id'])}</th><td>{e(', '.join(models) or 'No proposal model metadata')}</td><td>{len(p['included'])}</td><td>{len(p['excluded'])} / {count} ({pct(rate)})</td><td>{len(p['absences'])}</td></tr>"
        body += f'<section><h2>Output validity</h2><p>Excluded proposals have invalid codes or source spans. Exclusion rate uses included plus excluded proposals; valid absence declarations are counted separately. Overlap scores cover the valid subset and may overstate whole-output agreement.</p><div class="progress-table"><table><thead><tr><th>Run</th><th>Provider / model</th><th>Included</th><th>Excluded / assessed</th><th>Absences</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
        for group, summary in report["summaries"].items():
            if not summary["eligible_pairs"]:
                continue
            rows = "".join(
                f"<tr><th>{LABELS[key]}</th><td>{pct(item['mean'])}</td><td>{pct(item['minimum'])} – {pct(item['maximum'])}</td><td>{item['defined_pairs']} / {summary['eligible_pairs']}</td></tr>"
                for key, item in summary["metrics"].items()
            )
            body += f'<section><h2>{GROUP_LABELS[group]}</h2><div class="progress-table"><table><thead><tr><th>Measure</th><th>Pairwise mean</th><th>Minimum – maximum</th><th>Defined pairs</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
        pair_lookup = {
            frozenset((p["left"]["run_id"], p["right"]["run_id"])): p for p in report["pairs"]
        }
        heads = "".join(f'<th scope="col">Run {i + 1}</th>' for i, _ in enumerate(selected))
        rows = ""
        for i, left in enumerate(selected):
            cells = ""
            for right in selected:
                p = pair_lookup.get(frozenset((left, right)))
                if left == right:
                    cells += '<td aria-label="Same run, comparison not calculated">—</td>'
                elif p:
                    score = p["summary"]["coverage_jaccard"]
                    shade = 0 if score is None else round(8 + score * 28)
                    url = "/compare?" + urlencode(dict(left=left, right=right))
                    cells += f'<td style="background:rgba(53,125,119,{shade / 100})"><a href="{e(url)}" aria-label="Inspect {e(left)} and {e(right)}: coded-text overlap {pct(score)}">{pct(score)}</a></td>'
                else:
                    cells += "<td>Unavailable</td>"
            rows += f'<tr><th scope="row">Run {i + 1}</th>{cells}</tr>'
        legend = "".join(f"<li>Run {i + 1}: {e(r)}</li>" for i, r in enumerate(selected))
        path = (
            app.artifacts_dir / "comparison_reports" / f"stability-{snapshot_identity(report)}.json"
        )
        if path.exists() and snapshot_identity(
            json.loads(path.read_text(encoding="utf-8"))
        ) != snapshot_identity(report):
            raise ValueError("The saved evaluation report no longer matches its frozen identity.")
        download = app._file_link(path, "Download frozen evaluation JSON") if path.exists() else ""
        inputs = "".join(f'<input type="hidden" name="run" value="{e(r)}">' for r in selected)
        body += f'<section><h2>Coded-text overlap between runs</h2><p>Select a cell to inspect codes and source-boundary differences. Coverage counts Unicode character positions separately within each code, so multiply coded text contributes to each assigned code. Each pair is counted once in the summaries above. Empty unions are undefined.</p><div class="progress-table"><table><thead><tr><th>Run</th>{heads}</tr></thead><tbody>{rows}</tbody></table></div><ul>{legend}</ul><details><summary>Configuration and interpretation</summary><p>{e(report["configuration_policy"])}</p><p>{e(report["empty_policy"])}</p><p>These results do not establish correctness, saturation, thematic validity, or general reliability. No inferential confidence intervals are calculated.</p></details><form action="/stability/save" method="post"><input type="hidden" name="experiment" value="{e(experiment_id)}"><input type="hidden" name="report_id" value="{snapshot_identity(report)}">{inputs}<input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><button>Save frozen evaluation report</button></form><p>{download}</p></section>'
    return app._render_workspace_page(
        title="Evaluate repeat runs",
        intro="Examine stability across repeated coding and agreement across configurations.",
        body=body,
    )
