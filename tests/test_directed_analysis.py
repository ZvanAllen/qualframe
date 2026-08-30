import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from qualframe.config import load_codebook_spec, load_method_spec
from qualframe.directed_analysis import (
    parsed_assignment_policy_issues,
    partition_codebook,
    validate_assignment_set,
    validate_evidence_span_against_source,
)
from qualframe.models import (
    CodeAssignment,
    CodebookPartitionPolicy,
    CodingPolicy,
    EvidenceSpan,
    MethodSpec,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cfir_method_preserves_per_domain_partition_default() -> None:
    method = load_method_spec(
        REPO_ROOT / "config/methods/cfir_directed_content_analysis_v1.yaml"
    )

    assert method.partitioning.strategy == "per_top_level_category"
    assert method.coding.cardinality == "multi_label"
    assert method.context.before == 2
    assert method.context.after == 2
    assert method.calibration.complete_review_required is True


def test_coding_policy_rejects_multi_code_limit_for_single_label() -> None:
    with pytest.raises(ValidationError, match="at most one code"):
        CodingPolicy(cardinality="single_label", max_codes_per_unit=2)


def test_custom_partition_requires_named_groups() -> None:
    with pytest.raises(ValidationError, match="requires at least one named group"):
        CodebookPartitionPolicy(strategy="custom_groups")


def test_codebook_partition_strategies() -> None:
    codebook = load_codebook_spec(
        REPO_ROOT / "config/codebooks/example_directed_codebook_v1.yaml"
    )

    full = partition_codebook(
        codebook,
        CodebookPartitionPolicy(strategy="full_codebook"),
    )
    assert list(full) == ["all_codes"]
    assert len(full["all_codes"]) == 5

    top_level = partition_codebook(
        codebook,
        CodebookPartitionPolicy(strategy="per_top_level_category"),
    )
    assert list(top_level) == ["access", "experience"]
    assert [entry.id for entry in top_level["access"]] == [
        "access",
        "access_availability",
        "access_affordability",
    ]

    custom = partition_codebook(
        codebook,
        CodebookPartitionPolicy(
            strategy="custom_groups",
            custom_groups={"access_subset": ["access_availability", "access_affordability"]},
        ),
    )
    assert [entry.id for entry in custom["access_subset"]] == [
        "access_availability",
        "access_affordability",
    ]


def test_evidence_span_hashes_exact_text_and_keeps_context_separate() -> None:
    exact_text = "Appointments were difficult to find."
    span = EvidenceSpan(
        id="span-1",
        meaning_unit_id="unit-1",
        source_id="source-1",
        source_sha256="a" * 64,
        start_offset=20,
        end_offset=56,
        exact_text=exact_text,
        context_start_offset=0,
        context_end_offset=80,
        creation_method="model_proposed",
    )

    assert span.exact_text_sha256 == hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    assert span.context_start_offset != span.start_offset
    assert span.context_end_offset != span.end_offset


def test_evidence_span_rejects_context_that_excludes_exact_span() -> None:
    with pytest.raises(ValidationError, match="context_start_offset"):
        EvidenceSpan(
            id="span-1",
            meaning_unit_id="unit-1",
            source_id="source-1",
            source_sha256="a" * 64,
            start_offset=20,
            end_offset=30,
            exact_text="synthetic",
            context_start_offset=21,
            context_end_offset=40,
            creation_method="automatic",
        )


def test_evidence_span_validates_against_immutable_source() -> None:
    source_text = "Before. Exact synthetic evidence. After."
    exact_text = "Exact synthetic evidence."
    start = source_text.index(exact_text)
    span = EvidenceSpan(
        id="span-source-1",
        meaning_unit_id="unit-1",
        source_id="source-1",
        source_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        start_offset=start,
        end_offset=start + len(exact_text),
        exact_text=exact_text,
        context_start_offset=0,
        context_end_offset=len(source_text),
        creation_method="researcher_presegmented",
    )

    validate_evidence_span_against_source(span, source_text)

    wrong_offsets = span.model_copy(
        update={"start_offset": start + 1, "end_offset": start + len(exact_text) + 1}
    )
    with pytest.raises(ValueError, match="offsets do not select"):
        validate_evidence_span_against_source(wrong_offsets, source_text)


def _assignment(assignment_id: str, code_id: str) -> CodeAssignment:
    return CodeAssignment(
        id=assignment_id,
        meaning_unit_id="unit-1",
        evidence_span_id="span-1",
        codebook_id="example_directed_codebook",
        codebook_version="1.0.0",
        code_id=code_id,
        origin="model",
    )


def test_assignment_cardinality_is_configurable() -> None:
    codebook = load_codebook_spec(
        REPO_ROOT / "config/codebooks/example_directed_codebook_v1.yaml"
    )
    multi_method = load_method_spec(
        REPO_ROOT / "config/methods/directed_content_analysis_v1.yaml"
    )
    assignments = [
        _assignment("assignment-1", "access_availability"),
        _assignment("assignment-2", "access_affordability"),
    ]

    validate_assignment_set(assignments, multi_method, codebook)

    single_method = MethodSpec.model_validate(
        {
            **multi_method.model_dump(),
            "coding": {
                **multi_method.coding.model_dump(),
                "cardinality": "single_label",
                "max_codes_per_unit": 1,
            },
        }
    )
    with pytest.raises(ValueError, match="single_label"):
        validate_assignment_set(assignments, single_method, codebook)

    issues = parsed_assignment_policy_issues(
        {
            "Coding": [
                {"Meaning Unit ID": "unit-1", "Code ID": "access_availability"},
                {"Meaning Unit ID": "unit-1", "Code ID": "access_affordability"},
                {"Meaning Unit ID": "unit-2", "Code ID": "not_in_codebook"},
            ]
        },
        single_method,
        codebook,
    )
    assert any("single-label" in issue for issue in issues)
    assert any("not_in_codebook" in issue for issue in issues)
