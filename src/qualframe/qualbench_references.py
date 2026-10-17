"""Paired reference sensitivity analysis on jointly assessed units (no file I/O)."""
from __future__ import annotations

import random
from collections import Counter

from qualframe.qualbench_presence import accuracy_statistics, sample_documents, _percentile

METRICS = ("sensitivity", "specificity", "balanced_accuracy", "mcc")


def reference_differences(predictions: dict[str, set], baselines: dict[str, str],
                          first_present: set, second_present: set, units: list[tuple[str, str]],
                          sources: list[str], first_id: str, second_id: str,
                          replicates: int, seed: int, cluster_by_folder: bool) -> list[dict]:
    """Use the same assessed units, predictions and document draws on both references.

    All coding sets and deterministic baselines share each draw. An undefined estimate
    remains null; its paired difference requires both estimates from that draw.
    """
    assessed_documents = {source for source, _ in units}
    # Documents with no jointly assessed cells contribute no observations to this analysis.
    documents = [source for source in sources if source in assessed_documents]
    per_document = {}
    for coding_set, positive in predictions.items():
        counts = {source: [[0, 0, 0, 0], [0, 0, 0, 0]] for source in documents}
        for unit in units:
            predicted = unit in positive
            for index, reference in enumerate((first_present, second_present)):
                truth = unit in reference
                category = 0 if predicted and truth else 1 if predicted else 2 if truth else 3
                counts[unit[0]][index][category] += 1
        per_document[coding_set] = counts

    def evaluate(counts: dict, weights: Counter, index: int) -> dict:
        totals = [sum(pair[index][i] * weights[source] for source, pair in counts.items())
                  for i in range(4)]
        return accuracy_statistics(*totals)

    points = {coding_set: [evaluate(counts, Counter(documents), index) for index in (0, 1)]
              for coding_set, counts in per_document.items()}
    distributions = {(coding_set, metric): [[], [], []]
                     for coding_set in predictions for metric in METRICS}
    rng = random.Random(seed)
    for _ in range(replicates):
        weights = Counter(sample_documents(rng, documents, cluster_by_folder)) if documents else Counter()
        for coding_set, counts in per_document.items():
            a, b = (evaluate(counts, weights, index) for index in (0, 1))
            for metric in METRICS:
                values = distributions[(coding_set, metric)]
                if a[metric] is not None:
                    values[0].append(a[metric])
                if b[metric] is not None:
                    values[1].append(b[metric])
                if a[metric] is not None and b[metric] is not None:
                    values[2].append(b[metric] - a[metric])
    rows = []
    universe = set(units)
    for coding_set in predictions:
        for metric in METRICS:
            a, b = (point[metric] for point in points[coding_set])
            values = distributions[(coding_set, metric)]
            rows.append(dict(
                coding_set=coding_set, baseline=baselines.get(coding_set), level="code", metric=metric,
                first_reference=first_id, second_reference=second_id,
                a=a, a_lower=_percentile(values[0], .025), a_upper=_percentile(values[0], .975),
                b=b, b_lower=_percentile(values[1], .025), b_upper=_percentile(values[1], .975),
                difference=b - a if a is not None and b is not None else None,
                difference_lower=_percentile(values[2], .025), difference_upper=_percentile(values[2], .975),
                n_units=len(units), units_a=len(units), units_b=len(units),
                prevalence_a=len(universe & first_present) / len(units) if units else None,
                prevalence_b=len(universe & second_present) / len(units) if units else None,
                replicates=replicates, valid_replicates_a=len(values[0]), valid_replicates_b=len(values[1]),
                valid_replicates=len(values[2]), undefined_replicates_a=replicates - len(values[0]),
                undefined_replicates_b=replicates - len(values[1]), undefined_replicates=replicates - len(values[2]),
                documents=len(documents), folders=len({source.replace("\\", "/").rsplit("/", 1)[0]
                    if "/" in source.replace("\\", "/") else "." for source in documents}),
                seed=seed, resampling="folders_then_documents" if cluster_by_folder else "documents",
                difference_direction="second minus first"))
    return rows
