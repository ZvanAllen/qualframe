import copy
import itertools

import pytest
from test_run_comparison import runs

from qualframe.benchmark_metrics import build_benchmark_report
from qualframe.run_comparison import compare_raw_payloads, raw_coding_payload


def payload(run_id, entries=(), *, excluded=0, absences=0):
    rows = []
    for index, entry in enumerate(entries):
        source, code, start, end = entry
        rows.append(
            dict(
                record_id=f"{run_id}-{index}",
                source=source,
                code_id=code,
                start=start,
                end=end,
                exact_text="x" * (end - start),
            )
        )
    return dict(
        kind="qualframe_raw_comparison_input_v1",
        run_id=run_id,
        project_id="test",
        configuration_fingerprint="same",
        sources={"s1": "abc", "s2": "def"},
        codebook={"codes": [{"id": "c1", "label": "Code 1"}, {"id": "c2", "label": "Code 2"}]},
        included=rows,
        excluded=[dict(record_id=f"excluded-{i}") for i in range(excluded)],
        absences=[dict(record_id=f"absence-{i}") for i in range(absences)],
    )


def measure(report, name="exact"):
    return report["summary"][name]


def test_exact_f1_counts_match_existing_jaccard_without_changing_v1():
    left = payload("left", [("s1", "c1", 0, 10), ("s1", "c1", 15, 20)])
    right = payload("right", [("s1", "c1", 0, 10)])
    before = compare_raw_payloads(left, right)
    original = copy.deepcopy((left, right))
    report = build_benchmark_report(left, right)
    exact = measure(report)
    assert exact["matched_spans"] == 1
    assert exact["matched_fraction_left"] == 0.5 and exact["matched_fraction_right"] == 1
    assert exact["f1_dice"] == pytest.approx(2 / 3)
    jaccard = before["summary"]["exact_span_jaccard"]
    assert exact["f1_dice"] == pytest.approx(2 * jaccard / (1 + jaccard))
    assert compare_raw_payloads(left, right) == before and (left, right) == original
    assert report["macro_by_code"]["exact"]["defined_codes"] == 1
    assert report["macro_by_code"]["exact"]["undefined_codes"] == 1
    left["included"][0]["record_id"] = "changed after report"
    assert report["inputs"]["left"]["included"][0]["record_id"] == "left-0"


def test_split_merge_cannot_match_one_span_twice():
    left = payload("left", [("s1", "c1", 0, 10)])
    right = payload("right", [("s1", "c1", 0, 5), ("s1", "c1", 5, 10)])
    report = build_benchmark_report(left, right)
    assert measure(report)["f1_dice"] == 0
    assert measure(report, "iou_0_50")["f1_dice"] == pytest.approx(2 / 3)
    assert measure(report, "iou_0_75")["f1_dice"] == 0
    assert measure(report, "iou_0_50")["boundary_diagnostics"]["median_iou"] == 0.5
    assert (
        measure(report, "iou_0_50")["boundary_diagnostics"]["maximum_absolute_boundary_difference"]
        == 5
    )
    reverse = build_benchmark_report(right, left)
    assert measure(reverse, "iou_0_50")["f1_dice"] == pytest.approx(2 / 3)
    assert measure(reverse, "iou_0_50")["matched_fraction_left"] == 0.5
    details = report["by_code"][0]["measures"]["iou_0_50"]
    assert len(details["matches"]) == len(details["unmatched_right"]) == 1
    assert details["matches"][0]["left"]["record_ids"] == ["left-0"]


def test_augmenting_path_finds_two_matches_where_first_edge_greedy_fails():
    # L0 can match either right span at .25. L1 can only match R0.
    # Canonical first-edge greedy takes L0-R0 and loses the second match.
    left = payload("left", [("s1", "c1", 0, 10), ("s1", "c1", 8, 12)])
    right = payload("right", [("s1", "c1", 4, 12), ("s1", "c1", 5, 8)])
    report = build_benchmark_report(left, right)
    result = measure(report, "iou_0_25")
    assert result["matched_spans"] == 2 and result["f1_dice"] == 1
    assert measure(report, "iou_0_50")["matched_spans"] == 1
    pairs = report["by_code"][0]["measures"]["iou_0_25"]["matches"]
    assert [(item["left"]["record_ids"], item["right"]["record_ids"]) for item in pairs] == [
        (["left-0"], ["right-1"]),
        (["left-1"], ["right-0"]),
    ]
    for a_order, b_order in itertools.product(
        itertools.permutations(left["included"]), itertools.permutations(right["included"])
    ):
        candidate = build_benchmark_report(
            dict(left, included=list(a_order)), dict(right, included=list(b_order))
        )
        assert candidate["summary"] == report["summary"]
        assert candidate["by_code"] == report["by_code"]


