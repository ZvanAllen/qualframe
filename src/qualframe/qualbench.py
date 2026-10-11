"""QualBench: agreement, stability and process measures for coding runs and reference codings.

Inputs are coding sets: a run's original model proposals (before review) or an imported
reference coding. No provider calls are made and nothing in the study is changed. The report is a
set of tidy tables for R or Python, with the definitions written alongside.

Units of analysis
- Presence: one unit per transcript and code. A code is present when the coding set applied it
  to that transcript at least once, whether or not its quotation was found in the transcript.
  Codes are compared as coded, and again with sub-codes merged into their parent code.
- Passages: located quotations, compared within the same transcript and code.

Nothing here treats one coding set as correct. With a reference, precision is the share of the
coding set's present codes that the reference also has, and recall the share of the reference's
present codes that the coding set also has.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean, median

from qualframe.benchmark_metrics import _Span, _maximum_matching
from qualframe.run_comparison import interval_overlap, raw_coding_payload

KIND = "qualframe_qualbench_v1"
_ANY_OVERLAP = (1, 10**12)
_IOU_HALF = (1, 2)
_EXACT = (1, 1)


# ---------------------------------------------------------------- statistics

def agreement_statistics(both: int, left_only: int, right_only: int, neither: int) -> dict:
    """Two-coder agreement on a present/absent judgement for each unit."""
    n = both + left_only + right_only + neither
    if n == 0:
        return dict(n_units=0, percent_agreement=None, cohen_kappa=None, gwet_ac1=None, pabak=None, jaccard=None)
    observed = (both + neither) / n
    left_yes, right_yes = (both + left_only) / n, (both + right_only) / n
    expected = left_yes * right_yes + (1 - left_yes) * (1 - right_yes)
    kappa = None if expected >= 1 else (observed - expected) / (1 - expected)
    prevalence = (left_yes + right_yes) / 2
    chance_ac1 = 2 * prevalence * (1 - prevalence)
    ac1 = (observed - chance_ac1) / (1 - chance_ac1)
    present = both + left_only + right_only
    return dict(
        n_units=n,
        percent_agreement=observed,
        cohen_kappa=kappa,
        gwet_ac1=ac1,
        pabak=2 * observed - 1,
        jaccard=both / present if present else None,
    )


def reference_statistics(both: int, left_only: int, right_only: int) -> dict:
    """The left coding set judged against a reference on the right."""
    return dict(
        precision=both / (both + left_only) if both + left_only else None,
        recall=both / (both + right_only) if both + right_only else None,
        f1=2 * both / (2 * both + left_only + right_only) if both + left_only + right_only else None,
    )


def krippendorff_alpha_nominal(units: list[list]) -> float | None:
    """Krippendorff's alpha for nominal values; each unit lists the values its coders gave."""
    coincidences: Counter = Counter()
    for values in units:
        m = len(values)
        if m < 2:
            continue
        counts = Counter(values)
        for c in counts:
            for k in counts:
                pairs = counts[c] * (counts[k] - (1 if c == k else 0))
                if pairs:
                    coincidences[(c, k)] += pairs / (m - 1)
    totals: Counter = Counter()
    for (c, _), value in coincidences.items():
        totals[c] += value
    n = sum(totals.values())
    if n <= 1:
        return None
    disagreement = sum(value for (c, k), value in coincidences.items() if c != k)
    expected = sum(totals[c] * totals[k] for c in totals for k in totals if c != k) / (n - 1)
    if expected == 0:
        return None
    return 1 - disagreement / expected


# ---------------------------------------------------------------- coding sets

def _domain(code: dict) -> str:
    domain = str(code.get("domain") or "").strip()
    if not domain:
        return "All codes"
    return re.sub(r"\s+domain$", "", domain, flags=re.IGNORECASE).title()


