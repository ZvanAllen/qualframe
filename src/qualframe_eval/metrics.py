"""Deterministic metrics for transcript, network, and cross-network comparisons."""

from __future__ import annotations


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Return Jaccard similarity between two sets. Returns 1.0 if both are empty."""
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / len(set_a | set_b)


def pairwise_percent_agreement(labels_a: list[str], labels_b: list[str]) -> float:
    """Return the fraction of positions where two label lists agree."""
    if not labels_a:
        return 0.0
    same = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    return same / len(labels_a)