def test_wrong_code_or_source_never_matches_even_identical_boundaries():
    left = payload("left", [("s1", "c1", 0, 10)])
    for source, code in [("s1", "c2"), ("s2", "c1")]:
        right = payload("right", [(source, code, 0, 10)])
        report = build_benchmark_report(left, right)
        assert all(
            item["matched_spans"] == 0 and item["f1_dice"] == 0
            for item in report["summary"].values()
        )
        assert all(
            item["boundary_diagnostics"]["mean_iou"] is None for item in report["summary"].values()
        )


def test_empty_sets_are_undefined_not_perfect_and_one_empty_is_zero():
    empty = payload("left")
    report = build_benchmark_report(empty, payload("right"))
    assert all(item["f1_dice"] is None for item in report["summary"].values())
    assert report["validity"]["left"]["duplicate_fraction"] is None
    assert report["validity"]["left"]["excluded_fraction"] is None
    right = payload("right", [("s1", "c1", 0, 10)])
    report = build_benchmark_report(empty, right)
    assert all(item["f1_dice"] == 0 for item in report["summary"].values())
    assert measure(report)["matched_fraction_left"] is None
    assert measure(report)["matched_fraction_right"] == 0
    assert report["macro_by_code"]["exact"]["mean_f1_dice"] == 0
    assert report["macro_by_code"]["exact"]["undefined_codes"] == 1


def test_duplicates_and_invalid_subset_are_reported_without_inflation():
    left = payload("left", [("s1", "c1", 0, 10), ("s1", "c1", 0, 10)], excluded=1, absences=2)
    right = payload("right", [("s1", "c1", 0, 10)])
    report = build_benchmark_report(left, right)
    validity = report["validity"]["left"]
    assert validity["included_proposals"] == 2 and validity["unique_labelled_spans"] == 1
    assert validity["duplicate_proposals"] == 1 and validity["duplicate_fraction"] == 0.5
    assert validity["excluded_fraction"] == pytest.approx(1 / 3)
    assert validity["valid_absence_declarations"] == 2
    assert measure(report)["f1_dice"] == 1 and measure(report)["left_spans"] == 1
    matches = report["by_code"][0]["measures"]["exact"]["matches"]
    assert matches[0]["left"]["record_ids"] == ["left-0", "left-1"]


def test_threshold_is_inclusive_and_adjacency_is_not_overlap():
    left = payload("left", [("s1", "c1", 0, 12)])
    right = payload("right", [("s1", "c1", 0, 3)])
    assert measure(build_benchmark_report(left, right), "iou_0_25")["matched_spans"] == 1
    right = payload("right", [("s1", "c1", 12, 15)])
    assert all(
        item["matched_spans"] == 0
        for item in build_benchmark_report(left, right)["summary"].values()
    )


def test_incompatible_cohort_codebook_and_invalid_offsets_fail_closed():
    left = payload("left", [("s1", "c1", 0, 10)])
    right = payload("right", [("s1", "c1", 0, 10)])
    with pytest.raises(ValueError, match="same transcript"):
        build_benchmark_report(left, dict(right, sources={"s1": "changed", "s2": "def"}))
    other = copy.deepcopy(right)
    other["codebook"]["codes"][0]["label"] = "Changed meaning"
    with pytest.raises(ValueError, match="same frozen codebook"):
        build_benchmark_report(left, other)
    with pytest.raises(ValueError, match="distinct runs"):
        build_benchmark_report(left, left)
    for start, end in [(-1, 10), (10, 10), (True, 10), (0, 2.5)]:
        other = copy.deepcopy(right)
        other["included"][0].update(start=start, end=end)
        with pytest.raises(ValueError, match="source offsets"):
            build_benchmark_report(left, other)


def test_real_engine_payload_contract_and_v1_reports_remain_usable(tmp_path):
    project, left_root, right_root, _ = runs(tmp_path)
    left = raw_coding_payload(project.parents[2], left_root)
    right = raw_coding_payload(project.parents[2], right_root)
    report = build_benchmark_report(left, right)
    assert report["kind"] == "qualframe_benchmark_report_v1"
    assert report["validity"]["left"]["unique_labelled_spans"] == 4
    assert all(item["f1_dice"] == 1 for item in report["summary"].values())
    assert len(report["by_source"]) == 2