def parent_projection(codebook: dict) -> dict[str, str]:
    """Each code mapped to its top-level code (itself if it has no parent)."""
    codes = codebook.get("codes", [])
    by_id = {code["id"]: code for code in codes}
    parents: dict[str, str] = {}
    for code in codes:
        parent = code.get("parent_id")
        if parent is None and code.get("parent_label"):
            matches = [c["id"] for c in codes if c.get("raw_label") == code["parent_label"]
                       and c.get("domain") == code.get("domain") and not c.get("parent_label")]
            parent = matches[0] if len(matches) == 1 else None
        parents[code["id"]] = parent if parent in by_id else code["id"]
    for code_id in list(parents):  # follow chains to the top
        seen = {code_id}
        while parents[parents[code_id]] != parents[code_id] and parents[code_id] not in seen:
            seen.add(parents[code_id])
            parents[code_id] = parents[parents[code_id]]
    return parents


def run_coding_set(repo_root: Path, run_root: Path) -> dict:
    """A run's original model proposals as a coding set, with its model, cost and time."""
    payload = raw_coding_payload(repo_root, run_root)
    settings_path = run_root / "run_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    provider = settings.get("provider") or {}
    usage = dict(requests=0, input_tokens=0, output_tokens=0, cost_usd=0.0)
    ledger = run_root.parents[1] / "logs/cost_ledger.jsonl"
    if ledger.exists():
        latest = {}
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("run_id") == run_root.name:
                    latest[row.get("request_id")] = row
        for row in latest.values():
            usage["requests"] += 1
            usage["input_tokens"] += int(row.get("input_tokens") or 0)
            usage["output_tokens"] += int(row.get("output_tokens") or 0)
            usage["cost_usd"] += float(row.get("calculated_cost_usd") or 0)
    elapsed = 0.0
    for path in (run_root / "requests").glob("*.json"):
        try:
            elapsed += float(json.loads(path.read_text(encoding="utf-8")).get("elapsed_seconds") or 0)
        except (ValueError, OSError):
            continue
    model = provider.get("model") or next((i.get("model") for i in payload["included"]), None)
    plan = json.loads((run_root / "run_plan.json").read_text(encoding="utf-8"))
    sample = ", sample" if plan.get("transcript_sample") else ""
    return dict(
        payload,
        set_id=run_root.name,
        set_kind="model_proposals",
        label=f"{model or 'Model'} ({run_root.name}{sample})",
        model=model,
        provider=provider.get("name"),
        usage=dict(usage, cost_usd=round(usage["cost_usd"], 6), elapsed_seconds=round(elapsed, 1) if elapsed else None),
    )


def reference_coding_set(reference: dict) -> dict:
    return dict(reference, set_id=reference["run_id"], set_kind="reference", label=reference["label"],
                model=None, provider=None, usage=None)


def _known(coding_set: dict) -> set[str]:
    return {code["id"] for code in coding_set["codebook"].get("codes", [])}


def present_units(coding_set: dict, projection: dict[str, str] | None = None) -> Counter:
    """(transcript, code) -> number of proposals applying that code, located or not."""
    known = _known(coding_set)
    counts: Counter = Counter()
    for item in coding_set["included"] + coding_set["excluded"]:
        code = item.get("code_id")
        if code in known:
            counts[(item["source"], projection[code] if projection else code)] += 1
    return counts


def _mean(values: list) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def _restrict(coding_set: dict, sources: set[str]) -> dict:
    trimmed = dict(coding_set, sources={k: v for k, v in coding_set["sources"].items() if k in sources})
    for key in ("included", "excluded", "absences"):
        trimmed[key] = [item for item in coding_set.get(key, []) if item.get("source") in sources]
    return trimmed


def common_sources(sets: list[dict]) -> list[str]:
    common = set(sets[0]["sources"].items())
    for coding_set in sets[1:]:
        common &= set(coding_set["sources"].items())
    return sorted(path for path, _ in common)


