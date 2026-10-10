"""Immutable local benchmark bundles; no provider calls or human-reference claims."""

from __future__ import annotations

import csv
import io
import json
from html import escape
from pathlib import Path

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import compare_raw_payloads, raw_coding_payload

BUNDLE_FORMAT_VERSION = "display-v3"


def benchmark_bundle_directory(report: dict, output_root: Path) -> Path:
    """Keep display-format revisions separate from the scientific report identity."""
    return output_root / f"benchmark-{snapshot_identity(report)}-{BUNDLE_FORMAT_VERSION}"


def _number(value: float | None) -> str:
    return "Undefined" if value is None else f"{100 * value:.1f}%"


def _source_label(report: dict, source: str) -> str:
    for side in ("left", "right"):
        origin = report["inputs"][side].get("benchmark_provenance", {})
        mapping = origin.get("source_mapping", {})
        for entry in mapping.values():
            if entry.get("source_id") == source:
                return entry.get("original_path", source)
    return source


def _quote_sensitivity_notice(report: dict) -> str:
    if not any(
        value.get("benchmark_provenance", {}).get("quote_anchoring_policy")
        for value in report["inputs"].values()
    ):
        return ""
    sides = []
    for side in ("left", "right"):
        origin = report["inputs"][side].get("benchmark_provenance", {})
        policy = origin.get("quote_anchoring_policy")
        label = (
            "Casefold-only sensitivity: " + str(policy)
            if policy
            else "Strict quotation anchoring (existing whitespace and quote-typography rules)"
        )
        audit = origin.get("quote_anchoring_sensitivity", {})
        strict = audit.get("strict_counts", {}).get("included")
        revised = audit.get("sensitivity_counts", {}).get("included")
        counts = (
            f" Included proposals: {strict} under strict anchoring; {revised} under sensitivity."
            if type(strict) is int and type(revised) is int
            else ""
        )
        code_policy = str(origin.get("code_label_policy", "legacy_v1"))
        sides.append(
            f"<li>{side.title()}: {escape(label)}.{escape(counts)} "
            f"Code-label policy: {escape(code_policy)}.</li>"
        )
    return (
        '<section class="note" aria-label="Quotation anchoring sensitivity">'
        "<h2>Quotation anchoring sensitivity</h2>"
        "<p>These scores include an explicitly selected casefold-only sensitivity. "
        "Unique case-insensitive matches retain their original source slices and model "
        "quotations. They do not establish semantic correctness or human approval. "
        "Interpret these results alongside the separate strict report.</p>"
        "<ul>" + "".join(sides) + "</ul>"
        "<p>Punctuation and word changes are not repaired. Unresolved code labels and "
        "other blocking issues remain excluded. Full strict exclusions and each "
        "sensitivity attempt are retained in the JSON audit.</p></section>"
    )