def test_matching_cardinality_agrees_with_small_exhaustive_oracle():
    import random

    randomizer = random.Random(721)
    intervals = [(start, end) for start in range(7) for end in range(start + 1, 9)]
    for _ in range(25):
        a = randomizer.sample(intervals, 4)
        b = randomizer.sample(intervals, 4)
        left = payload("left", [("s1", "c1", start, end) for start, end in a])
        right = payload("right", [("s1", "c1", start, end) for start, end in b])
        report = build_benchmark_report(left, right)
        for metric, threshold in [
            ("exact", 1),
            ("iou_0_25", 0.25),
            ("iou_0_50", 0.5),
            ("iou_0_75", 0.75),
        ]:
            edges = []
            for start, end in a:
                eligible = []
                for index, (other_start, other_end) in enumerate(b):
                    overlap = max(0, min(end, other_end) - max(start, other_start))
                    union = end - start + other_end - other_start - overlap
                    if overlap / union >= threshold:
                        eligible.append(index)
                edges.append(eligible)

            def brute_force(index, used, graph=edges):
                if index == len(graph):
                    return 0
                choices = [brute_force(index + 1, used)]
                choices.extend(
                    1 + brute_force(index + 1, used | {other})
                    for other in graph[index]
                    if other not in used
                )
                return max(choices)

            assert measure(report, metric)["matched_spans"] == brute_force(0, set())


def test_macro_is_unweighted_across_defined_codes_and_pooled_uses_counts():
    common = [("s1", "c1", 0, 2), ("s1", "c1", 4, 6), ("s2", "c1", 0, 2)]
    left = payload("left", common + [("s1", "c2", 8, 10)])
    right = payload("right", common)
    report = build_benchmark_report(left, right)
    assert measure(report)["f1_dice"] == pytest.approx(6 / 7)
    assert report["macro_by_code"]["exact"] == dict(
        mean_f1_dice=0.5, defined_codes=2, undefined_codes=0
    )


def test_duplicate_catalog_entries_do_not_double_match_counts_or_support():
    left = payload("left", [("s1", "c1", 0, 10)])
    right = payload("right", [("s1", "c1", 0, 10)])
    for item in (left, right):
        item["codebook"]["codes"].append(copy.deepcopy(item["codebook"]["codes"][0]))
    report = build_benchmark_report(left, right)
    assert len(report["inputs"]["left"]["codebook"]["codes"]) == 3
    assert len(report["by_code"]) == 2
    assert measure(report)["matched_spans"] == measure(report)["left_spans"] == 1
    assert measure(report)["f1_dice"] == 1
    diagnostics = report["codebook_diagnostics"]
    assert diagnostics["duplicate_code_id_count"] == diagnostics["duplicate_catalog_entries"] == 1
    assert diagnostics["duplicate_ids"][0]["labels"] == ["Code 1"]
    assert diagnostics["ambiguous_code_ids"] == []


def test_ambiguous_duplicate_catalog_id_has_one_empty_row_and_blocks_included_spans():
    left = payload("left", [("s1", "c1", 0, 10)])
    right = payload("right", [("s1", "c1", 0, 10)])
    for item in (left, right):
        item["codebook"]["codes"][1]["definition"] = "First meaning"
        item["codebook"]["codes"].append(dict(id="c2", label="Code 2", definition="Other meaning"))
        item["excluded"].append(
            dict(record_id="ambiguous-note", code_id="c2", issues=["Ambiguous duplicate code ID"])
        )
    report = build_benchmark_report(left, right)
    assert report["codebook_diagnostics"]["ambiguous_code_ids"] == ["c2"]
    ambiguous = [row for row in report["by_code"] if row["code_id"] == "c2"]
    assert len(ambiguous) == 1 and ambiguous[0]["ambiguous_code_id"] is True
    assert ambiguous[0]["left_spans"] == ambiguous[0]["right_spans"] == 0
    assert all(value["f1_dice"] is None for value in ambiguous[0]["measures"].values())
    assert measure(report)["matched_spans"] == 1
    assert report["macro_by_code"]["exact"]["undefined_codes"] == 1
    right["included"][0]["code_id"] = "c2"
    with pytest.raises(ValueError, match="ambiguous duplicate code ID"):
        build_benchmark_report(left, right)


def test_graph_matching_uses_augmenting_path_and_does_not_mutate_edges():
    from qualframe.benchmark_metrics import _maximum_matching_indices

    # The first left node must move to R1 so the second can take its only edge, R0.
    adjacent = [[0, 1], [0]]
    original = copy.deepcopy(adjacent)
    assert _maximum_matching_indices(adjacent) == [(0, 1), (1, 0)]
    assert adjacent == original


@pytest.mark.parametrize("adjacent", [[], [[], []]])
def test_graph_matching_handles_empty_graphs(adjacent):
    from qualframe.benchmark_metrics import _maximum_matching_indices

    assert _maximum_matching_indices(adjacent) == []


def test_graph_matching_preserves_one_to_one_node_identity():
    from qualframe.benchmark_metrics import _maximum_matching_indices

    # Duplicate alternative edges and multiple proposals cannot count R0 twice.
    assert _maximum_matching_indices([[0, 0], [0]]) == [(0, 0)]
    # Each node can be used once even when every pairing is eligible.
    matches = _maximum_matching_indices([[0, 1], [0, 1], [0, 1]])
    assert matches == [(0, 0), (1, 1)]
    assert len({left for left, _ in matches}) == len({right for _, right in matches}) == 2