def coding_profile(coding_set: dict) -> dict:
    known = _known(coding_set)
    sources = sorted(coding_set["sources"])
    included = coding_set["included"]
    not_located = [i for i in coding_set["excluded"] if i.get("code_id") in known]
    unknown = [i for i in coding_set["excluded"] if i.get("code_id") not in known]
    anchoring = Counter(i.get("anchoring_method") for i in included)
    per_source = Counter(i["source"] for i in included + not_located)
    present = present_units(coding_set)
    spans = Counter((i["source"], i["start"], i["end"]) for i in included)
    words = [len(i.get("exact_text", "").split()) for i in included]
    proposals = len(included) + len(not_located)
    return dict(
        set_id=coding_set["set_id"], label=coding_set["label"], kind=coding_set["set_kind"],
        model=coding_set.get("model"), provider=coding_set.get("provider"),
        transcripts=len(sources),
        coded_passages=proposals,
        passages_located=len(included),
        located_exactly=anchoring.get("unique_exact_quote", 0),
        located_after_typography=anchoring.get("normalized_quote_candidate", 0),
        located_by_ellipsis_parts=anchoring.get("ellipsis_parts", 0),
        quotations_not_found=len(not_located),
        unknown_codes=len(unknown),
        no_evidence_rows=len(coding_set.get("absences", [])),
        share_located=len(included) / proposals if proposals else None,
        codes_present=len(present),
        codes_present_per_transcript=len(present) / len(sources) if sources else None,
        passages_per_transcript=proposals / len(sources) if sources else None,
        median_passage_words=median(words) if words else None,
        passages_coded_more_than_once=sum(1 for count in spans.values() if count > 1),
        **({} if not coding_set.get("usage") else {
            "requests": coding_set["usage"]["requests"], "input_tokens": coding_set["usage"]["input_tokens"],
            "output_tokens": coding_set["usage"]["output_tokens"], "cost_usd": coding_set["usage"]["cost_usd"],
            "elapsed_seconds": coding_set["usage"]["elapsed_seconds"]}),
        per_transcript_passages={source: per_source.get(source, 0) for source in sources},
    )


# ---------------------------------------------------------------- comparisons

def _presence_rows(left: dict, right: dict, sources: list[str], codes: list[dict], level: str,
                   projection: dict[str, str] | None, versus_reference: bool) -> list[dict]:
    universe_codes = sorted({projection[c["id"]] if projection else c["id"] for c in codes})
    domains = {c["id"]: _domain(c) for c in codes}
    a, b = present_units(left, projection), present_units(right, projection)
    scopes: dict[tuple[str, str], list[tuple[str, str]]] = {("all", "All"): []}
    for source in sources:
        for code in universe_codes:
            unit = (source, code)
            scopes[("all", "All")].append(unit)
            scopes.setdefault(("domain", domains.get(code, "All codes")), []).append(unit)
            scopes.setdefault(("transcript", source.rsplit("/", 1)[-1]), []).append(unit)
    rows = []
    for (scope_kind, scope), units in scopes.items():
        both = sum(1 for u in units if a[u] and b[u])
        left_only = sum(1 for u in units if a[u] and not b[u])
        right_only = sum(1 for u in units if b[u] and not a[u])
        neither = len(units) - both - left_only - right_only
        row = dict(level=level, scope_kind=scope_kind, scope=scope, left=left["set_id"], right=right["set_id"],
                   comparison="versus reference" if versus_reference else "between coding sets",
                   both=both, left_only=left_only, right_only=right_only, neither=neither,
                   **agreement_statistics(both, left_only, right_only, neither))
        row.update(reference_statistics(both, left_only, right_only) if versus_reference
                   else dict(precision=None, recall=None, f1=None))
        rows.append(row)
    return rows


