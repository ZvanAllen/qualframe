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
# Passage matching thresholds as ratios (shared / combined extent), to avoid rounding at the boundary.
MATCH_THRESHOLDS = (("exact", (1, 1)), ("iou_quarter", (1, 4)), ("iou_half", (1, 2)),
                    ("iou_three_quarters", (3, 4)), ("any_overlap", (1, 10**12)))


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


def _latest_request_rows(path: Path, run_id: str, project_id: str | None) -> dict[str, dict]:
    """Reconciliation appends a replacement for the same request; count it once."""
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("run_id") == run_id and row.get("project_id", project_id) == project_id:
                latest[str(row["request_id"])] = row
    return latest


_TOKEN_TOTALS = ("input_tokens", "output_tokens", "cached_input_tokens",
                 "cache_write_tokens", "reasoning_tokens")
_USAGE_TOTALS = ("requests", *_TOKEN_TOTALS, "cost_usd", "elapsed_seconds")


def _usage_totals(records: list[dict], *, ledger_available: bool = True,
                  stage_attribution_known: bool = True) -> dict:
    notes = []
    complete = ledger_available and all(row.get("usage_recorded") for row in records)
    if not ledger_available:
        notes.append("Cost ledger is missing; cost and token totals are unknown.")
    elif not complete:
        missing = sum(not row.get("usage_recorded") for row in records)
        notes.append(f"Usage is not recorded for {missing} request(s); cost and token totals are unknown.")
    tokens = {
        key: sum(int(row[key]) for row in records)
        if complete and all(row.get(key) is not None for row in records) else None
        for key in _TOKEN_TOTALS
    }
    if complete and any(tokens[key] is None for key in _TOKEN_TOTALS):
        notes.append("Some token categories were not recorded for every request; those totals are unknown.")
    elapsed = [float(row["elapsed_seconds"]) for row in records if row.get("elapsed_seconds") is not None]
    totals = dict(
        requests=len(records), **tokens,
        cost_usd=round(sum(float(row["calculated_cost_usd"]) for row in records), 6)
        if complete and all(row.get("calculated_cost_usd") is not None for row in records) else None,
        elapsed_seconds=round(sum(elapsed), 1) if elapsed else None,
        cost_is_estimated=any(row.get("cost_is_estimated", False) for row in records)
        if ledger_available else None,
    )
    if not stage_attribution_known:
        notes.append("Some requests lack coding-stage attribution; compared-cohort totals are unknown.")
        totals = {key: None for key in totals}
    return dict(totals, usage_note=" ".join(notes) or None)


def _cost_ledger_path(repo_root: Path, run_root: Path, settings: dict) -> Path:
    manifest_path = run_root / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    recorded = settings.get("cost_ledger_path") or manifest.get("cost_ledger_path")
    if not recorded:
        return run_root.parents[1] / "logs/cost_ledger.jsonl"
    # Recorded relative paths are workspace-relative, including after moving a workspace.
    path = Path(str(recorded).replace("\\", "/"))
    return path if path.is_absolute() else repo_root / path


