"""Presence assessment, exclusions and document-level bootstrap helpers (no study I/O)."""
from __future__ import annotations

import csv
import math
import random
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

REASONS = ("reference_not_assessed", "excluded_code", "excluded_domain", "parent_not_fully_assessed")
METRICS = ("f1", "cohen_kappa", "mcc", "balanced_accuracy")


def accuracy_statistics(tp: int, fp: int, fn: int, tn: int) -> dict:
    sensitivity = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    denominator = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    return dict(sensitivity=sensitivity, specificity=specificity,
                balanced_accuracy=(sensitivity + specificity) / 2
                if sensitivity is not None and specificity is not None else None,
                mcc=(tp * tn - fp * fn) / math.sqrt(denominator) if denominator else None)


def document_match(value: str, sources: list[str]) -> str:
    """An exact path, unambiguous path suffix or file name; never silently pick one."""
    value = value.strip().replace("\\", "/")
    exact = [s for s in sources if s.replace("\\", "/") == value]
    matches = exact or [s for s in sources if s.replace("\\", "/").endswith("/" + value)
                       or value.endswith("/" + s.replace("\\", "/"))]
    if len(matches) != 1:
        raise ValueError(f"Document {value!r} matches {len(matches)} documents; give one unambiguous path.")
    return matches[0]


def load_document_exclusions(path: Path | None, sources: list[str]) -> list[str]:
    if path is None:
        return []
    return sorted({document_match(line, sources) for line in path.read_text(encoding="utf-8-sig").splitlines()
                   if line.strip()})


def load_unit_exclusions(path: Path | None, sources: list[str], codes: list[dict], domain) -> dict:
    if path is None:
        return {}
    exclusions: dict = defaultdict(set)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        if len(columns) != 2 or set(columns) not in ({"document", "code"}, {"document", "domain"}):
            raise ValueError("Exclude-units CSV must have exactly document,code or document,domain columns.")
        key = "code" if "code" in columns else "domain"
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed exclude-units CSV row {number}.")
            source = document_match(row["document"], sources)
            value = row[key].strip()
            if not value:
                raise ValueError(f"Empty {key} in exclude-units CSV row {number}.")
            if key == "code":
                found = [c for c in codes if c["id"] == value]
                found = found or [c for c in codes if value in (c.get("label"), c.get("raw_label"))]
                if len(found) != 1:
                    raise ValueError(f"Code {value!r} matches {len(found)} active codes; give its unique code ID.")
            else:
                normalized = domain({"domain": value})
                found = [c for c in codes if domain(c) == normalized]
                if not found:
                    raise ValueError(f"Domain {value!r} matches no active codes.")
            for code in found:
                exclusions[(source, code["id"])].add("excluded_" + key)
    return dict(exclusions)


def assessment_masks(sources: list[str], code_ids: set[str], reference_present: set,
                     reference_absent: set, explicit_absences: bool, manual: dict,
                     projection: dict[str, str]) -> tuple[dict, dict]:
    """Exclude unassessed reference cells. A partial parent needs an assessed positive.

    Manual exclusions remove that child's application from both sides before projection.
    Otherwise a partially unassessed family cannot establish a negative parent.
    """
    code_mask = {unit: set(reasons) for unit, reasons in manual.items()}
    for source in sources:
        for code in code_ids:
            unit = source, code
            if explicit_absences and unit not in reference_present and unit not in reference_absent:
                code_mask.setdefault(unit, set()).add("reference_not_assessed")
    children: dict = defaultdict(set)
    for code in code_ids:
        children[projection[code]].add(code)
    parent_mask = {}
    for source in sources:
        for parent, members in children.items():
            units = {(source, code) for code in members}
            removed = units & code_mask.keys()
            assessed_positive = bool((units - code_mask.keys()) & reference_present)
            if removed and not assessed_positive:
                reasons = set().union(*(code_mask[unit] for unit in removed))
                reasons.add("parent_not_fully_assessed")
                parent_mask[(source, parent)] = reasons
    return code_mask, parent_mask


def exclusion_counts(units: list | set, mask: dict) -> dict:
    excluded = set(units) & mask.keys()
    return dict(n_units_before_exclusions=len(units), excluded_units=len(excluded),
                **{reason: sum(reason in mask[unit] for unit in excluded) for reason in REASONS})