def passage_agreement(left: dict, right: dict, *, versus_reference: bool) -> dict:
    def spans(coding_set: dict) -> list[_Span]:
        return [_Span(i["source"], i["code_id"], i["start"], i["end"], (i["record_id"],))
                for i in coding_set["included"]]

    a, b = spans(left), spans(right)
    row = dict(left=left["set_id"], right=right["set_id"],
               comparison="versus reference" if versus_reference else "between coding sets",
               left_passages=len(a), right_passages=len(b))
    for name, ratio in (("exact", _EXACT), ("iou_half", _IOU_HALF), ("any_overlap", _ANY_OVERLAP)):
        matched = len(_maximum_matching(a, b, ratio))
        row[f"matched_{name}"] = matched
        row[f"f1_{name}"] = 2 * matched / (len(a) + len(b)) if a or b else None
    groups: dict[tuple[str, str], tuple[list, list]] = {}
    for item in left["included"]:
        groups.setdefault((item["source"], item["code_id"]), ([], []))[0].append(item)
    for item in right["included"]:
        groups.setdefault((item["source"], item["code_id"]), ([], []))[1].append(item)
    shared = union = left_chars = right_chars = 0
    for left_items, right_items in groups.values():
        common, total = interval_overlap(left_items, right_items)
        shared += common
        union += total
        left_chars += interval_overlap(left_items, [])[1]
        right_chars += interval_overlap([], right_items)[1]
    row.update(
        coded_text_jaccard=shared / union if union else None,
        left_text_also_coded_by_right=shared / left_chars if left_chars else None,
        right_text_also_coded_by_left=shared / right_chars if right_chars else None,
    )
    return row


def build_qualbench(coding_sets: list[dict], *, reference: dict | None = None,
                    stability_groups: list[list[str]] | None = None) -> dict:
    """Compare every pair of coding sets, and each with the reference, on the transcripts all share."""
    everything = coding_sets + ([reference] if reference else [])
    if len(everything) < 2:
        raise ValueError("Choose at least two coding sets, or one with a reference.")
    ids = [s["set_id"] for s in everything]
    if len(set(ids)) != len(ids):
        raise ValueError("Choose each coding set once.")
    code_ids = [_known(s) for s in everything]
    if any(ids_ != code_ids[0] for ids_ in code_ids[1:]):
        raise ValueError("All coding sets must use the same codebook.")
    sources = common_sources(everything)
    if not sources:
        raise ValueError("These coding sets have no transcripts in common.")
    omitted = sorted({path for s in everything for path in s["sources"]} - set(sources))
    everything = [_restrict(s, set(sources)) for s in everything]
    coding_sets, reference = (everything[:-1], everything[-1]) if reference else (everything, None)
    codes = everything[0]["codebook"]["codes"]
    projection = parent_projection(everything[0]["codebook"])
    merged_levels = any(projection[c] != c for c in projection)
    presence, passages = [], []
    pairs = [(left, right, False) for left, right in combinations(coding_sets, 2)]
    pairs += [(coding_set, reference, True) for coding_set in coding_sets] if reference else []
    for left, right, versus in pairs:
        presence += _presence_rows(left, right, sources, codes, "code", None, versus)
        if merged_levels:
            presence += _presence_rows(left, right, sources, codes, "parent code", projection, versus)
        passages.append(passage_agreement(left, right, versus_reference=versus))
    stability = []
    by_id = {s["set_id"]: s for s in everything}
    for group in stability_groups or []:
        members = [by_id[g] for g in group if g in by_id]
        if len(members) < 2:
            continue
        for level, proj in (("code", None), ("parent code", projection)) if merged_levels else (("code", None),):
            counts = [present_units(m, proj) for m in members]
            universe = sorted({(s, proj[c["id"]] if proj else c["id"]) for s in sources for c in codes})
            values = [[1 if count[u] else 0 for count in counts] for u in universe]
            pairwise = [r for r in presence if r["level"] == level and r["scope_kind"] == "all"
                        and {r["left"], r["right"]} <= set(group) and r["comparison"] == "between coding sets"]
            stability.append(dict(
                group=" + ".join(m["set_id"] for m in members), coding_sets=len(members), level=level,
                n_units=len(universe), krippendorff_alpha=krippendorff_alpha_nominal(values),
                units_all_agree=sum(1 for v in values if len(set(v)) == 1) / len(values) if values else None,
                mean_pairwise_kappa=_mean([r["cohen_kappa"] for r in pairwise]),
            ))
    units = []
    for coding_set in everything:
        counts = present_units(coding_set)
        for source in sources:
            for code in codes:
                units.append(dict(coding_set=coding_set["set_id"], transcript=source.rsplit("/", 1)[-1],
                                  domain=_domain(code), code_id=code["id"], code=code.get("label", code["id"]),
                                  parent_code_id=projection[code["id"]], present=1 if counts[(source, code["id"])] else 0,
                                  proposals=counts[(source, code["id"])]))
    return dict(
        kind=KIND,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        coding_sets=[coding_profile(s) for s in everything],
        reference=dict(set_id=reference["set_id"], label=reference["label"],
                       statement=reference.get("statement"),
                       independent_human_coding=bool(reference.get("independent_human_coding")))
        if reference else None,
        transcripts=sources,
        transcripts_left_out=omitted,
        codes=len(codes),
        presence=presence,
        passages=passages,
        stability=stability,
        units=units,
    )


