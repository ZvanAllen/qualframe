"""Exploratory evidence retrieval against an expanded-context archival comparator."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from fractions import Fraction
from statistics import mean

from qualframe.archival_reference import (
    ORIGIN,
    SHARED_DOMAINS,
    _catalog,
    canonical_domain,
    validate_parent_projection,
)
from qualframe.benchmark_metrics import _Span, _span_sets, build_benchmark_report
from qualframe.io.files import sha256_for_text
from qualframe.reviewed_analysis import snapshot_identity
from qualframe.run_comparison import compare_raw_payloads


def _verify_sources(archive: dict, new: dict, texts: dict[str, str]) -> None:
    if archive["sources"] != new["sources"] or set(texts) != set(archive["sources"]):
        raise ValueError(
            "Archive, new output and source texts must use exactly the same frozen cohort."
        )
    mapping = archive["benchmark_provenance"]["source_mapping"]
    if snapshot_identity(mapping) != archive["benchmark_provenance"]["source_mapping_sha256"]:
        raise ValueError("Archival source mapping hash differs.")
    for entry in mapping.values():
        if sha256_for_text(texts[entry["source_id"]]) != entry["extracted_text_sha256"]:
            raise ValueError("Extracted source text differs from the archival binding.")
    new_mapping = new.get("benchmark_provenance", {}).get("source_mapping")
    if new_mapping is not None:
        if snapshot_identity(new_mapping) != new["benchmark_provenance"].get(
            "source_mapping_sha256"
        ):
            raise ValueError("New-output source mapping hash differs.")
        by_source = {entry["source_id"]: entry for entry in new_mapping.values()}
        if set(by_source) != set(texts) or len(by_source) != len(new_mapping):
            raise ValueError("New-output source mapping does not describe the comparison cohort.")
        for source, entry in by_source.items():
            if (
                entry["sha256"] != new["sources"][source]
                or sha256_for_text(texts[source]) != entry["extracted_text_sha256"]
            ):
                raise ValueError("New-output extraction or source hash differs.")


def _project(payload: dict, codebook: dict, projection: dict, texts: dict[str, str]) -> dict:
    if snapshot_identity(payload["codebook"]) != snapshot_identity(codebook):
        raise ValueError(
            "Comparison needs the same frozen original codebook; no substantive "
            "mapping is inferred."
        )
    known, duplicates = _catalog(codebook)
    parent_ids = sorted(
        {
            value
            for value in projection.values()
            if canonical_domain(known[value]["domain"]) in SHARED_DOMAINS
        }
    )
    parent_book = dict(
        id="archival-parent-projection-v1",
        original_codebook_sha256=snapshot_identity(codebook),
        projection_sha256=snapshot_identity(projection),
        domains=list(SHARED_DOMAINS),
        codes=[deepcopy(known[key]) for key in parent_ids],
    )
    result = deepcopy(payload)
    original_content_hash = result.pop("content_sha256", None)
    result.update(
        kind="qualframe_archival_parent_comparison_input_v1",
        codebook=parent_book,
        included=[],
        excluded=[],
        absences=[],
        out_of_scope=deepcopy(payload.get("out_of_scope", [])),
    )
    seen = set()
    for category in ("included", "excluded", "absences"):
        if not isinstance(payload.get(category), list):
            raise ValueError("Comparison inputs need included, excluded and absence collections.")
        for original in payload[category]:
            item = deepcopy(original)
            item["original_collection"] = category
            identifier = item.get("record_id")
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError(
                    "Proposal identities must be nonblank and unique within each input."
                )
            seen.add(identifier)
            code_id = item.get("code_id")
            code = known.get(code_id)
            if category == "included":
                start, end, source = item.get("start"), item.get("end"), item.get("source")
                if source not in texts or code_id in duplicates or code is None:
                    raise ValueError(
                        "Included spans must have unambiguous source and code identities."
                    )
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= len(texts[source])
                ):
                    raise ValueError("Included spans have invalid exclusive-end offsets.")
                if item.get("exact_text") != texts[source][start:end]:
                    raise ValueError("Included span text differs from its verified source slice.")
            domain = (
                canonical_domain(code["domain"])
                if code
                else canonical_domain(item.get("original_domain"))
            )
            item.update(original_code_id=code_id, projection_domain=domain)
            if domain == "Outcomes Addendum":
                result["out_of_scope"].append(
                    dict(item, scope_exclusions=["outside_shared_five_domain_scope"])
                )
                continue
            if code_id in projection and domain in SHARED_DOMAINS:
                item.update(
                    code_id=projection[code_id], parent_projection_policy="explicit_parent_v1"
                )
                result[category].append(item)
            else:
                item["issues"] = sorted(
                    set(item.get("issues", []) + ["unresolved_parent_projection"])
                )
                result["excluded"].append(item)
    result["benchmark_provenance"] = dict(
        result.get("benchmark_provenance", {}),
        original_payload_sha256=snapshot_identity(payload),
        original_codebook=deepcopy(codebook),
        original_kind=payload.get("kind"),
        original_content_sha256=original_content_hash,
        parent_projection=deepcopy(projection),
        parent_projection_policy="explicit_parent_v1",
        shared_domains=list(SHARED_DOMAINS),
    )
    result["content_sha256"] = snapshot_identity(result)
    return result


def _overlap(a: _Span, b: _Span) -> tuple[int, int]:
    return max(0, min(a.end, b.end) - max(a.start, b.start)), min(a.end - a.start, b.end - b.start)


def _retrieval_matches(
    left: list[_Span], right: list[_Span], threshold: float
) -> list[tuple[_Span, _Span]]:
    """Maximum-cardinality matching on same-source/parent shorter-span overlap."""
    ratio = Fraction(str(threshold))
    adjacent = []
    for a in left:
        edges = []
        for index, b in enumerate(right):
            shared, shorter = _overlap(a, b)
            if (
                a.source == b.source
                and a.code_id == b.code_id
                and shared > 0
                and shared * ratio.denominator >= shorter * ratio.numerator
            ):
                edges.append(index)
        adjacent.append(edges)
    owner, matched = {}, {}
    for initial in range(len(left)):
        queue, seen, previous = deque([initial]), {initial}, {}
        free = None
        while queue and free is None:
            a = queue.popleft()
            for b in adjacent[a]:
                if b in previous:
                    continue
                previous[b] = a
                if b not in owner:
                    free = b
                    break
                if owner[b] not in seen:
                    seen.add(owner[b])
                    queue.append(owner[b])
        if free is None:
            continue
        b = free
        while True:
            a = previous[b]
            prior = matched.get(a)
            matched[a], owner[b] = b, a
            if prior is None:
                break
            b = prior
    return [(left[a], right[b]) for a, b in sorted(matched.items())]


def _measure(
    left: list[_Span], right: list[_Span], threshold: float, *, details: bool = False
) -> dict:
    matches = _retrieval_matches(left, right, threshold)
    n, h, m = len(left), len(right), len(matches)
    result = dict(
        new_items=n,
        archival_items=h,
        matched_pairs=m,
        new_output_matched_fraction=m / n if n else None,
        archival_annotation_recovery=m / h if h else None,
        retrieval_dice=2 * m / (n + h) if n + h else None,
        unmatched_new_items=n - m,
        unrecovered_archival_items=h - m,
    )
    if details:
        left_seen, right_seen = {a for a, _ in matches}, {b for _, b in matches}
        result.update(
            matches=[
                dict(
                    new=a.reference(),
                    archival=b.reference(),
                    intersection_characters=_overlap(a, b)[0],
                    shorter_span_characters=_overlap(a, b)[1],
                    shorter_span_overlap=_overlap(a, b)[0] / _overlap(a, b)[1],
                )
                for a, b in matches
            ],
            unmatched_new=[a.reference() for a in left if a not in left_seen],
            unrecovered_archival=[b.reference() for b in right if b not in right_seen],
        )
    return result


def _counts(payload: dict, spans: list[_Span]) -> dict:
    included, excluded = len(payload["included"]), len(payload["excluded"])
    return dict(
        included_entries=included,
        excluded_entries=excluded,
        eligibility_denominator=included + excluded,
        eligible_fraction=included / (included + excluded) if included + excluded else None,
        unique_parent_spans=len(spans),
        duplicate_entries=included - len(spans),
        absence_declarations=len(payload["absences"]),
        out_of_scope_entries=len(payload["out_of_scope"]),
        inventory_entries=included
        + excluded
        + len(payload["absences"])
        + len(payload["out_of_scope"]),
    )


def compare_archival_reference(
    new_payload: dict,
    archive_payload: dict,
    *,
    source_texts: dict[str, str],
    minimum_shorter_span_overlap: float = 0.50,
    include_boundary_sensitivity: bool = False,
    allow_asymmetric_anchoring: bool = False,
) -> dict:
    """Return a distinct exploratory report, preserving both inputs and all exclusions.

    Primary retrieval is intersection/min(span lengths), with one-to-one matches.
    Expanded context can contain a shorter quote while IoU is low. Neither rule
    establishes construct correctness or the original historical coded boundaries.
    """
    if (
        type(minimum_shorter_span_overlap) not in (int, float)
        or not 0 < minimum_shorter_span_overlap <= 1
    ):
        raise ValueError(
            "Exploratory retrieval threshold must be greater than zero and at most one."
        )
    if (
        archive_payload.get("kind") != "qualframe_archival_reference_v1"
        or archive_payload.get("origin") != ORIGIN
    ):
        raise ValueError("Use a verified archival-reference import.")
    if snapshot_identity(
        {k: v for k, v in archive_payload.items() if k != "content_sha256"}
    ) != archive_payload.get("content_sha256"):
        raise ValueError("Archival import content hash differs; reload its frozen manifest.")
    archive_policy = archive_payload["benchmark_provenance"]["quote_anchoring_policy"]
    new_policy = new_payload.get("benchmark_provenance", {}).get("quote_anchoring_policy")
    common_policy = new_policy == archive_policy
    if not common_policy and not allow_asymmetric_anchoring:
        raise ValueError(
            "Quotation anchoring policies differ or are unspecified. Rebuild the "
            "new input under the declared archival policy, or explicitly request "
            "an asymmetric-policy sensitivity."
        )
    _verify_sources(archive_payload, new_payload, source_texts)
    codebook, projection = archive_payload["codebook"], archive_payload["parent_projection"]
    validate_parent_projection(codebook, projection)
    new = _project(new_payload, codebook, projection, source_texts)
    archive = _project(archive_payload, codebook, projection, source_texts)
    compare_raw_payloads(new, archive)  # Reuse cohort/study/codebook compatibility validation.
    left, right = _span_sets(new, set()), _span_sets(archive, set())
    thresholds = sorted({0.25, 0.50, 0.75, float(minimum_shorter_span_overlap)})
    by_source = []
    for source in sorted(new["sources"]):
        a, b = [v for v in left if v.source == source], [v for v in right if v.source == source]
        by_source.append(dict(source=source, **_measure(a, b, minimum_shorter_span_overlap)))
    by_parent = []
    for code in new["codebook"]["codes"]:
        a, b = (
            [v for v in left if v.code_id == code["id"]],
            [v for v in right if v.code_id == code["id"]],
        )
        by_parent.append(
            dict(
                code_id=code["id"],
                label=code["label"],
                domain=code["domain"],
                **_measure(a, b, minimum_shorter_span_overlap),
            )
        )
    source_scores = [
        row["retrieval_dice"] for row in by_source if row["retrieval_dice"] is not None
    ]
    result = dict(
        kind="qualframe_archival_comparison_v1",
        origin=ORIGIN,
        interpretation=(
            "Exploratory recovery of retained expanded-context archival evidence;"
            " not independent human accuracy, semantic validity or coded-boundary"
            " accuracy."
        ),
        policy=dict(
            id="archival_shorter_span_retrieval_v1",
            primary_threshold=minimum_shorter_span_overlap,
            comparison_status="common_declared_anchoring_policy"
            if common_policy
            else "asymmetric_anchoring_sensitivity_only",
            common_declared_anchoring_policy=common_policy,
            anchoring_policy_limit=(
                "The caller must reconstruct and audit new-input eligibility from "
                "original quotations; changing a policy label alone is not a policy "
                "conversion."
            )
            if common_policy
            else (
                "Eligibility rules differ or are unspecified; this sensitivity cannot"
                " be reported as a common-policy primary comparison."
            ),
            threshold_status="prespecified exploratory convention, not a validated CFIR threshold",
            edge_rule=(
                "same source and projected parent; intersection / shorter span length >= threshold"
            ),
            matching=(
                "maximum-cardinality one-to-one; duplicates collapse within each selected layer"
            ),
            shared_domains=list(SHARED_DOMAINS),
            archival_layer=archive_payload["layer"],
            quote_anchoring_policy=archive_policy,
            new_output_quote_anchoring_policy=new_policy,
            empty_policy="zero denominator is null; both-empty Dice null; one-empty Dice zero",
            context_limit=(
                "A match can concern surrounding context rather than the original "
                "coded focus; broad quotations can increase retrieval."
            ),
            reference_scope=(
                "finite selected eligible archival set; no exhaustive source-coding "
                "or reviewed-negative claim"
            ),
        ),
        input_hashes=dict(
            new=snapshot_identity(new_payload), archival=archive_payload["content_sha256"]
        ),
        new_output=new,
        archival_reference=archive,
        eligibility=dict(new=_counts(new, left), archival=_counts(archive, right)),
        primary=_measure(left, right, minimum_shorter_span_overlap, details=True),
        threshold_sensitivities={
            (f"{value:.2f}" if round(value, 2) == value else str(value)): _measure(
                left, right, value
            )
            for value in thresholds
        },
        sources=by_source,
        parents=by_parent,
        equal_weight_source_summary=dict(
            defined_sources=len(source_scores),
            total_sources=len(by_source),
            mean_retrieval_dice=mean(source_scores) if source_scores else None,
            uncertainty="descriptive only; spans/repeats/groups are not independent observations",
        ),
    )
    if include_boundary_sensitivity:
        result["boundary_sensitivity"] = dict(
            interpretation=(
                "Raw exact/IoU overlap sensitivity on projected parent spans with "
                "different context lengths; not original-boundary accuracy."
            ),
            report=build_benchmark_report(new, archive),
        )
    result["report_id"] = snapshot_identity(result)
    return result
