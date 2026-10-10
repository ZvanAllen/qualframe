"""Symmetric, opt-in archival quotation policy for preserved raw model outputs."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from qualframe.archival_reference import ANCHOR_POLICY, _normalized, strict_quote_candidates
from qualframe.benchmark_quote_sensitivity import (
    _QUOTE_ONLY_ISSUES, _quote_text, _validate_records, _verified_sources,
)
from qualframe.reviewed_analysis import snapshot_identity


def align_model_quotes_for_archive(payload: dict, source_texts: dict[str, str]) -> dict:
    """Return a separate input under the archive's exact/typographic policy.

    Recheck included quotes and consider only specifically recognized quote-only
    exclusions for promotion. Unknown codes, altered words, case changes and
    other validation issues remain excluded. No source or review state changes.
    """
    if payload.get("kind") != "qualframe_raw_comparison_input_v1":
        raise ValueError("Select an original raw benchmark input.")
    provenance=payload.get("benchmark_provenance", {})
    if provenance.get("quote_anchoring_policy") or provenance.get("quote_anchoring_sensitivity"):
        raise ValueError("Align an original input once; retain any previous sensitivity separately.")
    hashes=_verified_sources(payload, source_texts)
    known=_validate_records(payload, source_texts)
    original_id=snapshot_identity(payload)
    result=deepcopy(payload)
    normalized={source:_normalized(text) for source,text in source_texts.items()}
    included,excluded,audit=[],[],[]
    for group in ("included","excluded"):
        for original in payload[group]:
            item=deepcopy(original)
            quote=item.get("proposed_quotation")
            issues=item.get("issues")
            can_recheck=group=="included" or (
                item.get("code_id") in known
                and item.get("anchoring_method")=="unresolved_exact_quote"
                and isinstance(issues,list)
                and all(isinstance(x,str) for x in issues)
                and set(issues)==_QUOTE_ONLY_ISSUES
            )
            if not can_recheck:
                excluded.append(item)
                audit.append(dict(record_id=item["record_id"], original_group=group,
                    outcome="other_issue_retained", original_record_sha256=snapshot_identity(original)))
                continue
            if not isinstance(quote,str):
                raise ValueError("An anchor-eligible model record is missing its original quotation.")
            body=_quote_text(quote)
            method,spans=strict_quote_candidates(source_texts[item["source"]],body,
                normalized_source=normalized[item["source"]])
            if len(spans)==1:
                start,end=spans[0]
                item.pop("issues",None)
                item.update(start=start,end=end,exact_text=source_texts[item["source"]][start:end],
                    anchoring_method=method)
                included.append(item)
                outcome="revalidated_included" if group=="included" else "recovered_quote_only_exclusion"
            else:
                item["issues"]=sorted(set(item.get("issues",[])) | {
                    "Ambiguous quotation under the common archival policy." if spans
                    else "Quotation absent under the common archival policy."})
                excluded.append(item)
                outcome="excluded_ambiguous" if spans else "excluded_unmatched"
            audit.append(dict(record_id=item["record_id"], original_group=group, outcome=outcome,
                original_record_sha256=snapshot_identity(original),
                candidate_count=len(spans),candidate_method=method))
    result["included"],result["excluded"]=included,excluded
    result["benchmark_provenance"]["quote_anchoring_policy"]=ANCHOR_POLICY
    result["benchmark_provenance"]["archival_quote_alignment"]=dict(
        version="archival_model_quote_alignment_v1",
        original_input_sha256=original_id,
        original_policy=provenance.get("normalization_version"),
        policy=ANCHOR_POLICY,source_text_hashes=hashes,
        original_included=deepcopy(payload["included"]),
        original_excluded=deepcopy(payload["excluded"]),
        original_counts={k:len(payload[k]) for k in ("included","excluded","absences")},
        derived_counts={k:len(result[k]) for k in ("included","excluded","absences")},
        outcomes=dict(Counter(x["outcome"] for x in audit)),records=audit,
        rule="Revalidate all included; recover only known-code, quote-only exclusions. No human decisions or code reassignment.",
    )
    return result