# ---------------------------------------------------------------- output

def _csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    columns = list(rows[0])
    for row in rows[1:]:
        columns += [key for key in row if key not in columns]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else round(v, 6) if isinstance(v, float) else v) for k, v in row.items()})
    return buffer.getvalue()


README = """# QualBench report

Created {created}. {sets} coding sets on {transcripts} transcript(s) and {codes} codes.
{reference}

Files (tidy tables, one row per observation):
- `coding_sets.csv`: one row per coding set. Volume, quotation fidelity, cost and time.
- `presence.csv`: agreement on whether each code was applied to each transcript, for every pair
  of coding sets and for each set against the reference. Scopes: all units, each domain, each
  transcript. Levels: codes as coded, and sub-codes merged into their parent code.
- `passages.csv`: agreement on the coded passages themselves.
- `stability.csv`: agreement among repeat runs (Krippendorff's alpha).
- `units.csv`: the presence data itself (coding set × transcript × code), for your own analysis.
- `report.json`: everything above.

Definitions
- A unit is one transcript and one code. A code is present when the coding set applied it at least
  once, whether or not the quotation was found in the transcript.
- Percent agreement: share of units where both sets agree (present or absent).
- Cohen's kappa: agreement corrected for chance using each set's own rate of applying codes.
  Low when codes are rarely applied, even if agreement is high.
- Gwet's AC1: chance-corrected agreement that stays stable when most codes are absent.
- PABAK: prevalence- and bias-adjusted kappa, 2 × percent agreement − 1.
- Jaccard: units both sets marked present, out of units either set marked present.
- Precision, recall, F1 (against a reference only): precision is the share of the set's present
  units that the reference also has; recall is the share of the reference's present units that the
  set also has; F1 is their harmonic mean.
- Passage F1: passages for the same code in the same transcript matched one to one: exactly
  (same start and end), at an overlap of at least half their combined extent (IoU ≥ 0.5), or with
  any overlap. F1 = 2 × matched / (passages in left + passages in right).
- Coded-text Jaccard: characters both sets coded with the same code, out of characters either did.
- Krippendorff's alpha (nominal): agreement among several coding sets on the same units, corrected
  for chance. 1 is perfect agreement; 0 is agreement at chance.

Interpretation
- A reference is not treated as correct coding. {statement}
- Comparisons use the model's original proposals, before any review.
"""


def write_qualbench(report: dict, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    profiles = [{k: v for k, v in row.items() if k != "per_transcript_passages"} for row in report["coding_sets"]]
    for name, rows in (("coding_sets", profiles), ("presence", report["presence"]),
                       ("passages", report["passages"]), ("stability", report["stability"]),
                       ("units", report["units"])):
        (folder / f"{name}.csv").write_text(_csv(rows), encoding="utf-8")
    reference = report["reference"]
    (folder / "README.md").write_text(README.format(
        created=report["created_at_utc"][:16].replace("T", " ") + " UTC",
        sets=len(report["coding_sets"]), transcripts=len(report["transcripts"]), codes=report["codes"],
        reference=f"Reference: {reference['label']}." if reference else "No reference coding.",
        statement=(reference["statement"] if reference else ""),
    ), encoding="utf-8")
    return folder
