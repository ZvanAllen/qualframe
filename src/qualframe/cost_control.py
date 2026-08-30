from __future__ import annotations

import json
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from qualframe.models import (
    CostApprovalAction,
    CostPauseRecord,
    CostPolicySpec,
    ModelPricing,
    PricingSnapshotSpec,
    RequestUsageRecord,
)
from qualframe.providers.base import LLMResponse, LLMUsage, estimate_tokens


class CostApprovalRequired(RuntimeError):
    def __init__(self, pause: CostPauseRecord, path: Path) -> None:
        super().__init__(
            f"Cost approval required at USD {pause.threshold_usd:.2f}; "
            f"pause record: {path}"
        )
        self.pause = pause
        self.path = path


class CostLimitExceeded(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_model_pricing(
    snapshot: PricingSnapshotSpec,
    *,
    provider: str,
    model: str,
) -> ModelPricing:
    match = next(
        (
            item
            for item in snapshot.models
            if item.provider == provider and item.model == model
        ),
        None,
    )
    if match is None:
        raise ValueError(
            f"Pricing snapshot '{snapshot.id}' has no exact entry for "
            f"provider/model '{provider}/{model}'."
        )
    return match


def calculate_cost_usd(usage: LLMUsage, pricing: ModelPricing) -> float:
    """Calculate cost from normalized, mutually exclusive token counts."""
    cached_rate = (
        pricing.cached_input_per_million_usd
        if pricing.cached_input_per_million_usd is not None
        else pricing.input_per_million_usd
    )
    cache_write_rate = (
        pricing.cache_write_per_million_usd
        if pricing.cache_write_per_million_usd is not None
        else pricing.input_per_million_usd
    )
    reasoning_rate = (
        pricing.reasoning_per_million_usd
        if pricing.reasoning_per_million_usd is not None
        else pricing.output_per_million_usd
    )
    total = (
        usage.input_tokens * pricing.input_per_million_usd
        + usage.cached_input_tokens * cached_rate
        + usage.cache_write_tokens * cache_write_rate
        + usage.output_tokens * pricing.output_per_million_usd
        + usage.reasoning_tokens * reasoning_rate
    ) / 1_000_000
    return round(total, 8)


def estimate_request_usage(
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> LLMUsage:
    return LLMUsage(
        input_tokens=estimate_tokens(system_prompt + user_prompt),
        output_tokens=max_output_tokens,
    )


def _append_jsonl(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_cost_approval(
    approvals_path: Path,
    *,
    project_id: str,
    run_id: str,
    threshold_usd: float,
    decision: str,
    reviewer: str,
    rationale: str,
) -> CostApprovalAction:
    if decision not in {"approve", "stop"}:
        raise ValueError("Cost decision must be 'approve' or 'stop'.")
    if not reviewer.strip() or not rationale.strip():
        raise ValueError("Cost approvals require reviewer identity and rationale.")
    action = CostApprovalAction(
        action_id=f"cost-{uuid.uuid4().hex}",
        project_id=project_id,
        run_id=run_id,
        threshold_usd=threshold_usd,
        decision=decision,
        reviewer=reviewer.strip(),
        rationale=rationale.strip(),
        timestamp_utc=utc_now(),
    )
    _append_jsonl(approvals_path, action.model_dump())
    return action


def approved_cost_thresholds(approvals_path: Path, project_id: str) -> set[float]:
    latest: dict[float, str] = {}
    for raw in _read_jsonl(approvals_path):
        action = CostApprovalAction.model_validate(raw)
        if action.project_id == project_id:
            latest[action.threshold_usd] = action.decision
    return {threshold for threshold, decision in latest.items() if decision == "approve"}


@dataclass
class NotificationResult:
    status: str
    error: str | None = None


def send_cost_email(pause: CostPauseRecord, recipient_env: str | None) -> NotificationResult:
    recipient = os.getenv(recipient_env or "") if recipient_env else None
    adapter = os.getenv("QUALFRAME_EMAIL_ADAPTER", "").strip().lower()
    host = os.getenv("QUALFRAME_SMTP_HOST", "").strip()
    sender = os.getenv("QUALFRAME_EMAIL_FROM", "").strip()
    if adapter != "smtp" or not recipient or not host or not sender:
        return NotificationResult("not_configured")
    try:
        port = int(os.getenv("QUALFRAME_SMTP_PORT", "465"))
        message = EmailMessage()
        message["Subject"] = (
            f"QualFrame paused for USD {pause.threshold_usd:.2f} cost approval"
        )
        message["From"] = sender
        message["To"] = recipient
        message.set_content(
            "QualFrame paused before an external model request.\n\n"
            f"Project: {pause.project_id}\nRun: {pause.run_id}\n"
            f"Stage: {pause.stage_id}\nInput: {pause.input_label}\n"
            f"Current spend: USD {pause.current_cost_usd:.4f}\n"
            f"Projected spend: USD {pause.projected_cost_usd:.4f}\n"
            f"Approval threshold: USD {pause.threshold_usd:.2f}\n\n"
            "Use the local QualFrame approve-cost command to approve or stop. "
            "This email cannot resume the run."
        )
        username = os.getenv("QUALFRAME_SMTP_USERNAME", "").strip()
        password = os.getenv("QUALFRAME_SMTP_PASSWORD", "")
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
        return NotificationResult("sent")
    except Exception as exc:  # delivery failure must preserve the pause
        return NotificationResult("failed", str(exc))


class CostController:
    def __init__(
        self,
        *,
        project_id: str,
        run_id: str,
        artifact_root: Path,
        logs_root: Path,
        policy: CostPolicySpec,
        pricing_snapshot: PricingSnapshotSpec,
        provider: str,
        model: str,
        max_output_tokens: int,
    ) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self.artifact_root = artifact_root
        self.ledger_path = logs_root / "cost_ledger.jsonl"
        self.approvals_path = logs_root / "cost_approvals.jsonl"
        self.policy = policy
        self.snapshot = pricing_snapshot
        self.pricing = find_model_pricing(
            pricing_snapshot, provider=provider, model=model
        )
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens

    def project_cost_usd(self) -> float:
        return round(
            sum(
                RequestUsageRecord.model_validate(raw).calculated_cost_usd
                for raw in _read_jsonl(self.ledger_path)
                if raw.get("project_id") == self.project_id
            ),
            8,
        )

    def run_cost_usd(self) -> float:
        return round(
            sum(
                RequestUsageRecord.model_validate(raw).calculated_cost_usd
                for raw in _read_jsonl(self.ledger_path)
                if raw.get("project_id") == self.project_id
                and raw.get("run_id") == self.run_id
            ),
            8,
        )

    def preflight(
        self,
        *,
        stage_id: str,
        input_label: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, float]:
        request_id = f"request-{uuid.uuid4().hex}"
        estimated_usage = estimate_request_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self.max_output_tokens,
        )
        estimate = calculate_cost_usd(estimated_usage, self.pricing)
        current = self.project_cost_usd()
        projected = round(current + estimate, 8)
        if projected > self.policy.absolute_limit_usd:
            raise CostLimitExceeded(
                f"Projected project spend USD {projected:.4f} exceeds the absolute "
                f"limit USD {self.policy.absolute_limit_usd:.2f}; no request was sent."
            )

        approved = approved_cost_thresholds(self.approvals_path, self.project_id)
        increment = self.policy.approval_increment_usd
        threshold = increment
        while threshold <= projected + 1e-9:
            rounded_threshold = round(threshold, 8)
            if rounded_threshold not in approved:
                pause = CostPauseRecord(
                    project_id=self.project_id,
                    run_id=self.run_id,
                    stage_id=stage_id,
                    input_label=input_label,
                    current_cost_usd=current,
                    projected_cost_usd=projected,
                    threshold_usd=rounded_threshold,
                    absolute_limit_usd=self.policy.absolute_limit_usd,
                    notification_adapter=self.policy.notification_adapter,
                    notification_status="not_configured",
                    created_at_utc=utc_now(),
                )
                if self.policy.notification_adapter == "email":
                    result = send_cost_email(
                        pause, self.policy.notification_recipient_env
                    )
                    pause.notification_status = result.status
                    pause.notification_error = result.error
                pause_path = self.artifact_root / "cost_pause.json"
                pause_path.parent.mkdir(parents=True, exist_ok=True)
                pause_path.write_text(pause.model_dump_json(indent=2), encoding="utf-8")
                raise CostApprovalRequired(pause, pause_path)
            threshold += increment
        return request_id, estimate

    def record_response(
        self,
        *,
        request_id: str,
        estimated_cost_usd: float,
        stage_id: str,
        input_label: str,
        system_prompt: str,
        user_prompt: str,
        response: LLMResponse,
    ) -> RequestUsageRecord:
        cost_is_estimated = response.usage is None
        usage = response.usage or LLMUsage(
            input_tokens=estimate_tokens(system_prompt + user_prompt),
            output_tokens=estimate_tokens(response.text),
        )
        record = RequestUsageRecord(
            request_id=request_id,
            response_id=response.response_id,
            project_id=self.project_id,
            run_id=self.run_id,
            stage_id=stage_id,
            input_label=input_label,
            provider=response.provider or self.provider,
            model=response.model or self.model,
            timestamp_utc=utc_now(),
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            pricing_snapshot_id=self.snapshot.id,
            estimated_cost_usd=estimated_cost_usd,
            calculated_cost_usd=calculate_cost_usd(usage, self.pricing),
            cost_is_estimated=cost_is_estimated,
        )
        _append_jsonl(self.ledger_path, record.model_dump())
        return record
