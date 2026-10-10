"""Opt-in casefold-only sensitivity for frozen historical benchmark inputs.

This pure transformation never changes default CFIR review, original payloads,
source text, or model quotations. It requires extracted source text keyed by the
canonical source IDs in ``benchmark_provenance.source_mapping``. Its output is a
separate benchmark input whose provenance changes the resulting report identity.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from copy import deepcopy

from qualframe.cfir_review import locate_quote, normalized_with_offsets
from qualframe.io.files import sha256_for_text
from qualframe.reviewed_analysis import snapshot_identity

CASEFOLD_POLICY = "unique_casefold_quote_sensitivity_v1"
_QUOTE_ONLY_ISSUES = {
    "Select the evidence in the transcript; the quotation is missing or ambiguous.",
    "Missing source span",
}


def _verified_sources(payload: dict, source_texts: dict[str, str]) -> dict[str, str]:
    provenance = payload.get("benchmark_provenance", {})
    mapping = provenance.get("source_mapping")
    sources = payload.get("sources")
    if not isinstance(mapping, dict) or not mapping or not isinstance(sources, dict):
        raise ValueError("Casefold sensitivity requires the frozen benchmark source mapping.")
    if snapshot_identity(mapping) != provenance.get("source_mapping_sha256"):
        raise ValueError("Frozen benchmark source mapping hash differs.")
    if set(source_texts) != set(sources):
        raise ValueError("Supply extracted text for exactly the canonical benchmark sources.")
    hashes = {}
    for entry in mapping.values():
        if not isinstance(entry, dict):
            raise ValueError("Frozen benchmark source mapping entry is invalid.")
        required = {"source_id", "original_path", "sha256", "extracted_text_sha256"}
        if not required <= entry.keys() or any(
            not isinstance(entry[key], str) or not entry[key] for key in required
        ):
            raise ValueError("Frozen benchmark source mapping entry is incomplete.")
        source_id = entry["source_id"]
        identity = (
            "benchmark-source-"
            + snapshot_identity(
                {"original_path": entry["original_path"], "sha256": entry["sha256"]}
            )[:24]
        )
        if (
            identity != source_id
            or source_id in hashes
            or source_id not in sources
            or sources[source_id] != entry["sha256"]
        ):
            raise ValueError("Frozen benchmark source identity or file hash differs.")
        text = source_texts[source_id]
        if not isinstance(text, str) or sha256_for_text(text) != entry["extracted_text_sha256"]:
            raise ValueError("Extracted source text hash differs from the frozen benchmark.")
        hashes[source_id] = entry["extracted_text_sha256"]
    if set(hashes) != set(sources):
        raise ValueError("Frozen mapping must cover each canonical benchmark source once.")
    return hashes


def _validate_records(payload: dict, source_texts: dict[str, str]) -> set[str]:
    codes = payload.get("codebook", {}).get("codes", [])
    if not codes or any(
        not isinstance(code, dict) or not isinstance(code.get("id"), str) or not code["id"]
        for code in codes
    ):
        raise ValueError("Sensitivity requires the original codebook and nonblank code IDs.")
    counts = Counter(code["id"] for code in codes)
    # Even identical duplicate catalog IDs stay excluded, as in the historical adapter.
    known = {identifier for identifier, count in counts.items() if count == 1}
    seen = set()
    for group in ("included", "excluded", "absences"):
        if not isinstance(payload.get(group), list):
            raise ValueError("Benchmark proposal collections must be lists.")
        for item in payload[group]:
            if not isinstance(item, dict):
                raise ValueError("Benchmark proposals must be records.")
            identifier = item.get("record_id")
            if not isinstance(identifier, str) or not identifier or identifier in seen:
                raise ValueError("Benchmark proposal IDs must be nonblank and unique.")
            seen.add(identifier)
            if item.get("source") not in source_texts:
                raise ValueError("Benchmark proposal source is outside the frozen cohort.")
            if group == "included":
                start, end = item.get("start"), item.get("end")
                text = source_texts[item["source"]]
                if (
                    item.get("code_id") not in known
                    or type(start) is not int
                    or type(end) is not int
                    or start < 0
                    or end <= start
                    or end > len(text)
                    or text[start:end] != item.get("exact_text")
                ):
                    raise ValueError("Original included span/code fails source validation.")
    return known


def _folded_source(source: str) -> tuple[str, list[tuple[int, int]]]:
    normalized, offsets = normalized_with_offsets(source)
    folded, folded_offsets = [], []
    for char, offset in zip(normalized, offsets, strict=True):
        for value in char.casefold():
            folded.append(value)
            folded_offsets.append(offset)
    return "".join(folded), folded_offsets


def _quote_text(quote: str) -> str:
    # Exactly the existing locate_quote wrapper rule: one balanced double-quote pair.
    quote = quote.strip()
    if len(quote) > 1 and (quote[0], quote[-1]) in [('"', '"'), ("“", "”")]:
        quote = quote[1:-1]
    return quote


def _candidate(
    source: str, quote: str, folded: str, offsets: list[tuple[int, int]]
) -> tuple[str, tuple[int, int] | None]:
    needle = normalized_with_offsets(_quote_text(quote))[0].casefold()
    if not needle.strip():
        return "empty_quotation", None
    if locate_quote(source, quote)[2] != "unresolved_exact_quote":
        return "already_strictly_anchorable", None
    start = folded.find(needle)
    if start < 0:
        return "no_casefold_match", None
    if folded.find(needle, start + 1) >= 0:
        return "ambiguous_casefold_matches", None
    low, high = offsets[start][0], offsets[start + len(needle) - 1][1]
    # A match may start/end inside a Unicode casefold expansion. Reject it unless
    # the complete original source slice folds back to exactly the whole quote.
    if normalized_with_offsets(source[low:high])[0].casefold() != needle:
        return "source_slice_roundtrip_mismatch", None
    return "recovered_casefold_only", (low, high)


def casefold_quote_sensitivity(payload: dict, source_texts: dict[str, str]) -> dict:
    """Return a separate casefold-only benchmark input; perform no IO or review.

    Hash/identity failures raise. Ambiguous matches, mismatched reverse slices,
    unresolved codes, and other blocking issues remain excluded with audit outcomes.
    Casefold is added to the existing whitespace/quote-typography normalization;
    punctuation, words, and code labels are never removed, inferred, or rewritten.
    """
    if payload.get("kind") != "qualframe_raw_comparison_input_v1":
        raise ValueError("Casefold sensitivity requires a raw benchmark input.")
    provenance = payload.get("benchmark_provenance", {})
    if provenance.get("quote_anchoring_sensitivity") or provenance.get("quote_anchoring_policy"):
        raise ValueError("Apply casefold sensitivity once to an original strict input.")
    hashes = _verified_sources(payload, source_texts)
    known = _validate_records(payload, source_texts)
    result = deepcopy(payload)
    folded = {key: _folded_source(text) for key, text in source_texts.items()}
    audit, retained = [], []
    for item in result["excluded"]:
        issues = item.get("issues")
        quote = item.get("proposed_quotation")
        span = None
        if item.get("code_id") not in known:
            outcome = "unresolved_or_duplicate_code"
        elif item.get("anchoring_method") != "unresolved_exact_quote":
            outcome = "not_an_unresolved_quote_proposal"
        elif (
            not isinstance(issues, list)
            or any(not isinstance(issue, str) for issue in issues)
            or set(issues) != _QUOTE_ONLY_ISSUES
        ):
            outcome = "other_or_unrecognized_blocking_issues"
        elif not isinstance(quote, str):
            outcome = "missing_quotation"
        else:
            source = item["source"]
            outcome, span = _candidate(source_texts[source], quote, *folded[source])
        attempt = dict(
            record_id=item["record_id"],
            source=item["source"],
            code_id=item.get("code_id"),
            original_exclusion_sha256=snapshot_identity(item),
            original_anchoring_method=item.get("anchoring_method"),
            strict_issues=deepcopy(issues),
            outcome=outcome,
        )
        if span is not None:
            low, high = span
            exact_text = source_texts[item["source"]][low:high]
            attempt.update(
                start=low,
                end=high,
                proposed_quotation_sha256=sha256_for_text(quote),
                source_text_sha256=hashes[item["source"]],
                selected_source_text_sha256=sha256_for_text(exact_text),
            )
            recovered = deepcopy(item)
            recovered.pop("issues")
            recovered.update(
                start=low,
                end=high,
                exact_text=exact_text,
                anchoring_method=CASEFOLD_POLICY,
                quote_anchoring_sensitivity=dict(policy=CASEFOLD_POLICY, **deepcopy(attempt)),
            )
            result["included"].append(recovered)
        else:
            retained.append(item)
        audit.append(attempt)
    result["excluded"] = retained
    sensitivity = dict(
        policy=CASEFOLD_POLICY,
        original_strict_input_sha256=snapshot_identity(payload),
        original_normalization_version=provenance.get("normalization_version"),
        unicode_version=unicodedata.unidata_version,
        source_text_sha256s=hashes,
        strict_counts={key: len(payload[key]) for key in ("included", "excluded", "absences")},
        sensitivity_counts={key: len(result[key]) for key in ("included", "excluded", "absences")},
        outcome_counts=dict(sorted(Counter(item["outcome"] for item in audit).items())),
        attempts=audit,
        interpretation=(
            "Opt-in source-anchoring sensitivity: unique casefold matches after the "
            "existing whitespace/quote-typography normalization, with source-slice "
            "roundtrip validation. Original quotations and strict exclusions are "
            "retained in the audit. No human adjudication, semantic validation, "
            "punctuation removal, word matching, or code-label repair is implied."
        ),
    )
    result["benchmark_provenance"].update(
        normalization_version="historical_cfir_benchmark_casefold_quotes_v1",
        quote_anchoring_policy=CASEFOLD_POLICY,
        quote_anchoring_sensitivity=sensitivity,
        normalization_policy=(
            str(provenance.get("normalization_policy", ""))
            + "; opt-in unique casefold-only quote anchoring with source-slice validation"
        ),
    )
    return result