def sample_documents(rng: random.Random, sources: list[str], cluster_by_folder: bool) -> list[str]:
    if not cluster_by_folder:
        return rng.choices(sources, k=len(sources))
    folders: dict[str, list[str]] = defaultdict(list)
    for source in sources:
        folders[source.replace("\\", "/").rsplit("/", 1)[0] if "/" in source.replace("\\", "/") else "."].append(source)
    result = []
    for folder in rng.choices(sorted(folders), k=len(folders)):
        documents = folders[folder]
        result.extend(rng.choices(documents, k=len(documents)))
    return result


def _statistics(counts: tuple | list) -> dict:
    tp, fp, fn, tn = counts
    n = sum(counts)
    # Algebraic kappa denominator avoids floating point cancellation near perfect marginals.
    expected_numerator = (tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)
    denominator = n * n - expected_numerator
    return dict(f1=2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None,
                cohen_kappa=(n * (tp + tn) - expected_numerator) / denominator if denominator else None,
                **accuracy_statistics(tp, fp, fn, tn))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    location = (len(ordered) - 1) * fraction
    lower = math.floor(location)
    upper = math.ceil(location)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (location - lower)


def bootstrap_intervals(data: dict, sources: list[str], coding_set_ids: list[str], reference_id: str,
                        replicates: int, seed: int, cluster_by_folder: bool) -> list[dict]:
    """data[(set, level, scope_kind, scope)] maps documents to four confusion counts.

    Every comparison and paired difference uses the identical draw; counts are multiplied by
    document multiplicity. Undefined estimates and jointly undefined differences are counted.
    """
    if not replicates:
        return []
    rng = random.Random(seed)
    values: dict = defaultdict(list)
    def evaluate(key, documents, weights):
        if key[2] == "transcript mean":
            per_document = {source: _statistics(counts) for source, counts in documents.items()}
            return {metric: sum(stats[metric] * weights[source] for source, stats in per_document.items()
                                if stats[metric] is not None) / denominator
                    if (denominator := sum(weights[source] for source, stats in per_document.items()
                                           if stats[metric] is not None)) else None for metric in METRICS}
        return _statistics([sum(counts[i] * weights[source] for source, counts in documents.items())
                            for i in range(4)])

    points = {key: evaluate(key, documents, Counter(sources)) for key, documents in data.items()}
    paired = []
    for a, b in combinations(coding_set_ids, 2):
        for key in data:
            if key[0] == a and (b, *key[1:]) in data:
                paired.append((key, (b, *key[1:])))
    for _ in range(replicates):
        weights = Counter(sample_documents(rng, sources, cluster_by_folder))
        estimates = {key: evaluate(key, docs, weights) for key, docs in data.items()}
        for key, stats in estimates.items():
            for metric in METRICS:
                if stats[metric] is not None:
                    values[(key, None, metric)].append(stats[metric])
        for a, b in paired:
            for metric in METRICS:
                if estimates[a][metric] is not None and estimates[b][metric] is not None:
                    values[(a, b, metric)].append(estimates[a][metric] - estimates[b][metric])
    rows = []
    for a, b in [(key, None) for key in data] + paired:
        for metric in METRICS:
            observed = points[a][metric]
            if b is not None:
                observed = observed - points[b][metric] if observed is not None and points[b][metric] is not None else None
            distribution = values[(a, b, metric)]
            rows.append(dict(kind="paired_difference" if b else "estimate", left=a[0],
                             right=b[0] if b else reference_id, reference=reference_id,
                             level=a[1], scope_kind=a[2], scope=a[3], metric=metric, estimate=observed,
                             lower_95=_percentile(distribution, .025), upper_95=_percentile(distribution, .975),
                             replicates=replicates, valid_replicates=len(distribution),
                             undefined_replicates=replicates - len(distribution), seed=seed,
                             resampling="folders_then_documents" if cluster_by_folder else "documents",
                             documents=len(sources), folders=len({s.replace("\\", "/").rsplit("/", 1)[0]
                                          if "/" in s.replace("\\", "/") else "." for s in sources}),
                             difference_direction="left minus right" if b else None))
    return rows
