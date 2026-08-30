from __future__ import annotations

import json
from pathlib import Path

import pytest

from qualframe.cost_control import (
    CostApprovalRequired,
    CostController,
    CostLimitExceeded,
    append_cost_approval,
    calculate_cost_usd,
)
from qualframe.models import CostPolicySpec, ModelPricing, PricingSnapshotSpec
from qualframe.providers.base import LLMResponse, LLMUsage


def pricing() -> ModelPricing:
    return ModelPricing(
        provider="mock",
        model="priced-mock",
        input_per_million_usd=2,
        cached_input_per_million_usd=0.5,
        cache_write_per_million_usd=2.5,
        output_per_million_usd=8,
        reasoning_per_million_usd=10,
    )


def controller(
    tmp_path: Path,
    *,
    max_output_tokens: int = 25,
    absolute_limit_usd: float = 100,
) -> CostController:
    # An intentionally high fixture rate makes boundary tests tiny and deterministic.
    snapshot = PricingSnapshotSpec(
        id="test-pricing",
        version="1.0.0",
        effective_date="2026-08-02",
        models=[
            ModelPricing(
                provider="mock",
                model="priced-mock",
                input_per_million_usd=0,
                output_per_million_usd=1_000_000,
            )
        ],
    )
    policy = CostPolicySpec(
        id="test-policy",
        version="1.0.0",
        approval_increment_usd=20,
        absolute_limit_usd=absolute_limit_usd,
        notification_adapter="none",
    )
    return CostController(
        project_id="project-1",
        run_id="run-1",
        artifact_root=tmp_path / "artifacts" / "run-1",
        logs_root=tmp_path / "logs",
        policy=policy,
        pricing_snapshot=snapshot,
        provider="mock",
        model="priced-mock",
        max_output_tokens=max_output_tokens,
    )


def test_calculate_cost_uses_distinct_usage_classes() -> None:
    usage = LLMUsage(
        input_tokens=1_000,
        cached_input_tokens=2_000,
        cache_write_tokens=3_000,
        output_tokens=4_000,
        reasoning_tokens=5_000,
    )

    assert calculate_cost_usd(usage, pricing()) == 0.0925


def test_preflight_pauses_before_unapproved_threshold(tmp_path: Path) -> None:
    cost = controller(tmp_path)

    with pytest.raises(CostApprovalRequired) as caught:
        cost.preflight(
            stage_id="coding",
            input_label="synthetic-01",
            system_prompt="system",
            user_prompt="fixture",
        )

    assert caught.value.pause.threshold_usd == 20
    assert caught.value.pause.projected_cost_usd == 25
    assert caught.value.path.exists()
    assert caught.value.pause.notification_status == "not_configured"


def test_local_approval_allows_crossing_one_interval(tmp_path: Path) -> None:
    cost = controller(tmp_path)
    with pytest.raises(CostApprovalRequired):
        cost.preflight(
            stage_id="coding",
            input_label="synthetic-01",
            system_prompt="system",
            user_prompt="fixture",
        )
    append_cost_approval(
        cost.approvals_path,
        project_id="project-1",
        run_id="run-1",
        threshold_usd=20,
        decision="approve",
        reviewer="researcher",
        rationale="Approved bounded synthetic test.",
    )

    request_id, estimate = cost.preflight(
        stage_id="coding",
        input_label="synthetic-01",
        system_prompt="system",
        user_prompt="fixture",
    )

    assert request_id.startswith("request-")
    assert estimate == 25


def test_absolute_limit_fails_before_approval_check(tmp_path: Path) -> None:
    cost = controller(tmp_path, max_output_tokens=26, absolute_limit_usd=25)

    with pytest.raises(CostLimitExceeded, match="no request was sent"):
        cost.preflight(
            stage_id="coding",
            input_label="synthetic-01",
            system_prompt="system",
            user_prompt="fixture",
        )


def test_response_usage_is_appended_to_project_ledger(tmp_path: Path) -> None:
    cost = controller(tmp_path, max_output_tokens=10)
    request_id, estimate = cost.preflight(
        stage_id="coding",
        input_label="synthetic-01",
        system_prompt="system",
        user_prompt="fixture",
    )
    response = LLMResponse(
        text="result",
        provider="mock",
        model="priced-mock",
        response_id="provider-response-1",
        usage=LLMUsage(input_tokens=2, output_tokens=3),
    )

    record = cost.record_response(
        request_id=request_id,
        estimated_cost_usd=estimate,
        stage_id="coding",
        input_label="synthetic-01",
        system_prompt="system",
        user_prompt="fixture",
        response=response,
    )

    raw = json.loads(cost.ledger_path.read_text(encoding="utf-8").strip())
    assert record.calculated_cost_usd == 3
    assert raw["request_id"] == request_id
    assert raw["response_id"] == "provider-response-1"
    assert raw["pricing_snapshot_id"] == "test-pricing"
    assert cost.project_cost_usd() == 3
    assert cost.run_cost_usd() == 3