def benchmark_csv(report: dict) -> str:
    """Per-code support and measures; neutralize spreadsheet formula strings."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "code_id",
            "code_label",
            "left_spans",
            "right_spans",
            "exact_f1",
            "iou_025_f1",
            "iou_050_f1",
            "iou_075_f1",
            "matched_at_050",
        ]
    )
    for row in report["by_code"]:
        fields = [row["code_id"], row["code_label"], row["left_spans"], row["right_spans"]]
        fields.extend(
            row["measures"][name]["f1_dice"]
            for name in ("exact", "iou_0_25", "iou_0_50", "iou_0_75")
        )
        fields.append(row["measures"]["iou_0_50"]["matched_spans"])
        writer.writerow(
            [
                "'" + field
                if isinstance(field, str) and field.lstrip().startswith(("=", "+", "-", "@"))
                else field
                for field in fields
            ]
        )
    return output.getvalue()


def render_benchmark_html(report: dict) -> str:
    """Standalone metadata-only view; full source-linked details remain in JSON."""
    left, right = report["inputs"]["left"], report["inputs"]["right"]
    overlap = compare_raw_payloads(left, right)
    title = "Coding agreement benchmark"
    cards = []
    for key, label in (
        ("exact", "Exact span agreement"),
        ("iou_0_25", "Overlap at 0.25"),
        ("iou_0_50", "Overlap at 0.50"),
        ("iou_0_75", "Overlap at 0.75"),
    ):
        value = report["summary"][key]
        cards.append(
            f"<article><p>{label}</p><strong>{_number(value['f1_dice'])}</strong>"
            f"<small>{value['matched_spans']} matched pairs; "
            f"{value['left_spans']} left / {value['right_spans']} right spans</small></article>"
        )
    inputs = []
    for side in ("left", "right"):
        value = report["validity"][side]
        run = report["inputs"][side]
        models = sorted(
            {
                str(item.get("model", "Unknown"))
                for name in ("included", "excluded", "absences")
                for item in run[name]
            }
        )
        inputs.append(
            f"<tr><th>{side.title()}</th><td>{escape(run['run_id'])}"
            f"<small>{escape(', '.join(models) or 'Model unavailable')}</small></td>"
            f"<td>{value['included_proposals']}</td><td>{value['excluded_proposals']}</td>"
            f"<td>{value['valid_absence_declarations']}</td>"
            f"<td>{value['duplicate_proposals']}</td></tr>"
        )
    sources = []
    for row in report["by_source"]:
        scores = row["measures"]
        label = _source_label(report, row["source"])
        sources.append(
            f"<tr><th>{escape(label)}</th><td>{_number(scores['exact']['f1_dice'])}</td>"
            f"<td>{_number(scores['iou_0_50']['f1_dice'])}</td>"
            f"<td>{scores['iou_0_50']['left_spans']} / "
            f"{scores['iou_0_50']['right_spans']}</td></tr>"
        )
    codes = []
    for row in sorted(
        report["by_code"], key=lambda item: (item["code_label"].casefold(), item["code_id"])
    ):
        if not row["left_spans"] and not row["right_spans"]:
            continue
        values = "".join(
            f"<td>{_number(row['measures'][name]['f1_dice'])}</td>"
            for name in ("exact", "iou_0_25", "iou_0_50", "iou_0_75")
        )
        codes.append(
            f"<tr><th>{escape(row['code_label'])}<small>{escape(row['code_id'])}</small></th>"
            f"<td>{row['left_spans']} / {row['right_spans']}</td>{values}</tr>"
        )
    macros = report["macro_by_code"]["iou_0_50"]
    cautions = [
        report["interpretation"],
        report["validity_policy"],
        report["aggregation"],
        report["empty_policy"],
        report["limitations"],
    ]
    if any(run.get("benchmark_provenance") for run in (left, right)):
        cautions.insert(
            0,
            "Historical normalization: selected sources are explicitly mapped by file and "
            "extracted-text hashes. Original configuration/codebook provenance may be "
            "incomplete. This is exploratory; model-only effects are not established.",
        )
    assumption = any(
        run.get("benchmark_provenance", {}).get("test_assumption") for run in (left, right)
    )
    if assumption:
        cautions.insert(
            0,
            "TEST ONLY: acceptance was assumed for pipeline execution. "
            "No human-reference labels or acceptance-rate evidence were created.",
        )
    duplicates = report.get("codebook_diagnostics", {}).get("duplicate_ids", [])
    if duplicates:
        cautions.append(
            "The frozen catalog contains repeated code identifiers. Each identifier is "
            "counted once; ambiguous identifiers cannot contribute included spans. "
            "Full catalog entries and diagnostics are retained in the JSON: "
            + ", ".join(str(item.get("code_id", item)) for item in duplicates)
        )
    caution_html = "".join(f"<li>{escape(text)}</li>" for text in cautions)
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root{{color-scheme:light;
font-family:system-ui,sans-serif;
color:#18302e;
background:#f3f6f4}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1180px;
margin:auto;
padding:36px 24px 60px}}
h1{{font-size:clamp(1.9rem,4vw,2.8rem);
margin:8px 0 14px;
line-height:1.14}}h2{{font-size:1.2rem;
margin-top:32px}}
p,li{{line-height:1.6}}.eyebrow{{color:#47615b;
font-size:.8rem;
letter-spacing:.09em;
font-weight:650;
text-transform:uppercase}}
.cards{{display:grid;
grid-template-columns:repeat(4,minmax(0,1fr));
gap:14px;
margin:26px 0}}
article{{border:1px solid #d4dfd8;
border-radius:12px;
background:white;
padding:18px}}
article p{{margin:0 0 10px;
font-size:.9rem}}strong{{display:block;
font-size:2rem;
font-weight:650}}
small{{display:block;
font-size:.77rem;
line-height:1.5;
color:#526760;
margin-top:6px;
overflow-wrap:anywhere}}
.table{{overflow-x:auto;
background:white;
border:1px solid #d4dfd8;
border-radius:10px}}
table{{border-collapse:collapse;
width:100%;
font-size:.86rem}}td,th{{padding:12px;
text-align:left;
border-bottom:1px solid #e1e8e2}}
thead th{{background:#eaf1ec;
font-size:.79rem}}tbody th{{font-weight:550;
max-width:340px;
overflow-wrap:anywhere}}
td{{overflow-wrap:anywhere}}.note{{padding:14px 20px;
border-left:4px solid #ad7a28;
background:#fff8e9}}
a{{color:#1e5f51}}nav{{display:flex;
gap:22px;
flex-wrap:wrap;
margin:22px 0}}.details{{overflow-wrap:anywhere;
font-size:.9rem;
color:#415a52}}
@media(max-width:700px){{main{{padding:24px 14px
42px}}.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}article{{padding:14px}}strong{{font-size:1.65rem}}td,th{{padding:10px}}}}
</style>
<main>
<div class="eyebrow">QualFrame · local evaluation</div>
<h1>{title}</h1>
<p>How closely do two sets of proposed codes agree on these transcripts?</p>
<div class="note">Descriptive agreement of source-valid proposals. These scores do not measure
qualitative accuracy or human agreement.</div>
{_quote_sensitivity_notice(report)}
<div class="cards">{"".join(cards)}</div>
<p class="details">Each overlapping match must use the same source and code. A proposal matches at
most one proposal in the other run. The overlap threshold is intersection divided by union of the
two source spans. F1 is twice the matched pairs divided by total spans.</p>
<nav>
<a href="report.json">Full report and source-linked differences (JSON)</a>
<a href="by_code.csv">Per-code results (CSV)</a>
</nav>
<h2>What entered the comparison</h2>
<div class="table">
<table>
<thead>
<tr>
<th>Side</th>
<th>Run</th>
<th>Included proposals</th>
<th>Excluded proposals</th>
<th>Absence declarations</th>
<th>Duplicates</th>
</tr>
</thead>
<tbody>{"".join(inputs)}</tbody>
</table>
</div>
<p class="details">Duplicates remain in included proposal counts but count once in span scores.
Absence declarations are separate from passage matches. Exclusions are not silently treated as
uncoded text.</p>
<h2>Complementary measures</h2>
<p>Same-code text coverage Jaccard: <b>{_number(overlap["summary"]["coverage_jaccard"])}</b>.
Transcript-code set Jaccard: <b>{_number(overlap["summary"]["code_jaccard"])}</b>. Macro per-code
F1 at 0.50: <b>{_number(macros["mean_f1_dice"])}</b> across {macros["defined_codes"]} codes;
 {macros["undefined_codes"]} codes have no spans in either output.</p>
<p class="details">Code overlap pools {overlap["totals"]["code_jaccard"]["intersection"]}
shared transcript-code entries over {overlap["totals"]["code_jaccard"]["union"]} entries in
either run. It does not estimate participant or determinant prevalence.</p>
<h2>By transcript</h2>
<div class="table">
<table>
<thead>
<tr>
<th>Source</th>
<th>Exact F1</th>
<th>Overlap F1 at 0.50</th>
<th>Left / right spans</th>
</tr>
</thead>
<tbody>{"".join(sources)}</tbody>
</table>
</div>
<h2>By code</h2>
<p class="details">Only codes with at least one valid span are shown here. The JSON and CSV retain
all codes and undefined scores.</p>
<div class="table">
<table>
<thead>
<tr>
<th>Code</th>
<th>Left / right spans</th>
<th>Exact F1</th>
<th>IoU 0.25 F1</th>
<th>IoU 0.50 F1</th>
<th>IoU 0.75 F1</th>
</tr>
</thead>
<tbody>{"".join(codes)}</tbody>
</table>
</div>
<h2>Interpretation limits</h2>
<ul>{caution_html}</ul>
<p class="details">Metric version: {escape(report["metric_version"])}. Report identity:
{snapshot_identity(report)}.</p>
</main>
</html>"""


