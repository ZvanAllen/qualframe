"""Synthetic tests for explicit unresolved-request budget holds; no provider calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_cost_control import controller

from qualframe.cost_control import (
    CostApprovalRequired,
    CostController,
    CostLimitExceeded,
    UnresolvedRequest,
)
from qualframe.providers.base import LLMResponse, LLMUsage

PREFLIGHT = dict(
    stage_id="coding", input_label="synthetic-source", system_prompt="system", user_prompt="fixture"
)
HOLD = dict(
    recorded_by="Synthetic reviewer",
    rationale="Synthetic transport ambiguity remains unresolved.",
    bound_evidence_reference="fixture://documented-maximum-charge",
    resume_authorization="Explicit synthetic recovery authorization",
)


def restart(cost: CostController, *, allow: bool = False) -> CostController:
    return CostController(
        project_id=cost.project_id,
        run_id=cost.run_id,
        artifact_root=cost.artifact_root,
        logs_root=cost.ledger_path.parent,
        policy=cost.policy,
        pricing_snapshot=cost.snapshot,
        provider=cost.provider,
        model=cost.model,
        max_output_tokens=cost.max_output_tokens,
        allow_budget_holds=allow,
    )


def reserved(tmp_path: Path, *, maximum: float = 100):
    cost = controller(tmp_path, max_output_tokens=5, absolute_limit_usd=maximum)
    request, allowance = cost.preflight(**PREFLIGHT)
    assert allowance == 5
    return cost, request


def save_hold(cost, request, amount=9):
    return cost.hold_unresolved_request(
        request_id=request, reserved_usd=amount, **HOLD, dry_run=False
    )


def rows(path):
    return (
        [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if path.exists()
        else []
    )


def reconcile(cost, request, tokens):
    return cost.reconcile_request(
        request_id=request,
        usage=LLMUsage(output_tokens=tokens),
        reviewer="Synthetic reviewer",
        rationale="Provider-confirmed fixture usage",
        evidence_reference="fixture://actual-usage",
    )


def test_hold_preview_is_read_only_and_default_controller_stays_blocked(tmp_path):
    cost, request = reserved(tmp_path)
    reservation_bytes = cost.requests_path.read_bytes()
    preview = cost.hold_unresolved_request(request_id=request, reserved_usd=9, **HOLD)
    assert preview["reserved_usd"] == 9 and preview["usage_reconciled"] is False
    assert preview["actual_charge_usd"] is None
    assert not cost.holds_path.exists() and not cost.ledger_path.exists()
    assert cost.requests_path.read_bytes() == reservation_bytes
    assert cost.active_budget_holds() == {} and cost.budget_exposure_usd() == 5
    assert [row["request_id"] for row in cost.blocking_unresolved_requests()] == [request]
    save_hold(cost, request)
    assert cost.active_budget_holds() == {request: 9}
    assert cost.budget_exposure_usd() == 9 and cost.project_cost_usd() == 0
    with pytest.raises(UnresolvedRequest):
        cost.preflight(**PREFLIGHT)
    assert cost.requests_path.read_bytes() == reservation_bytes
    assert len(cost.unresolved_requests()) == 1


def test_explicit_opt_in_survives_restart_and_new_unknown_blocks_again(tmp_path):
    cost, request = reserved(tmp_path)
    save_hold(cost, request)
    normal = restart(cost)
    with pytest.raises(UnresolvedRequest):
        normal.preflight(**PREFLIGHT)
    recovery = restart(cost, allow=True)
    assert recovery.blocking_unresolved_requests() == []
    next_request, _ = recovery.preflight(**PREFLIGHT)
    assert next_request != request
    assert recovery.budget_exposure_usd() == 14
    assert len(recovery.unresolved_requests()) == 2
    again = restart(cost, allow=True)
    assert [row["request_id"] for row in again.blocking_unresolved_requests()] == [next_request]
    with pytest.raises(UnresolvedRequest):
        again.preflight(**PREFLIGHT)
    assert len(rows(cost.requests_path)) == 2 and not cost.ledger_path.exists()


def test_ceiling_and_approval_threshold_both_include_hold_exposure(tmp_path):
    bounded, request = reserved(tmp_path / "bounded", maximum=20)
    save_hold(bounded, request, 16)
    recovery = restart(bounded, allow=True)
    with pytest.raises(CostLimitExceeded):
        recovery.preflight(**PREFLIGHT)
    assert len(rows(recovery.requests_path)) == 1
    threshold, request = reserved(tmp_path / "threshold")
    save_hold(threshold, request, 16)
    recovery = restart(threshold, allow=True)
    with pytest.raises(CostApprovalRequired) as caught:
        recovery.preflight(**PREFLIGHT)
    assert caught.value.pause.current_cost_usd == 16
    assert caught.value.pause.projected_cost_usd == 21
    assert caught.value.pause.threshold_usd == 20
    assert len(rows(recovery.requests_path)) == 1


def test_reconciliation_retires_hold_and_actual_above_bound_stops_new_work(tmp_path):
    cost, request = reserved(tmp_path / "settled")
    save_hold(cost, request)
    original_hold = cost.holds_path.read_bytes()
    record = reconcile(cost, request, 3)
    assert record.calculated_cost_usd == 3 and not record.cost_is_estimated
    assert cost.active_budget_holds() == {} and cost.unresolved_requests() == []
    assert cost.budget_exposure_usd() == 3 and cost.project_cost_usd() == 3
    assert cost.holds_path.read_bytes() == original_hold
    assert restart(cost).blocking_unresolved_requests() == []
    bounded, request = reserved(tmp_path / "above-bound", maximum=20)
    save_hold(bounded, request, 6)
    record = reconcile(bounded, request, 25)
    assert record.calculated_cost_usd == 25 and bounded.budget_exposure_usd() == 25
    assert bounded.active_budget_holds() == {}
    with pytest.raises(CostLimitExceeded):
        restart(bounded, allow=True).preflight(**PREFLIGHT)
    assert len(rows(bounded.requests_path)) == 1


@pytest.mark.parametrize("amount", [0, -1, float("nan"), float("inf"), float("-inf"), True, "9"])
def test_invalid_hold_amounts_never_write_a_hold(tmp_path, amount):
    cost, request = reserved(tmp_path)
    with pytest.raises(ValueError, match="finite positive"):
        cost.hold_unresolved_request(request_id=request, reserved_usd=amount, **HOLD, dry_run=False)
    assert not cost.holds_path.exists()
    assert len(cost.blocking_unresolved_requests()) == 1


@pytest.mark.parametrize("field", list(HOLD))
def test_blank_evidence_or_authorization_fields_are_rejected(tmp_path, field):
    cost, request = reserved(tmp_path)
    values = dict(HOLD)
    values[field] = "  "
    with pytest.raises(ValueError, match="needs a recorder"):
        cost.hold_unresolved_request(request_id=request, reserved_usd=9, **values, dry_run=False)
    assert not cost.holds_path.exists()


def test_underreserve_unknown_request_and_duplicate_holds_fail(tmp_path):
    cost, request = reserved(tmp_path)
    with pytest.raises(ValueError, match="below the original"):
        save_hold(cost, request, 4.99)
    with pytest.raises(ValueError, match="No unresolved request"):
        save_hold(cost, "missing-request")
    save_hold(cost, request)
    with pytest.raises(ValueError, match="already has"):
        save_hold(cost, request)
    original = cost.holds_path.read_text(encoding="utf-8")
    cost.holds_path.write_text(original + original, encoding="utf-8")
    with pytest.raises(UnresolvedRequest, match="duplicate"):
        restart(cost, allow=True).preflight(**PREFLIGHT)
    assert len(rows(cost.requests_path)) == 1


@pytest.mark.parametrize(
    "change", [{"estimated_cost_usd": 1}, {"estimated_cost_usd": 15}, {"stage_id": "changed-stage"}]
)
def test_tampered_original_reservation_invalidates_hold(tmp_path, change):
    cost, request = reserved(tmp_path)
    save_hold(cost, request)
    reservation = rows(cost.requests_path)[0]
    reservation.update(change)
    cost.requests_path.write_text(json.dumps(reservation) + "\n", encoding="utf-8")
    recovery = restart(cost, allow=True)
    with pytest.raises(UnresolvedRequest, match="Invalid"):
        recovery.active_budget_holds()
    with pytest.raises(UnresolvedRequest):
        recovery.preflight(**PREFLIGHT)
    assert len(rows(cost.requests_path)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"reserved_usd": float("nan")},
        {"reserved_usd": float("inf")},
        {"reserved_usd": 4},
        {"reserved_usd": True},
        {"reserved_usd": "9"},
        {"reservation_sha256": "changed"},
        {"resume_authorization": ""},
    ],
)
def test_corrupt_stored_holds_fail_closed(tmp_path, change):
    cost, request = reserved(tmp_path)
    save_hold(cost, request)
    row = rows(cost.holds_path)[0]
    row.update(change)
    cost.holds_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(UnresolvedRequest):
        restart(cost, allow=True).preflight(**PREFLIGHT)
    assert len(rows(cost.requests_path)) == 1


def test_estimated_usage_and_hold_count_maximum_once_then_reconcile(tmp_path):
    cost, request = reserved(tmp_path)
    save_hold(cost, request, 9)

    def estimated(text):
        return cost.record_response(
            request_id=request,
            estimated_cost_usd=5,
            **PREFLIGHT,
            response=LLMResponse(text=text, provider="mock", model="priced-mock", usage=None),
        )

    smaller = estimated("x" * 16)
    assert smaller.cost_is_estimated and smaller.calculated_cost_usd < 9
    assert cost.budget_exposure_usd() == 9
    larger = estimated("x" * 80)
    assert larger.cost_is_estimated and larger.calculated_cost_usd > 9
    assert cost.budget_exposure_usd() == larger.calculated_cost_usd
    assert len(cost.unresolved_requests()) == 1
    reconcile(cost, request, 3)
    assert cost.budget_exposure_usd() == 3 and cost.project_cost_usd() == 3
    assert cost.active_budget_holds() == {}
