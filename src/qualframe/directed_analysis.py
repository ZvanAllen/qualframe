from __future__ import annotations

import hashlib
from collections import defaultdict

from qualframe.models import (
    CodeAssignment,
    CodebookEntry,
    CodebookPartitionPolicy,
    CodebookSpec,
    EvidenceSpan,
    MethodSpec,
)


def validate_evidence_span_against_source(span: EvidenceSpan, source_text: str) -> None:
    """Confirm that a span's source hash, offsets, and exact text agree."""
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if span.source_sha256 != source_hash:
        raise ValueError(f"evidence span '{span.id}' source_sha256 does not match source text")
    if span.end_offset > len(source_text):
        raise ValueError(f"evidence span '{span.id}' ends beyond the source text")
    if source_text[span.start_offset:span.end_offset] != span.exact_text:
        raise ValueError(f"evidence span '{span.id}' offsets do not select exact_text")
    if span.context_end_offset is not None and span.context_end_offset > len(source_text):
        raise ValueError(f"evidence span '{span.id}' context ends beyond the source text")


def partition_codebook(
    codebook: CodebookSpec,
    policy: CodebookPartitionPolicy,
) -> dict[str, list[CodebookEntry]]:
    """Return deterministic code groups for a configured model-call strategy."""
    entries_by_id = {entry.id: entry for entry in codebook.codes}
    active_entries = [entry for entry in codebook.codes if entry.active]

    if policy.strategy == "full_codebook":
        return {"all_codes": active_entries}

    if policy.strategy == "custom_groups":
        groups: dict[str, list[CodebookEntry]] = {}
        for group_name, code_ids in policy.custom_groups.items():
            missing = [code_id for code_id in code_ids if code_id not in entries_by_id]
            if missing:
                raise ValueError(
                    f"custom group '{group_name}' references unknown code ids: {', '.join(missing)}"
                )
            inactive = [code_id for code_id in code_ids if not entries_by_id[code_id].active]
            if inactive:
                raise ValueError(
                    f"custom group '{group_name}' references inactive code ids: {', '.join(inactive)}"
                )
            groups[group_name] = [entries_by_id[code_id] for code_id in code_ids]
        return groups

    children: dict[str | None, list[CodebookEntry]] = defaultdict(list)
    for entry in codebook.codes:
        children[entry.parent_id].append(entry)

    def active_descendants(root: CodebookEntry) -> list[CodebookEntry]:
        result: list[CodebookEntry] = []

        def visit(entry: CodebookEntry) -> None:
            if entry.active:
                result.append(entry)
            for child in children.get(entry.id, []):
                visit(child)

        visit(root)
        return result

    groups: dict[str, list[CodebookEntry]] = {}
    for root in children.get(None, []):
        entries = active_descendants(root)
        if entries:
            groups[root.id] = entries
    if not groups:
        raise ValueError("per_top_level_category partitioning requires at least one root code")
    return groups


def validate_assignment_set(
    assignments: list[CodeAssignment],
    method: MethodSpec,
    codebook: CodebookSpec,
) -> None:
    """Validate code membership, duplicates, and per-meaning-unit cardinality."""
    active_code_ids = {entry.id for entry in codebook.codes if entry.active}
    grouped: dict[str, list[CodeAssignment]] = defaultdict(list)

    for assignment in assignments:
        if assignment.codebook_id != codebook.id or assignment.codebook_version != codebook.version:
            raise ValueError(
                f"assignment '{assignment.id}' does not reference codebook "
                f"{codebook.id}@{codebook.version}"
            )
        if assignment.code_id not in active_code_ids:
            raise ValueError(
                f"assignment '{assignment.id}' references unknown or inactive code '{assignment.code_id}'"
            )
        grouped[assignment.meaning_unit_id].append(assignment)

    for meaning_unit_id, unit_assignments in grouped.items():
        code_ids = [assignment.code_id for assignment in unit_assignments]
        if len(code_ids) != len(set(code_ids)):
            raise ValueError(f"meaning unit '{meaning_unit_id}' has duplicate code assignments")
        if method.coding.cardinality == "single_label" and len(code_ids) > 1:
            raise ValueError(f"meaning unit '{meaning_unit_id}' exceeds single_label cardinality")
        max_codes = method.coding.max_codes_per_unit
        if max_codes is not None and len(code_ids) > max_codes:
            raise ValueError(
                f"meaning unit '{meaning_unit_id}' has {len(code_ids)} codes; maximum is {max_codes}"
            )


def parsed_assignment_policy_issues(
    parsed_output: dict[str, list[dict[str, str]]],
    method: MethodSpec,
    codebook: CodebookSpec,
) -> list[str]:
    """Return policy issues from the generic directed-coding table contract."""
    active_code_ids = {entry.id for entry in codebook.codes if entry.active}
    grouped: dict[str, list[str]] = defaultdict(list)
    issues: list[str] = []
    for rows in parsed_output.values():
        for row in rows:
            meaning_unit_id = str(row.get("Meaning Unit ID", "")).strip()
            code_id = str(row.get("Code ID", "")).strip()
            if not meaning_unit_id or not code_id:
                continue
            if code_id not in active_code_ids:
                issues.append(f"unknown or inactive code '{code_id}'")
            grouped[meaning_unit_id].append(code_id)
    for meaning_unit_id, code_ids in grouped.items():
        unique_codes = set(code_ids)
        if len(code_ids) != len(unique_codes):
            issues.append(f"meaning unit '{meaning_unit_id}' has duplicate code assignments")
        if method.coding.cardinality == "single_label" and len(unique_codes) > 1:
            issues.append(f"meaning unit '{meaning_unit_id}' exceeds single-label coding")
        maximum = method.coding.max_codes_per_unit
        if maximum is not None and len(unique_codes) > maximum:
            issues.append(
                f"meaning unit '{meaning_unit_id}' has {len(unique_codes)} codes; maximum is {maximum}"
            )
    return sorted(set(issues))