def write_benchmark_bundle(report: dict, output_root: Path, *, dry_run: bool = False) -> Path:
    """Write a content-addressed bundle, verifying rather than overwriting repeats."""
    if report.get("kind") != "qualframe_benchmark_report_v1":
        raise ValueError("Expected a QualFrame span benchmark report.")
    directory = benchmark_bundle_directory(report, output_root)
    files = {
        "report.json": json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        "by_code.csv": benchmark_csv(report),
        "index.html": render_benchmark_html(report),
    }
    if not dry_run:
        # Check all existing files before creating anything in a repeated bundle.
        for name, text in files.items():
            path = directory / name
            if path.exists() and path.read_bytes() != text.encode("utf-8"):
                raise ValueError(
                    "Stored benchmark bundle changed; preserve it and select a new output root."
                )
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            path = directory / name
            if not path.exists():
                with path.open("xb") as stream:
                    stream.write(text.encode("utf-8"))
    return directory / "index.html"


def write_run_benchmark(
    repo_root: Path, left_root: Path, right_root: Path, *, dry_run: bool = False
) -> Path:
    report = build_benchmark_report(
        raw_coding_payload(repo_root, left_root), raw_coding_payload(repo_root, right_root)
    )
    return write_benchmark_bundle(report, left_root / "benchmarks", dry_run=dry_run)