def _run_usage(run_root: Path, payload: dict, plan: dict, ledger: Path) -> list[dict]:
    latest = _latest_request_rows(ledger, run_root.name, payload.get("project_id"))
    reservations = _latest_request_rows(
        ledger.with_name("request_reservations.jsonl"), run_root.name, payload.get("project_id"))
    attempts: dict[str, dict] = {}
    for path in sorted((run_root / "requests").glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            attempts[str(row.get("request_id") or path.stem)] = row
        except (ValueError, OSError):
            continue
    # Match the first transcript-associated stage used by raw_coding_payload.
    stage_by_source: dict[str, str] = {}
    for call in plan.get("planned_stage_runs", []):
        source = call.get("input_path", "").replace("\\", "/")
        if source in payload["sources"]:
            stage_by_source.setdefault(source, call["stage_id"])
    records = []
    for request_id in sorted(latest.keys() | attempts.keys()):
        row = dict(reservations.get(request_id, {}), **latest.get(request_id, {}))
        row.update(attempts.get(request_id, {}))
        source = str(row.get("input_label") or "").split("::", 1)[0].replace("\\", "/")
        stage = row.get("stage_id")
        row["source"] = source if (
            source in stage_by_source and (stage is None or stage == stage_by_source[source])
        ) else None
        row["coding_stage_known"] = stage is not None
        row["usage_recorded"] = request_id in latest
        records.append(row)
    return records


def run_coding_set(repo_root: Path, run_root: Path) -> dict:
    """A run's original model proposals, with whole-run and source-attributed usage."""
    payload = raw_coding_payload(repo_root, run_root)
    settings_path = run_root / "run_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    provider = settings.get("provider") or {}
    plan = json.loads((run_root / "run_plan.json").read_text(encoding="utf-8"))
    ledger = _cost_ledger_path(repo_root, run_root, settings)
    usage_records = _run_usage(run_root, payload, plan, ledger)
    model = provider.get("model") or next((i.get("model") for i in payload["included"]), None)
    sample = ", sample" if plan.get("transcript_sample") else ""
    return dict(
        payload,
        set_id=run_root.name,
        set_kind="model_proposals",
        label=f"{model or 'Model'} ({run_root.name}{sample})",
        model=model,
        provider=provider.get("name"),
        usage=_usage_totals(usage_records, ledger_available=ledger.is_file()),
        usage_records=usage_records,
        usage_ledger_available=ledger.is_file(),
        usage_ledger_path=str(ledger),
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
    for item in coding_set["included"] + coding_set["excluded"] + coding_set.get("presence_only", []):
        code = item.get("code_id")
        if code in known:
            counts[(item["source"], projection[code] if projection else code)] += 1
    return counts


def _mean(values: list) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def _restrict(coding_set: dict, sources: set[str]) -> dict:
    trimmed = dict(coding_set, sources={k: v for k, v in coding_set["sources"].items() if k in sources})
    for key in ("included", "excluded", "absences", "presence_only", "usage_records"):
        trimmed[key] = [item for item in coding_set.get(key, []) if item.get("source") in sources]
    return trimmed


def same_transcripts_by_content(sets: list[dict]) -> list[dict]:
    """Key every coding set's transcripts by the first set's path for the same transcript.

    Runs from different studies (for example the same transcripts coded with different
    instructions in a second study) store the transcripts under different paths. A transcript at
    the same path with the same SHA-256 hash is the same; otherwise a file with the same hash is
    paired one to one with the first set's files, preferring the same file name, so two identical
    files within a study stay two transcripts.
    """
    base = sets[0]["sources"]
    by_digest: dict[str, list[str]] = {}
    for path, digest in sorted(base.items()):
        by_digest.setdefault(digest, []).append(path)
    rekeyed = [sets[0]]
    for coding_set in sets[1:]:
        free = {digest: list(paths) for digest, paths in by_digest.items()}
        mapping: dict[str, str] = {}
        for path, digest in coding_set["sources"].items():
            if base.get(path) == digest:
                mapping[path] = path
                free[digest].remove(path)
        for path, digest in sorted(coding_set["sources"].items()):
            if path in mapping:
                continue
            options = free.get(digest, [])
            same_name = [p for p in options if p.rsplit("/", 1)[-1] == path.rsplit("/", 1)[-1]]
            chosen = (same_name or options or [path])[0]
            if chosen in options:
                options.remove(chosen)
            mapping[path] = chosen
        if all(old == new for old, new in mapping.items()):
            rekeyed.append(coding_set)
            continue
        moved = dict(coding_set, sources={mapping[path]: digest for path, digest in coding_set["sources"].items()})
        for key in ("included", "excluded", "absences", "presence_only", "usage_records"):
            moved[key] = [dict(item, source=mapping.get(item.get("source"), item.get("source")))
                          for item in coding_set.get(key, [])]
        rekeyed.append(moved)
    return rekeyed


def common_sources(sets: list[dict]) -> list[str]:
    common = set(sets[0]["sources"].items())
    for coding_set in sets[1:]:
        common &= set(coding_set["sources"].items())
    return sorted(path for path, _ in common)


def _usage_profile(coding_set: dict) -> dict:
    if not coding_set.get("usage"):
        return {}
    whole_run = coding_set["usage"]
    records = [row for row in coding_set.get("usage_records", []) if row.get("source") in coding_set["sources"]]
    cohort = _usage_totals(
        records, ledger_available=coding_set.get("usage_ledger_available", False),
        stage_attribution_known=all(row.get("coding_stage_known") for row in records))
    count = len(coding_set["sources"])
    return {
        **cohort,  # Existing consumers display the compared cohort.
        "usage_ledger_path": coding_set.get("usage_ledger_path"),
        **{f"cohort_{key}": value for key, value in cohort.items()},
        **{f"whole_run_{key}": value for key, value in whole_run.items()},
        **{f"cohort_{key}_per_transcript": value / count if count and value is not None else None
           for key, value in cohort.items() if key in _USAGE_TOTALS},
    }


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
        codes_without_quotation=len(coding_set.get("presence_only", [])),
        share_located=len(included) / proposals if proposals else None,
        codes_present=len(present),
        codes_present_per_transcript=len(present) / len(sources) if sources else None,
        passages_per_transcript=proposals / len(sources) if sources else None,
        median_passage_words=median(words) if words else None,
        passages_coded_more_than_once=sum(1 for count in spans.values() if count > 1),
        **_usage_profile(coding_set),
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
    per_transcript = [r for r in rows if r["scope_kind"] == "transcript"]
    if len(per_transcript) > 1:
        # Each transcript weighted equally: the mean of the per-transcript figures.
        macro = dict(per_transcript[0], scope_kind="transcript mean", scope="Mean of transcripts",
                     n_units=sum(r["n_units"] for r in per_transcript))
        for key in ("both", "left_only", "right_only", "neither"):
            macro[key] = None
        for key in ("percent_agreement", "cohen_kappa", "gwet_ac1", "pabak", "jaccard", "precision", "recall", "f1"):
            macro[key] = _mean([r[key] for r in per_transcript])
        rows.append(macro)
    return rows


def passage_agreement(left: dict, right: dict, *, versus_reference: bool, source: str | None = None) -> dict:
    """Passage agreement over all transcripts, or within one transcript."""
    def located(coding_set: dict) -> list[dict]:
        return [i for i in coding_set["included"] if source is None or i["source"] == source]

    left_items, right_items = located(left), located(right)
    a = [_Span(i["source"], i["code_id"], i["start"], i["end"], (i["record_id"],)) for i in left_items]
    b = [_Span(i["source"], i["code_id"], i["start"], i["end"], (i["record_id"],)) for i in right_items]
    row = dict(scope_kind="all" if source is None else "transcript",
               scope="All" if source is None else source.rsplit("/", 1)[-1],
               left=left["set_id"], right=right["set_id"],
               comparison="versus reference" if versus_reference else "between coding sets",
               left_passages=len(a), right_passages=len(b))
    for name, ratio in MATCH_THRESHOLDS:
        matched = len(_maximum_matching(a, b, ratio))
        row[f"matched_{name}"] = matched
        row[f"f1_{name}"] = 2 * matched / (len(a) + len(b)) if a or b else None
    groups: dict[tuple[str, str], tuple[list, list]] = {}
    for item in left_items:
        groups.setdefault((item["source"], item["code_id"]), ([], []))[0].append(item)
    for item in right_items:
        groups.setdefault((item["source"], item["code_id"]), ([], []))[1].append(item)
    shared = union = left_chars = right_chars = 0
    for in_left, in_right in groups.values():
        common, total = interval_overlap(in_left, in_right)
        shared += common
        union += total
        left_chars += interval_overlap(in_left, [])[1]
        right_chars += interval_overlap([], in_right)[1]
    row.update(
        coded_text_jaccard=shared / union if union else None,
        left_text_also_coded_by_right=shared / left_chars if left_chars else None,
        right_text_also_coded_by_left=shared / right_chars if right_chars else None,
    )
    return row


def _codebook_differences(sets: list[dict]) -> list[dict]:
    """Name changed code content without treating display-only section labels as meaning."""
    first = sets[0]
    baseline = {code["id"]: code for code in first["codebook"]["codes"]}
    differences = []
    for other in sets[1:]:
        for code in other["codebook"]["codes"]:
            original = baseline[code["id"]]
            fields = sorted(key for key in original.keys() | code.keys()
                            if key != "section" and original.get(key) != code.get(key))
            if fields:
                differences.append(dict(left=first["set_id"], right=other["set_id"],
                                        code_id=code["id"], fields=fields))
    return differences


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
    differences = _codebook_differences(everything)
    warnings = [f"Code {item['code_id']} differs between {item['left']} and {item['right']}: "
                + ", ".join(item["fields"]) + "." for item in differences]
    if differences:
        warnings.append("Comparisons continue by code ID. Labels, domains and parent projections use the first coding set's codebook; interpret differences before reporting agreement.")
    everything = same_transcripts_by_content(everything)
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
        if len(sources) > 1:
            passages += [passage_agreement(left, right, versus_reference=versus, source=source) for source in sources]
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
        warnings=warnings, codebook_differences=differences,
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

Resource accounting uses the ledger path saved in run settings, then the manifest, then the conventional study logs path. Missing ledgers or missing request usage produce unknown (null) cost/token totals, not zero. Profiles include accounting notes, estimated-cost flags and cached/write-cache/reasoning token totals when recorded. Legacy records without a token category leave it unknown.

Files (tidy tables, one row per observation):
- `coding_sets.csv`: one row per coding set. Volume, quotation fidelity, compared-cohort request/token/cost/time totals and per-transcript means, plus explicitly labelled whole-run totals. Cohort usage follows each request source and the first transcript coding stage; later synthesis stages count only in whole-run totals. Time is summed provider-request duration, not study wall time.
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
  (same start and end), with shared text at least a quarter, half or three quarters of their
  combined extent (IoU ≥ 0.25, 0.5, 0.75), or with any overlap.
  F1 = 2 × matched / (passages in left + passages in right).
- Scopes: "all" pools every unit or passage; "transcript" rows give each transcript separately;
  "transcript mean" weights each transcript equally (the mean of the transcript rows).
- Coded-text Jaccard: characters both sets coded with the same code, out of characters either did.
- Krippendorff's alpha (nominal): agreement among several coding sets on the same units, corrected
  for chance. 1 is perfect agreement; 0 is agreement at chance.

Interpretation
{warnings}
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
        warnings="\n".join("- Warning: " + note for note in report.get("warnings", [])),
    ), encoding="utf-8")
    return folder
