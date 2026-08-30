from qualframe_eval.metrics import jaccard_similarity, pairwise_percent_agreement


def test_jaccard_similarity() -> None:
    assert jaccard_similarity({1, 2}, {2, 3}) == 1 / 3


def test_jaccard_both_empty() -> None:
    assert jaccard_similarity(set(), set()) == 1.0


def test_jaccard_one_empty() -> None:
    assert jaccard_similarity({1, 2}, set()) == 0.0


def test_pairwise_percent_agreement() -> None:
    assert pairwise_percent_agreement(["A", "B", "C"], ["A", "X", "C"]) == 2 / 3


def test_pairwise_empty() -> None:
    assert pairwise_percent_agreement([], []) == 0.0
