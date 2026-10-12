"""Descriptive exact/overlap span agreement on preserved source-valid raw outputs."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from statistics import mean, median

from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import compare_raw_payloads

# Ratios avoid threshold-boundary differences caused by floating-point rounding.
MATCH_POLICIES = {"exact": (1, 1), "iou_0_25": (1, 4), "iou_0_50": (1, 2), "iou_0_75": (3, 4)}


@dataclass(frozen=True)
class _Span:
    source: str
    code_id: str
    start: int
    end: int
    record_ids: tuple[str, ...]

    def reference(self) -> dict:
        identity = dict(source=self.source, code_id=self.code_id, start=self.start, end=self.end)
        return dict(identity, span_id=snapshot_identity(identity), record_ids=list(self.record_ids))


def _catalog(payload: dict) -> tuple[list[dict], dict]:
    grouped: dict[str, list[dict]] = {}
    for entry in payload["codebook"]["codes"]:
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Frozen benchmark codebook entries need nonblank code IDs.")
        grouped.setdefault(identifier, []).append(entry)
    duplicates = []
    for identifier, entries in sorted(grouped.items()):
        if len(entries) > 1:
            variants = {snapshot_identity(entry) for entry in entries}
            duplicates.append(
                dict(
                    code_id=identifier,
                    entry_count=len(entries),
                    distinct_entry_count=len(variants),
                    ambiguous=len(variants) > 1,
                    labels=sorted({entry["label"] for entry in entries}),
                    entry_hashes=sorted(variants),
                )
            )
    return (
        [entries[0] for _, entries in sorted(grouped.items())],
        dict(
            catalog_entry_count=sum(len(entries) for entries in grouped.values()),
            unique_code_id_count=len(grouped),
            duplicate_code_id_count=len(duplicates),
            duplicate_catalog_entries=sum(row["entry_count"] - 1 for row in duplicates),
            ambiguous_code_ids=[row["code_id"] for row in duplicates if row["ambiguous"]],
            duplicate_ids=duplicates,
        ),
    )


def _span_sets(payload: dict, ambiguous_ids: set[str]) -> list[_Span]:
    known = {code["id"] for code in payload["codebook"]["codes"]}
    groups: dict[tuple[str, str, int, int], list[str]] = {}
    seen_ids = set()
    for item in payload["included"]:
        if item["code_id"] in ambiguous_ids:
            raise ValueError("Included benchmark spans cannot use an ambiguous duplicate code ID.")
        if item["source"] not in payload["sources"] or item["code_id"] not in known:
            raise ValueError(
                "Included benchmark spans must belong to the frozen sources and codebook."
            )
        if (
            type(item["start"]) is not int
            or type(item["end"]) is not int
            or item["start"] < 0
            or item["end"] <= item["start"]
        ):
            raise ValueError("Included benchmark spans need valid exclusive-end source offsets.")
        identifier = item["record_id"]
        if not isinstance(identifier, str) or not identifier or identifier in seen_ids:
            raise ValueError(
                "Benchmark proposal identities must be nonblank and unique within a run."
            )
        seen_ids.add(identifier)
        key = (item["source"], item["code_id"], item["start"], item["end"])
        groups.setdefault(key, []).append(identifier)
    return [_Span(*key, tuple(sorted(ids))) for key, ids in sorted(groups.items())]


def _overlap(left: _Span, right: _Span) -> tuple[int, int]:
    intersection = max(0, min(left.end, right.end) - max(left.start, right.start))
    union = left.end - left.start + right.end - right.start - intersection
    return intersection, union


def _maximum_matching(
    left: list[_Span], right: list[_Span], ratio: tuple[int, int]
) -> list[tuple[_Span, _Span]]:
    """Deterministic augmenting paths; maximum cardinality, not greedy edge selection."""
    numerator, denominator = ratio
    adjacent: list[list[int]] = []
    for a in left:
        edges = []
        for index, b in enumerate(right):
            if a.source != b.source or a.code_id != b.code_id:
                continue
            intersection, union = _overlap(a, b)
            if intersection and intersection * denominator >= union * numerator:
                edges.append(index)
        adjacent.append(edges)
    return [(left[a], right[b]) for a, b in _maximum_matching_indices(adjacent)]


def _maximum_matching_indices(adjacent: list[list[int]]) -> list[tuple[int, int]]:
    """Match graph nodes one to one, using deterministic maximum-cardinality augmenting paths.

    Each list position is a left node; its entries identify eligible right nodes. This
    keeps passage identity separate from the span rules used to construct the edges.
    """
    right_owner: dict[int, int] = {}
    left_match: dict[int, int] = {}
    for starting in range(len(adjacent)):
        queue = deque([starting])
        visited_left = {starting}
        prior_right: dict[int, int] = {}
        free_right = None
        while queue and free_right is None:
            a = queue.popleft()
            for b in adjacent[a]:
                if b in prior_right:
                    continue
                prior_right[b] = a
                owner = right_owner.get(b)
                if owner is None:
                    free_right = b
                    break
                if owner not in visited_left:
                    visited_left.add(owner)
                    queue.append(owner)
        if free_right is None:
            continue
        b = free_right
        while True:
            a = prior_right[b]
            previous = left_match.get(a)
            left_match[a] = b
            right_owner[b] = a
            if previous is None:
                break
            b = previous
    return sorted(left_match.items())


def _diagnostics(matches: list[tuple[_Span, _Span]]) -> dict:
    ious = [common / union for a, b in matches for common, union in [_overlap(a, b)]]
    start = [abs(a.start - b.start) for a, b in matches]
    end = [abs(a.end - b.end) for a, b in matches]
    return dict(
        matched_pairs=len(matches),
        mean_iou=mean(ious) if ious else None,
        median_iou=median(ious) if ious else None,
        minimum_iou=min(ious) if ious else None,
        maximum_iou=max(ious) if ious else None,
        median_absolute_start_difference=median(start) if start else None,
        median_absolute_end_difference=median(end) if end else None,
        maximum_absolute_boundary_difference=max(start + end) if matches else None,
    )


def _measure(
    left: list[_Span],
    right: list[_Span],
    matches: list[tuple[_Span, _Span]],
    *,
    details: bool = False,
) -> dict:
    n_left, n_right, matched = len(left), len(right), len(matches)
    result = dict(
        left_spans=n_left,
        right_spans=n_right,
        matched_spans=matched,
        unmatched_left_count=n_left - matched,
        unmatched_right_count=n_right - matched,
        matched_fraction_left=matched / n_left if n_left else None,
        matched_fraction_right=matched / n_right if n_right else None,
        f1_dice=2 * matched / (n_left + n_right) if n_left + n_right else None,
        boundary_diagnostics=_diagnostics(matches),
    )
    if details:
        seen_left = {a for a, _ in matches}
        seen_right = {b for _, b in matches}
        result["matches"] = [
            dict(
                left=a.reference(),
                right=b.reference(),
                intersection_characters=_overlap(a, b)[0],
                union_characters=_overlap(a, b)[1],
                iou=_overlap(a, b)[0] / _overlap(a, b)[1],
                start_difference_right_minus_left=b.start - a.start,
                end_difference_right_minus_left=b.end - a.end,
            )
            for a, b in matches
        ]
        result["unmatched_left"] = [item.reference() for item in left if item not in seen_left]
        result["unmatched_right"] = [item.reference() for item in right if item not in seen_right]
    return result


def _validity(payload: dict, spans: list[_Span]) -> dict:
    included = len(payload["included"])
    excluded = len(payload["excluded"])
    denominator = included + excluded
    return dict(
        included_proposals=included,
        excluded_proposals=excluded,
        assessed_proposals=denominator,
        excluded_fraction=excluded / denominator if denominator else None,
        valid_absence_declarations=len(payload["absences"]),
        unique_labelled_spans=len(spans),
        duplicate_proposals=included - len(spans),
        duplicate_fraction=(included - len(spans)) / included if included else None,
    )


def build_benchmark_report(left: dict, right: dict) -> dict:
    """No provider/file effects; input validity relies on raw_coding_payload validation."""
    codes, diagnostics = _catalog(left)
    _, right_diagnostics = _catalog(right)
    ambiguous_ids = set(diagnostics["ambiguous_code_ids"])
    a = _span_sets(left, ambiguous_ids)
    b = _span_sets(right, set(right_diagnostics["ambiguous_code_ids"]))
    # Keep the v1 comparator and its cohort/codebook eligibility rules authoritative.
    # It is called without changing either payload or the original v1 report schema.
    compare_raw_payloads(left, right)
    all_matches = {name: [] for name in MATCH_POLICIES}
    by_code = []
    for code in codes:
        ca = [item for item in a if item.code_id == code["id"]]
        cb = [item for item in b if item.code_id == code["id"]]
        measures = {}
        for name, ratio in MATCH_POLICIES.items():
            pairs = _maximum_matching(ca, cb, ratio)
            all_matches[name].extend(pairs)
            measures[name] = _measure(ca, cb, pairs, details=True)
        by_code.append(
            dict(
                code_id=code["id"],
                code_label=code["label"],
                ambiguous_code_id=code["id"] in ambiguous_ids,
                left_spans=len(ca),
                right_spans=len(cb),
                left_duplicate_proposals=sum(len(item.record_ids) - 1 for item in ca),
                right_duplicate_proposals=sum(len(item.record_ids) - 1 for item in cb),
                measures=measures,
            )
        )
    summary = {name: _measure(a, b, pairs) for name, pairs in all_matches.items()}
    macro = {}
    for name in MATCH_POLICIES:
        values = [
            row["measures"][name]["f1_dice"]
            for row in by_code
            if row["measures"][name]["f1_dice"] is not None
        ]
        macro[name] = dict(
            mean_f1_dice=mean(values) if values else None,
            defined_codes=len(values),
            undefined_codes=len(codes) - len(values),
        )
    by_source = []
    for source in sorted(left["sources"]):
        sa = [item for item in a if item.source == source]
        sb = [item for item in b if item.source == source]
        by_source.append(
            dict(
                source=source,
                measures={
                    name: _measure(sa, sb, [(x, y) for x, y in pairs if x.source == source])
                    for name, pairs in all_matches.items()
                },
            )
        )
    return dict(
        kind="qualframe_benchmark_report_v1",
        metric_version="labelled_source_spans_v1",
        project_id=left["project_id"],
        input_hashes=dict(left=snapshot_identity(left), right=snapshot_identity(right)),
        inputs=dict(left=deepcopy(left), right=deepcopy(right)),
        validity=dict(left=_validity(left, a), right=_validity(right, b)),
        codebook_diagnostics=diagnostics,
        matching_policy=dict(
            grouping="same source hash/path and exact code ID; no parent-code or semantic matching",
            thresholds={
                name: numerator / denominator
                for name, (numerator, denominator) in MATCH_POLICIES.items()
            },
            objective="maximum cardinality one-to-one matching at each inclusive IoU threshold",
            tie_policy=(
                "canonical source/code/start/end order; breadth-first augmenting "
                "paths; total IoU is not optimized"
            ),
            offsets=(
                "zero-based Unicode code points with exclusive end; context "
                "outside the coded span excluded"
            ),
            duplicates=(
                "identical source/code/start/end proposals counted once; all "
                "record IDs and duplicate counts retained"
            ),
        ),
        summary=summary,
        macro_by_code=macro,
        by_code=by_code,
        by_source=by_source,
        interpretation=(
            "Descriptive agreement of source-valid raw span sets. "
            "Within-configuration repeats describe stability; different "
            "configurations describe agreement. Neither is accuracy, semantic "
            "validity, or an independently adjudicated human reference."
        ),
        aggregation=(
            "Summary pools matched/left/right counts across sources and codes. "
            "Macro averages defined per-code F1 values, with undefined-code "
            "counts retained. Match diagnostics concern only matched spans and "
            "can be optimistic when few spans match."
        ),
        empty_policy=(
            "Both sets empty: F1 and matched fractions undefined (null). Only one "
            "empty: F1 zero; its matched fraction undefined and the nonempty side "
            "zero. Failed runs are unavailable, never empty sets."
        ),
        validity_policy=(
            "Scores cover included source-valid raw proposals only. Excluded "
            "proposals and known-code absence declarations remain separate. "
            "Duplicate proposals do not inflate span support. High overlap in the "
            "valid subset can overstate whole-output agreement."
        ),
        limitations=(
            "Exact F1 is a monotonic transform of exact Jaccard, not independent "
            "corroboration. IoU thresholds 0.25/0.50/0.75 are prespecified "
            "sensitivity choices, not validated qualitative correctness cutoffs. "
            "Pairwise observations and spans within transcripts/groups are not "
            "independent. Assumed test acceptance is not human reference coding."
        ),
    )
