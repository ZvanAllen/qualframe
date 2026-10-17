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

from qualframe.benchmark_metrics import _maximum_matching_indices
from qualframe import __version__
from qualframe.code_provenance import get_code_provenance
from qualframe.qualbench_references import reference_differences
from qualframe.run_comparison import interval_overlap, raw_coding_payload
from qualframe.qualbench_presence import (
    REASONS, accuracy_statistics, assessment_masks, bootstrap_intervals, exclusion_counts,
    load_document_exclusions, load_unit_exclusions,
)

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


def reference_statistics(both: int, left_only: int, right_only: int, neither: int | None = None) -> dict:
    """The left coding set judged against a reference on the right."""
    return dict(
        **(accuracy_statistics(both, left_only, right_only, neither) if neither is not None else {}),
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


def _active_codes(codebook: dict) -> list[dict]:
    """Missing flags in older codebooks retain the original all-active meaning."""
    return [code for code in codebook.get("codes", []) if code.get("active", True)]


def present_units(coding_set: dict, projection: dict[str, str] | None = None,
                  active_code_ids: set[str] | None = None) -> Counter:
    """Count active-code proposals, optionally merged through inactive parent entries."""
    known = ({code["id"] for code in _active_codes(coding_set["codebook"])}
             if active_code_ids is None else active_code_ids)
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
    for key in ("included", "excluded", "absences", "no_decisions", "presence_only", "usage_records"):
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
        for key in ("included", "excluded", "absences", "no_decisions", "presence_only", "usage_records"):
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
    unique = [i for i in included if not i.get("alternative_spans")]
    repeated = len(included) - len(unique)
    anchoring = Counter(i.get("anchoring_method") for i in unique)
    per_source = Counter(i["source"] for i in included + not_located)
    present = present_units(coding_set)
    spans = Counter((i["source"], i["start"], i["end"]) for i in unique)
    words = [len(i.get("exact_text", "").split()) for i in unique]
    proposals = len(included) + len(not_located)
    return dict(
        set_id=coding_set["set_id"], label=coding_set["label"], kind=coding_set["set_kind"],
        model=coding_set.get("model"), provider=coding_set.get("provider"),
        transcripts=len(sources),
        active_codes=len(_active_codes(coding_set["codebook"])),
        inactive_codes=len(known) - len(_active_codes(coding_set["codebook"])),
        coded_passages=proposals,
        passages_located=len(included),
        passages_uniquely_located=len(unique),
        passages_with_alternative_locations=repeated,
        coded_text_passages_excluded=repeated,
        **(dict(reference_passages_unique=len(unique), reference_passages_repeated=repeated,
                reference_passages_unanchored=len(not_located),
                reference_candidates_requiring_confirmation=sum(i.get("anchoring_method") in
                    {"normalized_quote_candidate", "normalized_words_candidate"} for i in unique))
           if coding_set["set_kind"] == "reference" else {}),
        located_exactly=anchoring.get("unique_exact_quote", 0),
        located_after_typography=anchoring.get("normalized_quote_candidate", 0),
        located_after_word_normalization=anchoring.get("normalized_words_candidate", 0),
        located_by_ellipsis_parts=anchoring.get("ellipsis_parts", 0),
        quotations_not_found=len(not_located),
        unknown_codes=len(unknown),
        no_evidence_rows=len(coding_set.get("absences", [])),
        no_decision_count=len(coding_set.get("no_decisions", [])),
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

def _transcript_labels(sources: list[str]) -> dict[str, str]:
    """Use relative paths wherever a basename would identify more than one source."""
    names = {source: source.replace("\\", "/").rsplit("/", 1)[-1] for source in sources}
    counts = Counter(names.values())
    return {source: source if counts[name] > 1 else name for source, name in names.items()}


def _presence_counts(coding_set: dict, active_ids: set[str], projection: dict | None,
                     child_mask: dict) -> Counter:
    counts = Counter()
    for (source, code), value in present_units(coding_set, active_code_ids=active_ids).items():
        if (source, code) not in child_mask:
            counts[(source, projection[code] if projection else code)] += value
    return counts


def _presence_rows(left: dict, right: dict, sources: list[str], codes: list[dict], level: str,
                   projection: dict[str, str] | None, versus_reference: bool,
                   mask: dict | None = None, child_mask: dict | None = None,
                   bootstrap_data: dict | None = None) -> list[dict]:
    mask, child_mask = mask or {}, child_mask or {}
    labels = _transcript_labels(sources)
    universe_codes = sorted({projection[c["id"]] if projection else c["id"]
                             for c in codes if c.get("active", True)})
    domains = {c["id"]: _domain(c) for c in codes}
    active_ids = {c["id"] for c in codes if c.get("active", True)}
    a = _presence_counts(left, active_ids, projection, child_mask)
    b = _presence_counts(right, active_ids, projection, child_mask)
    scopes: dict[tuple[str, str], list[tuple[str, str]]] = {("all", "All"): []}
    for source in sources:
        for code in universe_codes:
            unit = (source, code)
            scopes[("all", "All")].append(unit)
            scopes.setdefault(("domain", domains.get(code, "All codes")), []).append(unit)
            scopes.setdefault(("transcript", labels[source]), []).append(unit)
    rows = []
    for (scope_kind, scope), universe in scopes.items():
        units = [u for u in universe if u not in mask]
        both = sum(1 for u in units if a[u] and b[u])
        left_only = sum(1 for u in units if a[u] and not b[u])
        right_only = sum(1 for u in units if b[u] and not a[u])
        neither = len(units) - both - left_only - right_only
        row = dict(level=level, scope_kind=scope_kind, scope=scope, left=left["set_id"], right=right["set_id"],
                   comparison="versus reference" if versus_reference else "between coding sets",
                   baseline=left.get("baseline"), n_codes=len({code for _, code in universe}),
                   both=both, left_only=left_only, right_only=right_only, neither=neither,
                   **exclusion_counts(universe, mask),
                   **agreement_statistics(both, left_only, right_only, neither))
        row.update(reference_statistics(both, left_only, right_only, neither) if versus_reference
                   else dict(precision=None, recall=None, f1=None, sensitivity=None, specificity=None,
                             balanced_accuracy=None, mcc=None))
        rows.append(row)
        if bootstrap_data is not None and versus_reference:
            per_document = {source: [0, 0, 0, 0] for source in sources
                            if scope_kind != "transcript" or labels[source] == scope}
            for unit in units:
                category = 0 if a[unit] and b[unit] else 1 if a[unit] else 2 if b[unit] else 3
                per_document[unit[0]][category] += 1
            bootstrap_data[(left["set_id"], level, scope_kind, scope)] = per_document
    per_transcript = [r for r in rows if r["scope_kind"] == "transcript"]
    if len(per_transcript) > 1:
        macro = dict(per_transcript[0], scope_kind="transcript mean", scope="Mean of transcripts",
                     n_units=sum(r["n_units"] for r in per_transcript))
        for key in ("both", "left_only", "right_only", "neither"):
            macro[key] = None
        for key in ("n_units_before_exclusions", "excluded_units", *REASONS):
            macro[key] = sum(r[key] for r in per_transcript)
        for key in ("percent_agreement", "cohen_kappa", "gwet_ac1", "pabak", "jaccard", "precision", "recall", "f1",
                    "sensitivity", "specificity", "balanced_accuracy", "mcc"):
            macro[key] = _mean([r[key] for r in per_transcript])
        rows.append(macro)
        if bootstrap_data is not None and versus_reference:
            bootstrap_data[(left["set_id"], level, "transcript mean", "Mean of transcripts")] = dict(
                bootstrap_data[(left["set_id"], level, "all", "All")])
    return rows


def _code_rows(coding_set: dict, reference: dict, sources: list[str], codes: list[dict], mask: dict) -> list[dict]:
    active_ids = {code["id"] for code in codes}
    a, b = present_units(coding_set, active_code_ids=active_ids), present_units(reference, active_code_ids=active_ids)
    rows = []
    for code in codes:
        universe = [(source, code["id"]) for source in sources]
        units = [u for u in universe if u not in mask]
        tp = sum(bool(a[u]) and bool(b[u]) for u in units)
        fp = sum(bool(a[u]) and not b[u] for u in units)
        fn = sum(not a[u] and bool(b[u]) for u in units)
        tn = len(units) - tp - fp - fn
        rows.append(dict(coding_set=coding_set["set_id"], reference=reference["set_id"],
                         code_id=code["id"], code=code.get("label", code["id"]), domain=_domain(code),
                         n_units=len(units), reference_prevalence=(tp + fn) / len(units) if units else None,
                         set_prevalence=(tp + fp) / len(units) if units else None,
                         true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn,
                         **exclusion_counts(universe, mask), **reference_statistics(tp, fp, fn, tn)))
    return rows


def _passage_threshold(left: dict, right: dict, numerator: int, denominator: int) -> bool:
    intersection = max(0, min(left["end"], right["end"]) - max(left["start"], right["start"]))
    union = left["end"] - left["start"] + right["end"] - right["start"] - intersection
    return intersection > 0 and intersection * denominator >= union * numerator


def passage_agreement(left: dict, right: dict, *, versus_reference: bool, source: str | None = None,
                      scope: str = "all pairs") -> dict:
    """Compare located passages across all pairs or pairs located on both sides."""
    if scope not in ("all pairs", "shared positives"):
        raise ValueError("Passage scope must be 'all pairs' or 'shared positives'.")

    def located(coding_set: dict) -> list[dict]:
        return [i for i in coding_set["included"] if source is None or i["source"] == source]

    left_items, right_items = located(left), located(right)
    shared_pairs = ({(i["source"], i["code_id"]) for i in left_items}
                    & {(i["source"], i["code_id"]) for i in right_items})
    if scope == "shared positives":
        left_items = [i for i in left_items if (i["source"], i["code_id"]) in shared_pairs]
        right_items = [i for i in right_items if (i["source"], i["code_id"]) in shared_pairs]
    # One graph vertex per annotation, regardless of how many locations it could have.
    a = [i.get("alternative_spans") or [i] for i in left_items]
    b = [i.get("alternative_spans") or [i] for i in right_items]
    labels = _transcript_labels(sorted(set(left["sources"]) | set(right["sources"])))
    row = dict(scope_kind="all" if source is None else "transcript",
               scope=scope, transcript="All" if source is None else labels[source],
               left=left["set_id"], right=right["set_id"],
               comparison="versus reference" if versus_reference else "between coding sets",
               shared_positive_pairs=len(shared_pairs),
               left_passages=len(a), right_passages=len(b))
    for name, ratio in MATCH_THRESHOLDS:
        numerator, denominator = ratio
        adjacent = []
        for item, alternatives in zip(left_items, a):
            edges = []
            for index, (other, candidates) in enumerate(zip(right_items, b)):
                if item["source"] != other["source"] or item["code_id"] != other["code_id"]:
                    continue
                if any(_passage_threshold(span, candidate, numerator, denominator)
                       for span in alternatives for candidate in candidates):
                    edges.append(index)
            adjacent.append(edges)
        matched = len(_maximum_matching_indices(adjacent))
        row[f"matched_{name}"] = matched
        row[f"f1_{name}"] = 2 * matched / (len(a) + len(b)) if a or b else None
    groups: dict[tuple[str, str], tuple[list, list]] = {}
    for item in left_items:
        if item.get("alternative_spans"):
            continue
        groups.setdefault((item["source"], item["code_id"]), ([], []))[0].append(item)
    for item in right_items:
        if item.get("alternative_spans"):
            continue
        groups.setdefault((item["source"], item["code_id"]), ([], []))[1].append(item)
    shared = union = left_chars = right_chars = 0
    for in_left, in_right in groups.values():
        common, total = interval_overlap(in_left, in_right)
        shared += common
        union += total
        left_chars += interval_overlap(in_left, [])[1]
        right_chars += interval_overlap([], in_right)[1]
    left_excluded = sum(bool(i.get("alternative_spans")) for i in left_items)
    right_excluded = sum(bool(i.get("alternative_spans")) for i in right_items)
    row.update(
        left_coded_text_passages_excluded=left_excluded,
        right_coded_text_passages_excluded=right_excluded,
        coded_text_passages_excluded=left_excluded + right_excluded,
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
                            if key != "section" and
                            original.get(key, True if key == "active" else None) !=
                            code.get(key, True if key == "active" else None))
            if fields:
                differences.append(dict(left=first["set_id"], right=other["set_id"],
                                        code_id=code["id"], fields=fields))
    return differences


def build_qualbench(coding_sets: list[dict], *, reference: dict | None = None,
                    second_reference: dict | None = None,
                    stability_groups: list[list[str]] | None = None,
                    exclude_units: Path | None = None, exclude_documents: Path | None = None,
                    bootstrap: int = 0, seed: int = 0, cluster_by_folder: bool = False) -> dict:
    """Compare every pair of coding sets, and each with the reference, on the transcripts all share."""
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or bootstrap < 0:
        raise ValueError("Bootstrap replicates must be a nonnegative integer.")
    if bootstrap and reference is None:
        raise ValueError("Bootstrap comparisons require a reference coding.")
    if cluster_by_folder and not bootstrap:
        raise ValueError("Cluster resampling requires --bootstrap with a positive replicate count.")
    if second_reference is not None and reference is None:
        raise ValueError("A second reference requires the first --reference.")
    if not coding_sets:
        raise ValueError("Choose at least one coding set.")
    coding_set_count = len(coding_sets)
    explicit_absences = bool(reference and reference.get("absences"))
    second_explicit_absences = bool(second_reference and second_reference.get("absences"))
    everything = coding_sets + ([reference] if reference else []) + ([second_reference] if second_reference else [])
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
        warnings.append("Comparisons continue by code ID. Labels, domains, active-code universe and parent projections use the first coding set's codebook; interpret differences before reporting agreement.")
    everything = same_transcripts_by_content(everything)
    sources = common_sources(everything)
    if not sources:
        raise ValueError("These coding sets have no transcripts in common.")
    omitted = sorted({path for s in everything for path in s["sources"]} - set(sources))
    all_sources = sorted({path for s in everything for path in s["sources"]})
    document_exclusions = load_document_exclusions(exclude_documents, all_sources)
    manual = load_unit_exclusions(exclude_units, all_sources, _active_codes(everything[0]["codebook"]), _domain)
    sources = [source for source in sources if source not in document_exclusions]
    if not sources:
        raise ValueError("No common transcripts remain after document exclusions.")
    requested_manual = manual
    manual = {unit: reasons for unit, reasons in manual.items() if unit[0] in sources}
    everything = [_restrict(s, set(sources)) for s in everything]
    coding_sets = everything[:coding_set_count]
    reference = everything[coding_set_count] if reference is not None else None
    second_reference = everything[coding_set_count + 1] if second_reference is not None else None
    # Existing tables retain the first reference's assessment policy. The new paired
    # table below alone intersects the two assessment masks.
    everything = coding_sets + ([reference] if reference else [])
    codebook = everything[0]["codebook"]
    codes = _active_codes(codebook)
    active_ids = {c["id"] for c in codes}
    projection = parent_projection(codebook)
    merged_levels = any(projection[c["id"]] != c["id"] for c in codes)
    code_universes = {"code": len(codes)}
    if merged_levels:
        code_universes["parent code"] = len({projection[c["id"]] for c in codes})
    reference_present = set(present_units(reference, active_code_ids=active_ids)) if reference else set()
    reference_absent = {(i["source"], i.get("code_id")) for i in reference.get("absences", [])} if reference else set()
    code_mask, parent_mask = assessment_masks(sources, active_ids, reference_present, reference_absent,
                                               explicit_absences, manual, projection)
    levels = [("code", None, code_mask)] + ([("parent code", projection, parent_mask)] if merged_levels else [])
    presence, passages, bootstrap_data = [], [], {}
    codes_table = []
    pairs = [(left, right, False) for left, right in combinations(coding_sets, 2)]
    pairs += [(coding_set, reference, True) for coding_set in coding_sets] if reference else []
    for left, right, versus in pairs:
        for level, proj, mask in levels:
            presence += _presence_rows(left, right, sources, codebook["codes"], level, proj, versus,
                                       mask, code_mask, bootstrap_data)
        if versus:
            codes_table += _code_rows(left, right, sources, codes, code_mask)
        for passage_scope in ("all pairs", "shared positives"):
            passages.append(passage_agreement(left, right, versus_reference=versus, scope=passage_scope))
            if len(sources) > 1:
                passages += [passage_agreement(left, right, versus_reference=versus, source=source,
                                              scope=passage_scope) for source in sources]
    if reference:
        for rule, baseline_id in (("every code present", "baseline:always-present"),
                                  ("every code absent", "baseline:always-absent")):
            if baseline_id in ids:
                raise ValueError(f"Coding set ID {baseline_id} is reserved for a baseline.")
            baseline = dict(set_id=baseline_id, baseline=rule, codebook=codebook, included=[], excluded=[],
                            presence_only=[dict(source=source, code_id=c["id"]) for source in sources for c in codes]
                            if rule == "every code present" else [])
            for level, proj, mask in levels:
                presence += _presence_rows(baseline, reference, sources, codebook["codes"], level, proj, True,
                                           mask, code_mask, bootstrap_data)
    stability = []
    by_id = {s["set_id"]: s for s in everything}
    for group in stability_groups or []:
        members = [by_id[g] for g in group if g in by_id]
        if len(members) < 2:
            continue
        for level, proj, mask in levels:
            counts = [_presence_counts(m, active_ids, proj, code_mask) for m in members]
            unfiltered = sorted({(s, proj[c["id"]] if proj else c["id"]) for s in sources for c in codes})
            universe = [unit for unit in unfiltered if unit not in mask]
            values = [[1 if count[u] else 0 for count in counts] for u in universe]
            pairwise = [r for r in presence if r["level"] == level and r["scope_kind"] == "all"
                        and {r["left"], r["right"]} <= set(group) and r["comparison"] == "between coding sets"]
            stability.append(dict(
                group=" + ".join(m["set_id"] for m in members), coding_sets=len(members), level=level,
                n_codes=code_universes[level], n_units=len(universe), **exclusion_counts(unfiltered, mask), krippendorff_alpha=krippendorff_alpha_nominal(values),
                units_all_agree=sum(1 for v in values if len(set(v)) == 1) / len(values) if values else None,
                mean_pairwise_kappa=_mean([r["cohen_kappa"] for r in pairwise]),
            ))
    units = []
    labels = _transcript_labels(sources)
    for coding_set in everything:
        counts = present_units(coding_set, active_code_ids=active_ids)
        for source in sources:
            for code in codes:
                units.append(dict(coding_set=coding_set["set_id"], transcript=labels[source],
                                  domain=_domain(code), code_id=code["id"], code=code.get("label", code["id"]),
                                  parent_code_id=projection[code["id"]],
                                  assessed=(source, code["id"]) not in code_mask,
                                  exclusion_reasons=";".join(sorted(code_mask.get((source, code["id"]), []))),
                                  present=None if (source, code["id"]) in code_mask else int(bool(counts[(source, code["id"])])),
                                  observed_present=int(bool(counts[(source, code["id"])])),
                                  proposals=counts[(source, code["id"])]))
    exclusions = [dict(level=level, document=source, code_id=code, reason=reason)
                  for level, _, mask in levels for (source, code), reasons in sorted(mask.items())
                  for reason in sorted(reasons)]
    exclusions += [dict(level="document", document=source, code_id=None, reason="excluded_document")
                   for source in document_exclusions]
    bootstrap_rows = bootstrap_intervals(bootstrap_data, sources, [s["set_id"] for s in coding_sets],
                                         reference["set_id"] if reference else "", bootstrap, seed, cluster_by_folder)
    reference_difference_rows = []
    reference_difference_assessment = None
    if second_reference is not None:
        second_present = set(present_units(second_reference, active_code_ids=active_ids))
        second_absent = {(i["source"], i.get("code_id")) for i in second_reference.get("absences", [])}
        second_mask, _ = assessment_masks(sources, active_ids, second_present, second_absent,
                                          second_explicit_absences, manual, projection)
        universe = {(source, code) for source in sources for code in active_ids}
        first_assessed, second_assessed = universe - code_mask.keys(), universe - second_mask.keys()
        shared_units = sorted(first_assessed & second_assessed)
        predictions = {s["set_id"]: set(present_units(s, active_code_ids=active_ids)) for s in coding_sets}
        baselines = {"baseline:always-present": "every code present", "baseline:always-absent": "every code absent"}
        predictions.update({"baseline:always-present": set(shared_units), "baseline:always-absent": set()})
        reference_difference_rows = reference_differences(
            predictions, baselines, reference_present, second_present, shared_units, sources,
            reference["set_id"], second_reference["set_id"], bootstrap, seed, cluster_by_folder)
        reference_difference_assessment = dict(
            n_units_before_exclusions=len(universe), first_assessed_units=len(first_assessed),
            second_assessed_units=len(second_assessed), jointly_assessed_units=len(shared_units),
            first_only_assessed_units=len(first_assessed - second_assessed),
            second_only_assessed_units=len(second_assessed - first_assessed))
        if not shared_units:
            warnings.append("No units are assessed in both references after exclusions; paired reference measures are undefined.")
    return dict(
        kind=KIND,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        qualframe_version=__version__, **get_code_provenance(),
        coding_sets=[coding_profile(s) for s in everything],
        reference=dict(set_id=reference["set_id"], label=reference["label"],
                       statement=reference.get("statement"),
                       independent_human_coding=bool(reference.get("independent_human_coding")))
        if reference else None,
        second_reference=dict(set_id=second_reference["set_id"], label=second_reference["label"],
                              statement=second_reference.get("statement"),
                              independent_human_coding=bool(second_reference.get("independent_human_coding")))
        if second_reference else None,
        reference_differences=reference_difference_rows,
        reference_difference_assessment=reference_difference_assessment,
        transcripts=sources,
        warnings=warnings, codebook_differences=differences,
        transcripts_left_out=omitted,
        documents_excluded=document_exclusions,
        unit_exclusions_requested=[dict(document=source, code_id=code, reasons=sorted(reasons))
                                   for (source, code), reasons in sorted(requested_manual.items())],
        reference_records_explicit_absences=explicit_absences,
        exclusions=exclusions,
        exclusion_summary=[dict(level=level, **exclusion_counts(
            {(source, proj[c["id"]] if proj else c["id"]) for source in sources for c in codes}, mask))
            for level, proj, mask in levels],
        bootstrap_settings=dict(replicates=bootstrap, seed=seed, cluster_by_folder=cluster_by_folder),
        bootstrap=bootstrap_rows,
        codes_table=codes_table,
        codes=len(codes),
        codebook_codes=len(codebook["codes"]),
        inactive_codes=len(codebook["codes"]) - len(codes),
        code_universes=code_universes,
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

Created {created}. {sets} coding sets on {transcripts} transcript(s) and {codes} active codes.
{code_provenance}
{universes}
{reference}
{second_reference}

Assessment and sensitivity-analysis exclusions:
{exclusion_summary}
{document_exclusions}
{bootstrap_summary}

Resource accounting uses the ledger path saved in run settings, then the manifest, then the conventional study logs path. Missing ledgers or missing request usage produce unknown (null) cost/token totals, not zero. Profiles include accounting notes, estimated-cost flags and cached/write-cache/reasoning token totals when recorded. Legacy records without a token category leave it unknown.

Files (tidy tables, one row per observation):
- `coding_sets.csv`: one row per coding set. Volume, quotation fidelity, compared-cohort request/token/cost/time totals and per-transcript means, plus explicitly labelled whole-run totals. Cohort usage follows each request source and the first transcript coding stage; later synthesis stages count only in whole-run totals. Time is summed provider-request duration, not study wall time.
- `presence.csv`: agreement on whether each code was applied to each transcript, for every pair
  of coding sets and for each set against the reference. Scopes: all units, each domain, each
  transcript. Levels: codes as coded, and sub-codes merged into their parent code.
- `codes.csv`: one row per active code and coding set against the reference: assessed-document prevalence,
  confusion counts, sensitivity, specificity and F1. Missing units never enter the denominator.
- `bootstrap.csv`: 95% percentile intervals for F1, kappa, MCC and balanced accuracy, including paired
  coding-set differences (left minus right). Empty when bootstrap is off.
- `reference_differences.csv`: each coding set and baseline scored against two references on jointly
  assessed code-level units, with paired differences (second minus first). Empty without a second reference.
- `exclusions.csv`: every excluded presence unit and reason, plus explicitly excluded documents.
  A unit may have several reasons; reason counts overlap and must not be summed as unique exclusions.
- `passages.csv`: agreement on the coded passages themselves.
- `stability.csv`: agreement among repeat runs (Krippendorff's alpha).
- `units.csv`: the presence data itself (coding set × transcript × code), for your own analysis.
- `report.json`: everything above.

Definitions
- A code-level unit is one transcript and one active code. Missing active flags in older codebooks mean active.
  Inactive entries are excluded as code-level units and proposals; they still define the hierarchy for
  projecting active codes to their top-level parents. Parent universes contain those projected parents.
  Universe counts use the first coding set's codebook; differences in active flags are warned about.
  A code is present when the coding set applied it at least once, whether or not its quotation was found.
- `no_decision_count` counts requested code decisions omitted from a response, within the compared
  transcripts and their first coding stage. These are separate from explicit absence declarations
  (`no_evidence_rows`), not failed requests. Older runs without recorded omissions count zero;
  this does not mean they were asked to decide every code. Presence measures remain based on applied
  codes: a zero is no observed application, not necessarily an explicit absence decision.
- When the reference contains explicit absence records, a document x code with neither a recognized
  presence nor an explicit absence is not assessed. It is excluded from every presence statistic,
  pairwise comparison, stability statistic, baseline and bootstrap. A presence-only reference retains
  its original implicit-negative interpretation; this is an assumption, not proof of exhaustive coding.
  `--exclude-units` also removes units from presence measures. `units.csv` keeps them with assessed=false,
  blank present, the original observed_present, and exclusion_reasons. Presence exclusions do not remove
  quotations from passage comparisons. Document exclusions remove documents from all compared tables;
  whole-run resource totals remain whole-run totals.
- Parent projections use only assessed child units. A parent is assessed if an assessed reference child
  is positive, or all active children are assessed. A partially unassessed family without an assessed
  positive is excluded, rather than counted absent. Without a reference, a partially excluded family
  is excluded. Parent exclusion reason counts refer to parent units, not child units.
- Baseline rows (`baseline:always-present`, `baseline:always-absent`) read no documents and apply the
  same assessed units, parent projections and scopes as coding sets. They appear in presence.csv;
  they are not model runs and do not contribute to usage or repeat-run stability.
- Percent agreement: share of units where both sets agree (present or absent).
- Cohen's kappa: agreement corrected for chance using each set's own rate of applying codes.
  Low when codes are rarely applied, even if agreement is high.
- Gwet's AC1: chance-corrected agreement that stays stable when most codes are absent.
- PABAK: prevalence- and bias-adjusted kappa, 2 × percent agreement − 1.
- Jaccard: units both sets marked present, out of units either set marked present.
- Precision, recall, F1 (against a reference only): precision is the share of the set's present
  units that the reference also has; recall is the share of the reference's present units that the
  set also has; F1 = 2 TP / (2 TP + FP + FN). Presence `both`, `left_only`, `right_only`, `neither`
  are respectively TP, FP, FN and TN against the reference.
- Sensitivity equals recall, TP / (TP + FN). Specificity = TN / (TN + FP). Balanced accuracy is the
  mean of sensitivity and specificity. MCC = (TP TN - FP FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN)).
- Undefined values are blank in CSV and null in JSON: precision needs a predicted positive;
  recall/sensitivity need a reference positive; specificity needs a reference negative; balanced
  accuracy needs both reference classes; MCC needs nonzero reference and prediction marginals;
  F1/Jaccard need at least one positive on either side; kappa needs nondegenerate chance agreement;
  every agreement rate needs at least one assessed unit. Transcript means average defined values only.
- Bootstrap draws whole documents with replacement, never individual document x code units.
  Cluster mode draws as many parent folders as observed, with replacement, then draws each sampled
  folder's original number of documents with replacement. Unequal folder sizes can change sample size.
  All sets, levels and scopes share each draw. Transcript means weight sampled document occurrences
  equally; domain rows keep the same sampled documents and restrict their codes. Individual-transcript
  intervals are conditional on that document being drawn and provide no within-document uncertainty.
  Undefined replicates are omitted separately for each estimate; paired differences require both
  estimates defined in the same draw. valid_replicates and undefined_replicates make this visible.
  Intervals use linear-interpolated 2.5th/97.5th percentiles of defined replicates and stay blank if
  none are defined. With few documents/folders, percentile coverage can be poor; these are descriptive
  resampling intervals, not evidence of generalizability. Baselines receive intervals; paired
  differences compare actual coding sets only.
- Passage F1: passages for the same code in the same transcript matched one to one: exactly
  (same start and end), with shared text at least a quarter, half or three quarters of their
  combined extent (IoU ≥ 0.25, 0.5, 0.75), or with any overlap.
  F1 = 2 × matched / (passages in left + passages in right).
- Passage `scope` is "all pairs" (the original pooled analysis) or "shared positives" (only document ×
  code pairs with at least one located passage on each side). `shared_positive_pairs` counts these pairs;
  left_passages/right_passages count passages within the selected scope. Both scopes use identical
  matching and coded-text rules, including alternative-location exclusions. The document label formerly
  in passage `scope` is retained in `transcript`; numeric pooled measurements are unchanged.
- `scope_kind` "all" pools every unit or passage; "transcript" rows give each transcript separately;
  "transcript mean" weights each transcript equally (the mean of the transcript rows). When filenames repeat, transcript labels use relative paths so distinct sources stay separate.
- Repeated reference quotations retain alternative spans with match: repeated. An annotation matches
  at a threshold if any candidate location meets it; it is still one passage and can match only once.
  Coding-set profiles count unique, repeated and unanchored reference passages with recognized codes;
  unknown-code rows, presence-only rows and explicit absences are reported separately.
  `located_after_word_normalization` separately counts uniquely located `normalized_words_candidate`
  quotations; these are located candidates awaiting researcher confirmation, as typography candidates are.
  Imported-reference candidates are flagged requires_confirmation and counted separately. References do
  not have the model-proposal Accept workflow: check locations against sources and record the check in
  reference provenance (or correct quotes and import a new reference). Comparison never confirms them.
  Passage-word medians and duplicate-span counts use uniquely located passages only.
- Coded-text Jaccard: characters both sets coded with the same code, out of characters either did.
  Passages with alternative locations are omitted from all character-overlap totals, with counts
  per side and in each coding-set profile. Other uniquely located passages remain in the union;
  an all-repeated reference can therefore have passage matches but zero text Jaccard against a
  nonempty model coding. If both remaining text sets are empty, text Jaccard is undefined.
  Earlier saved references remain readable and unchanged; only a new import gains alternatives.
- Krippendorff's alpha (nominal): agreement among several coding sets on the same units, corrected
  for chance. 1 is perfect agreement; 0 is agreement at chance.
- With `--second-reference`, all inputs must share the report's document cohort. Ordinary presence,
  codes, units and bootstrap tables continue to use the first reference's assessment mask. The separate
  reference-difference table intersects both references' assessed code-level units after manual exclusions;
  both reference estimates, prevalences and baselines use that identical denominator. Documents without
  jointly assessed units are omitted from this paired resampling. No parent-code projection is applied.
  a/b denote the first/second reference; difference is b minus a. Every coding set and baseline uses
  identical document or folder-then-document draws for both references, and percentile limits are
  interpolated as in bootstrap.csv. Each marginal interval retains its defined replicates; a difference
  requires both values defined in the same draw. Counts of defined and undefined replicates are explicit.
  Without bootstrap, point estimates remain available and intervals are blank. The earlier standalone
  paired script used random.choice and non-interpolated percentile ranks and could use different assessed
  units per reference; numerical equivalence therefore requires identical assessment masks, while its
  intervals need not be identical even with the same seed.

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
                       ("units", report["units"]), ("codes", report.get("codes_table", [])),
                       ("bootstrap", report.get("bootstrap", [])), ("exclusions", report.get("exclusions", [])),
                       ("reference_differences", report.get("reference_differences", []))):
        (folder / f"{name}.csv").write_text(_csv(rows), encoding="utf-8")
    reference = report["reference"]
    second = report.get("second_reference")
    dirty = report.get("git_dirty")
    (folder / "README.md").write_text(README.format(
        created=report["created_at_utc"][:16].replace("T", " ") + " UTC",
        code_provenance=f"QualFrame {report.get('qualframe_version') or 'not recorded'}; Git commit: "
                        f"{report.get('git_commit') or 'not recorded'}; uncommitted changes: "
                        f"{'yes' if dirty is True else 'no' if dirty is False else 'not recorded'}.",
        sets=len(report["coding_sets"]), transcripts=len(report["transcripts"]), codes=report["codes"],
        universes="Presence universes: " + "; ".join(
            f"{level}: {count} codes" for level, count in report.get("code_universes", {"code": report["codes"]}).items()) + ".",
        reference=f"Reference: {reference['label']}." if reference else "No reference coding.",
        second_reference=(f"Second reference: {second['label']}. Paired assessment: "
                          + json.dumps(report.get("reference_difference_assessment", {})) + ".") if second else "",
        exclusion_summary="\n".join(
            f"- {row['level']}: {row['excluded_units']} of {row['n_units_before_exclusions']} units excluded; "
            + "; ".join(f"{reason}: {row[reason]}" for reason in REASONS) + "."
            for row in report.get("exclusion_summary", [])) or "- No unit exclusion metadata (legacy report).",
        document_exclusions="Explicit document exclusions: " + ("; ".join(report.get("documents_excluded", [])) or "none") + ".",
        bootstrap_summary="Bootstrap settings: " + json.dumps(report.get("bootstrap_settings", {})) + ".",
        statement=(reference["statement"] if reference else ""),
        warnings="\n".join("- Warning: " + note for note in report.get("warnings", [])),
    ), encoding="utf-8")
    return folder
