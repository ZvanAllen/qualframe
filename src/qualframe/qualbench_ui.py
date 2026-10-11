"""QualBench in the workspace: choose coding runs and references, build a report, read it."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from qualframe.comparison_ui import _run_label, _run_setup
from qualframe.qualbench import build_qualbench, reference_coding_set, run_coding_set, write_qualbench
from qualframe.reference_coding import (
    build_reference_coding,
    list_references,
    load_reference_coding,
    reference_folder,
    save_reference_coding,
)

e = html.escape


def _reports_root(app) -> Path:
    return app.exports_dir / "qualbench"


def _references(app) -> list[dict]:
    found = []
    for path in list_references(app._managed_project_path()):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found.append(dict(id=data["reference_id"], label=data["label"], statement=data["statement"],
                          transcripts=len(data["sources"]), path=path))
    return found


def _runs(app) -> list[str]:
    return [r for r in app.list_runs() if (app.artifacts_dir / r / "evidence_review/index.json").exists()
            and (app.artifacts_dir / r / "run_manifest.json").exists()]


def build_qualbench_form(app, form: dict[str, list[str]]) -> tuple[str, str]:
    """Build a report from the chosen runs and reference. Returns (report id, message)."""
    if form.get("study_identity", [""])[0] != app.runner.project.project_id:
        raise ValueError("This tab belongs to another study. Reopen it before building a report.")
    runs, references = _runs(app), {r["id"]: r for r in _references(app)}
    chosen = [r for r in form.get("run", []) if r in runs]
    reference_id = form.get("reference", [""])[0]
    if reference_id and reference_id not in references:
        raise ValueError("Choose a reference coding from this study.")
    if len(chosen) + (1 if reference_id else 0) < 2:
        raise ValueError("Choose at least two runs, or one run and a reference coding.")
    sets = [run_coding_set(app.repo_root, app.artifacts_dir / r) for r in chosen]
    for coding_set in sets:
        coding_set["label"] = _run_label(app, coding_set["set_id"])
    reference = None
    if reference_id:
        reference = reference_coding_set(load_reference_coding(references[reference_id]["path"], app.repo_root))
    # Runs with the same model, instructions and options are repeats: report their stability too.
    groups: dict[tuple, list[str]] = {}
    for run_id in chosen:
        setup = _run_setup(app, run_id, {})
        groups.setdefault(tuple(setup.values()), []).append(run_id)
    report = build_qualbench(sets, reference=reference,
                             stability_groups=[ids for ids in groups.values() if len(ids) > 1])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_qualbench(report, _reports_root(app) / stamp)
    count = len(report["transcripts"])
    return stamp, f"Built a QualBench report on {count} transcript{'' if count == 1 else 's'}."


def _tokens(name: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9]+", name)}


def match_workbooks(transcripts: list[Path], workbooks: list[str]) -> dict[str, Path]:
    """Pair each workbook with the transcript it codes, from the file names.

    A transcript whose name starts with an ID containing a digit (such as 12A) matches a workbook
    whose name contains that ID; otherwise the workbook name must contain the transcript's name.
    """
    def matches(transcript: Path, workbook: str) -> bool:
        first = re.match(r"[A-Za-z0-9]+", transcript.stem)
        if first and re.search(r"\d", first.group(0)):
            return first.group(0).casefold() in _tokens(Path(workbook).stem)
        squash = lambda text: re.sub(r"[^a-z0-9]", "", text.casefold())
        return squash(transcript.stem) in squash(Path(workbook).stem)

    paired: dict[str, Path] = {}
    problems = []
    for workbook in workbooks:
        found = [t for t in transcripts if matches(t, workbook)]
        if len(found) != 1:
            problems.append(f"{workbook} matches {'no transcript' if not found else f'{len(found)} transcripts'}")
        else:
            paired[workbook] = found[0]
    taken = [t for t in paired.values()]
    doubled = sorted({t.name for t in taken if taken.count(t) > 1})
    if doubled:
        problems.append("more than one workbook for " + ", ".join(doubled))
    if problems:
        raise ValueError("Each workbook needs one transcript, named so it includes the transcript's ID "
                         "(for example 12A): " + "; ".join(problems) + ".")
    return paired


def import_reference_upload(app, fields: dict[str, list[str]], uploads: list) -> str:
    """Import uploaded CFIR coding workbooks as a reference coding. Returns a message."""
    import shutil
    from uuid import uuid4

    project = app._managed_project_path()
    label = " ".join(fields.get("label", [""])[0].split())
    statement = " ".join(fields.get("statement", [""])[0].split())
    if not label or not statement:
        raise ValueError("Give the earlier coding a name and say how it was coded and reviewed.")
    base = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:48] or "reference"
    base = base if len(base) >= 3 else f"{base}-ref"
    reference_id, number = base, 2
    while reference_folder(project, reference_id).exists():
        reference_id, number = f"{base}-{number}", number + 1
    names = [app.study_workspace._safe_filename(u.filename, {".xlsx", ".xlsm"}) for u in uploads]
    if len(set(names)) != len(names):
        raise ValueError("Two workbooks have the same name.")
    paired = match_workbooks(app.runner._transcript_files(), names)
    staging = project.parent / "references" / ".staging" / uuid4().hex
    staging.mkdir(parents=True)
    try:
        files = {}
        for name, upload in zip(names, uploads):
            path = staging / name
            path.write_bytes(upload.content)
            files[paired[name].resolve().relative_to(app.repo_root).as_posix()] = path
        payload = build_reference_coding(repo_root=app.repo_root, project_path=project, reference_id=reference_id,
                                         label=label, statement=statement, files=files,
                                         created_by=fields.get("actor", [""])[0] or app.researcher)
        for source, entry in payload["files"].items():
            entry["original_path"] = entry["workbook"]
        save_reference_coding(project, payload, files)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    counts = payload["counts"]
    count = len(payload["sources"])
    return (f"Imported {label}: {count} transcript{'' if count == 1 else 's'}, {counts['included']} quotations found in the "
            f"transcripts, {counts['quotations_not_found']} not found, {counts['unmatched_constructs']} construct names "
            f"not matched to the codebook.")


def _import_form(app, references: list[dict]) -> str:
    if app.runner.codebook is not None or not any(s.domain_iterations for s in app.runner.pipeline.stages):
        return ""
    listed = "".join(f'<li><strong>{e(r["label"])}</strong> ({r["transcripts"]} transcript{"" if r["transcripts"] == 1 else "s"}). '
                     f'<span class="muted">{e(r["statement"])}</span></li>' for r in references)
    listed = f'<h2>Earlier codings</h2><ul>{listed}</ul>' if listed else ""
    return (f'<section>{listed}<details><summary>Import an earlier coding of these transcripts</summary>'
            '<p>Workbooks in the published CFIR table format: one sheet per domain with CFIR Construct, Quote and '
            'Explanation columns, one workbook per transcript. Name each file so it includes the transcript\'s ID, '
            'for example <em>12A coding.xlsx</em>. Construct names are matched to the codebook and quotations are '
            'found in the transcripts; reviewer note columns are kept.</p>'
            '<form method="post" action="/import/reference-coding" enctype="multipart/form-data">'
            '<label>Name<input name="label" required placeholder="Phase 1a transcript coding"></label>'
            '<label>How it was coded and reviewed<textarea name="statement" rows="3" required '
            'placeholder="For example: model output from the published prompts, reviewed by two team members."></textarea>'
            '<small>Shown with every report that uses it.</small></label>'
            '<label>Workbooks<input type="file" name="upload" accept=".xlsx,.xlsm" multiple required></label>'
            '<button class="secondary">Import</button></form></details></section>')


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _num(value, places: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{places}f}"


def _money(value) -> str:
    return "" if value in (None, "") else f"${value:,.2f}"


def _minutes(seconds) -> str:
    if not seconds:
        return ""
    return f"{seconds / 60:.0f} min" if seconds >= 90 else f"{seconds:.0f} s"


def _chooser(app, runs: list[str], references: list[dict]) -> str:
    if not runs:
        return ('<div class="next-up"><div><h2>Code the study first</h2><p>QualBench compares coding runs with each '
                'other and with an earlier coding of the same transcripts.</p></div><a class="button" href="/configure">Run coding</a></div>')
    run_boxes = "".join(
        f'<label class="check"><input type="checkbox" name="run" value="{e(r)}"{" checked" if i < 2 else ""}>'
        f'<span>{e(_run_label(app, r))}</span></label>' for i, r in enumerate(runs))
    if references:
        reference_options = '<label class="check"><input type="radio" name="reference" value="" ><span>None</span></label>' + "".join(
            f'<label class="check"><input type="radio" name="reference" value="{e(r["id"])}"{" checked" if i == 0 else ""}>'
            f'<span>{e(r["label"])} <small class="muted">({r["transcripts"]} transcripts) {e(r["statement"])}</small></span></label>'
            for i, r in enumerate(references))
        reference_field = f'<fieldset><legend>Compare with an earlier coding</legend>{reference_options}</fieldset>'
    else:
        reference_field = ('<p class="muted">No earlier coding of these transcripts has been imported. With one, QualBench also '
                           'reports how closely each run reproduces it.</p>')
    return (f'<section><h2>Build a report</h2><form method="post" action="/qualbench/build">'
            f'<input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">'
            f'<fieldset><legend>Coding runs</legend><div class="sample-groups">{run_boxes}</div></fieldset>{reference_field}'
            f'<p class="muted">Runs with the same model, instructions and options are treated as repeats, and their stability is reported. '
            f'Comparisons use the transcripts every chosen run coded, and the model\'s proposals before review.</p>'
            f'<button>Build report</button></form></section>')


def _report_html(app, folder: Path) -> str:
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    names = {s["set_id"]: s["label"] for s in report["coding_sets"]}
    name = lambda set_id: e(names.get(set_id, set_id))
    out = ""
    reference = report.get("reference")
    if reference:
        out += (f'<div class="notice"><strong>About the reference.</strong> {e(reference["statement"])} '
                f'It is compared as another coding, not as the right answer.</div>')
    rows = "".join(
        f'<tr><td>{name(s["set_id"])}</td><td>{s["transcripts"]}</td><td>{s["coded_passages"]}</td>'
        f'<td>{_pct(s["share_located"])}</td><td>{_num(s["codes_present_per_transcript"], 1)}</td>'
        f'<td>{_money(s.get("cost_usd"))}</td><td>{_minutes(s.get("elapsed_seconds"))}</td></tr>'
        for s in report["coding_sets"])
    omitted = report.get("transcripts_left_out") or []
    count = len(report["transcripts"])
    scope = (f'{count} transcript{"" if count == 1 else "s"} that every coding set covers'
             + (f'; {len(omitted)} covered by only some are left out' if omitted else ""))
    out += (f'<section><div class="section-head"><h2>Coding sets</h2><span class="muted">{e(scope)}</span></div>'
            f'<div class="progress-table"><table><thead><tr><th>Coding</th><th>Transcripts</th><th>Coded passages</th>'
            f'<th>Quotations found</th><th>Codes per transcript</th><th>Cost</th><th>Time</th></tr></thead><tbody>{rows}</tbody></table></div></section>')

    def presence_table(level: str, scope_kind: str) -> str:
        chosen = [r for r in report["presence"] if r["level"] == level and r["scope_kind"] == scope_kind]
        if not chosen:
            return ""
        lines = "".join(
            f'<tr><td>{name(r["left"])}</td><td>{name(r["right"])}</td>'
            + (f'<td>{e(r["scope"])}</td>' if scope_kind != "all" else "")
            + f'<td>{r["n_units"]}</td><td>{_pct(r["percent_agreement"])}</td><td>{_num(r["cohen_kappa"])}</td>'
            f'<td>{_num(r["gwet_ac1"])}</td><td>{_num(r["precision"])}</td><td>{_num(r["recall"])}</td><td>{_num(r["f1"])}</td></tr>'
            for r in chosen)
        head = "<th>Coding</th><th>Compared with</th>" + ("<th>Scope</th>" if scope_kind != "all" else "")
        return (f'<div class="progress-table"><table><thead><tr>{head}<th>Units</th><th>Agreement</th><th>Kappa</th><th>AC1</th>'
                f'<th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{lines}</tbody></table></div>')

    merged = presence_table("parent code", "all")
    out += (f'<section><div class="section-head"><h2>Which codes were applied</h2><span class="muted">One unit per transcript and code</span></div>'
            f'{presence_table("code", "all")}'
            f'<p class="muted">Agreement counts units where both say present or both say absent. Kappa and AC1 correct for chance; '
            f'AC1 stays stable when most codes are absent or most are present. Precision, recall and F1 appear only against the reference.</p>'
            + (f'<details><summary>With sub-codes merged into their parent codes</summary>{merged}</details>' if merged else "")
            + f'<details><summary>By domain</summary>{presence_table("code", "domain")}</details>'
            f'<details><summary>By transcript</summary>{presence_table("code", "transcript")}</details></section>')
    lines = "".join(
        f'<tr><td>{name(r["left"])}</td><td>{name(r["right"])}</td><td>{r["left_passages"]} / {r["right_passages"]}</td>'
        f'<td>{_num(r["f1_exact"])}</td><td>{_num(r["f1_iou_half"])}</td><td>{_num(r["f1_any_overlap"])}</td>'
        f'<td>{_pct(r["coded_text_jaccard"])}</td></tr>' for r in report["passages"])
    out += (f'<section><div class="section-head"><h2>Which passages were coded</h2><span class="muted">Same code, same transcript</span></div>'
            f'<div class="progress-table"><table><thead><tr><th>Coding</th><th>Compared with</th><th>Passages</th><th>F1, exact</th>'
            f'<th>F1, mostly overlapping</th><th>F1, any overlap</th><th>Same text coded</th></tr></thead><tbody>{lines}</tbody></table></div>'
            f'<p class="muted">Passages are matched one to one. Mostly overlapping means the shared text is at least half of the two passages combined. '
            f'Same text coded is the share of characters either coding marked with a code that both marked with it.</p></section>')
    if report["stability"]:
        lines = "".join(
            f'<tr><td>{e(", ".join(names.get(i, i) for i in r["group"].split(" + ")))}</td><td>{e(r["level"])}</td>'
            f'<td>{r["n_units"]}</td><td>{_num(r["krippendorff_alpha"])}</td><td>{_pct(r["units_all_agree"])}</td></tr>'
            for r in report["stability"])
        out += (f'<section><h2>Stability across repeats</h2><div class="progress-table"><table><thead><tr><th>Repeat runs</th><th>Level</th>'
                f'<th>Units</th><th>Krippendorff\'s alpha</th><th>Units where all agree</th></tr></thead><tbody>{lines}</tbody></table></div></section>')
    links = " / ".join(app._file_link(folder / f, label) for f, label in (
        ("presence.csv", "Code agreement (CSV)"), ("passages.csv", "Passage agreement (CSV)"),
        ("coding_sets.csv", "Coding sets (CSV)"), ("units.csv", "Unit-level data (CSV)"),
        ("README.md", "Definitions"), ("report.json", "Full report (JSON)")) if (folder / f).exists())
    out += f'<section><h2>Files</h2><p>{links}</p><p class="muted">Saved in the study\'s exports folder, qualbench/{e(folder.name)}.</p></section>'
    # Figures right-aligned and kept on one line.
    out = out.replace("<table>", '<table class="bench">')
    return re.sub(r"<td>((?:n/a|\$?[\d.,]+%?(?: / [\d.,]+)?(?: min| s)?)?)</td>", r'<td class="n">\1</td>', out)


def render_qualbench(app, report_id: str = "", message: str = "", error: str = "") -> str:
    app._managed_project_path()
    runs, references = _runs(app), _references(app)
    body = f'<div class="message" role="status">{e(message)}</div>' if message else ""
    body += f'<div class="error" role="alert">{e(error)}</div>' if error else ""
    root = _reports_root(app)
    saved = sorted((p for p in root.glob("*/report.json")), reverse=True) if root.exists() else []
    if report_id and not re.fullmatch(r"\d{8}T\d{6}Z", report_id):
        raise ValueError("Choose a saved QualBench report.")
    current = root / report_id if report_id else (saved[0].parent if saved else None)
    if current is not None and (current / "report.json").exists():
        when = datetime.strptime(current.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        body += f'<p class="muted">Report built {e(when.strftime("%d %B %Y, %H:%M UTC"))}.</p>' + _report_html(app, current)
    body += _chooser(app, runs, references) + _import_form(app, references)
    if len(saved) > 1:
        items = "".join(f'<li><a href="/qualbench?{urlencode({"report": p.parent.name})}">{e(p.parent.name)}</a></li>' for p in saved)
        body += f'<section><details><summary>Earlier reports ({len(saved)})</summary><ul>{items}</ul></details></section>'
    return app._render_workspace_page(
        title="QualBench", active="qualbench", wide=True,
        intro="Agreement among coding runs, and with an earlier coding of the same transcripts, as tables you can report.",
        body=body)
