from __future__ import annotations

import hashlib
import json
import math
import os
import smtplib
import ssl
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
            f"Cost approval required at USD {pause.threshold_usd:.2f}; pause record: {path}"
        )
        self.pause = pause
        self.path = path


class CostLimitExceeded(RuntimeError):
    pass


class UnresolvedRequest(RuntimeError):
    """A prior submission must be reconciled before another paid request."""


@contextmanager
def request_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise UnresolvedRequest(
            "Another cost check is active or was interrupted; inspect the request lock."
        ) from exc
    try:
        with handle:
            handle.write(utc_now())
        yield
    finally:
        path.unlink()


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def find_model_pricing(
    snapshot: PricingSnapshotSpec,
    *,
    provider: str,
    model: str,
) -> ModelPricing:
    match = next(
        (item for item in snapshot.models if item.provider == provider and item.model == model),
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
        # Text-only allowance: UTF-8 bytes plus message framing. This is a local
        # estimate, not a provider billing guarantee or a tokenizer count.
        input_tokens=len((system_prompt + user_prompt).encode("utf-8")) + 256,
        output_tokens=max_output_tokens,
    )


def _append_jsonl(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
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
        message["Subject"] = f"QualFrame paused for USD {pause.threshold_usd:.2f} cost approval"
        message["From"] = sender
        message["To"] = recipient
        message.set_content(
            "QualFrame paused before an external model request.\n\n"
            f"Project: {pause.project_id}\nRun: {pause.run_id}\n"
            f"Stage: {pause.stage_id}\nInput: {pause.input_label}\n"
            f"Current budget exposure: USD {pause.current_cost_usd:.4f}\n"
            f"Projected budget exposure: USD {pause.projected_cost_usd:.4f}\n"
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
        allow_budget_holds: bool = False,
    ) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self.artifact_root = artifact_root
        self.ledger_path = logs_root / "cost_ledger.jsonl"
        self.requests_path = logs_root / "request_reservations.jsonl"
        self.approvals_path = logs_root / "cost_approvals.jsonl"
        self.policy = policy
        self.snapshot = pricing_snapshot
        self.pricing = find_model_pricing(pricing_snapshot, provider=provider, model=model)
        self.provider = provider
        self.model = model
        self.max_output_tokens = max_output_tokens
        # Explicit recovery only. Ordinary browser/CLI jobs still require usage.
        self.allow_budget_holds = allow_budget_holds
        self.holds_path = logs_root / "unresolved_budget_holds.jsonl"

    def unresolved_requests(self) -> list[dict[str, object]]:
        settled = {
            row["request_id"]
            for row in _read_jsonl(self.ledger_path)
            if row.get("project_id") == self.project_id and not row.get("cost_is_estimated")
        }
        return [
            row
            for row in _read_jsonl(self.requests_path)
            if row.get("project_id") == self.project_id and row["request_id"] not in settled
        ]

    def _latest_usage(self) -> list[RequestUsageRecord]:
        latest = {}
        for raw in _read_jsonl(self.ledger_path):
            if raw.get("project_id") == self.project_id:
                record = RequestUsageRecord.model_validate(raw)
                latest[record.request_id] = record
        return list(latest.values())

    @staticmethod
    def _reservation_hash(request: dict[str, object]) -> str:
        return hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def active_budget_holds(self) -> dict[str, float]:
        """Unsettled budget exposure, never a substitute for provider usage."""
        unresolved = {str(row["request_id"]): row for row in self.unresolved_requests()}
        holds: dict[str, float] = {}
        for row in _read_jsonl(self.holds_path):
            if row.get("project_id") != self.project_id:
                continue
            request_id = str(row.get("request_id", ""))
            if request_id not in unresolved:
                continue
            request = unresolved[request_id]
            amount = row.get("reserved_usd")
            if (
                type(amount) not in (float, int)
                or not math.isfinite(amount)
                or amount <= 0
                or amount < float(request["estimated_cost_usd"])
                or row.get("reservation_sha256") != self._reservation_hash(request)
                or any(
                    not str(row.get(field, "")).strip()
                    for field in (
                        "recorded_by",
                        "rationale",
                        "bound_evidence_reference",
                        "resume_authorization",
                    )
                )
                or request_id in holds
            ):
                raise UnresolvedRequest("Invalid or duplicate unresolved-request budget hold.")
            holds[request_id] = float(amount)
        return holds

    def blocking_unresolved_requests(self) -> list[dict[str, object]]:
        unresolved = self.unresolved_requests()
        if not self.allow_budget_holds:
            return unresolved
        holds = self.active_budget_holds()
        return [row for row in unresolved if row["request_id"] not in holds]

    def budget_exposure_usd(self) -> float:
        """Latest recorded charges plus outstanding reserves, counted once each."""
        latest = {row.request_id: row.calculated_cost_usd for row in self._latest_usage()}
        holds = self.active_budget_holds()
        for request in self.unresolved_requests():
            request_id = str(request["request_id"])
            latest[request_id] = max(
                latest.get(request_id, 0.0),
                holds.get(request_id, float(request["estimated_cost_usd"])),
            )
        return round(sum(latest.values()), 8)

    def hold_unresolved_request(
        self,
        *,
        request_id: str,
        reserved_usd: float,
        recorded_by: str,
        rationale: str,
        bound_evidence_reference: str,
        resume_authorization: str,
        dry_run: bool = True,
    ) -> dict[str, object]:
        """Keep a documented conservative bound inside the existing spending cap.

        Caller must verify a bound for the actual provider/request configuration.
        A transport failure or the ordinary byte estimate is not that evidence.
        This does not reconcile usage, clear uncertainty, or resume any work.
        """
        if any(
            not value.strip()
            for value in (recorded_by, rationale, bound_evidence_reference, resume_authorization)
        ):
            raise ValueError(
                "A budget hold needs a recorder, bound evidence and resume authorization."
            )
        if (
            type(reserved_usd) not in (int, float)
            or not math.isfinite(reserved_usd)
            or reserved_usd <= 0
        ):
            raise ValueError("The budget hold must be a finite positive USD amount.")
        with request_lock(self.requests_path.with_suffix(".lock")):
            request = next(
                (row for row in self.unresolved_requests() if row["request_id"] == request_id), None
            )
            if request is None:
                raise ValueError("No unresolved request with this identity exists in this study.")
            if request_id in self.active_budget_holds():
                raise ValueError("This request already has a budget hold.")
            if reserved_usd < float(request["estimated_cost_usd"]):
                raise ValueError("The hold cannot be below the original request allowance.")
            row = {
                "kind": "qualframe_unresolved_budget_hold_v1",
                "request_id": request_id,
                "project_id": self.project_id,
                "run_id": request["run_id"],
                "reservation_sha256": self._reservation_hash(request),
                "reserved_usd": float(reserved_usd),
                "recorded_by": recorded_by.strip(),
                "rationale": rationale.strip(),
                "bound_evidence_reference": bound_evidence_reference.strip(),
                "resume_authorization": resume_authorization.strip(),
                "timestamp_utc": utc_now(),
                "usage_reconciled": False,
                "actual_charge_usd": None,
            }
            if not dry_run:
                _append_jsonl(self.holds_path, row)
            return row

    def project_cost_usd(self) -> float:
        return round(sum(row.calculated_cost_usd for row in self._latest_usage()), 8)

    def run_cost_usd(self) -> float:
        return round(
            sum(
                row.calculated_cost_usd for row in self._latest_usage() if row.run_id == self.run_id
            ),
            8,
        )

    def reconcile_request(
        self,
        *,
        request_id: str,
        usage: LLMUsage,
        reviewer: str,
        rationale: str,
        evidence_reference: str,
        response_id: str | None = None,
    ) -> RequestUsageRecord:
        """Record provider-confirmed usage; never assumes a failed call was free."""
        if not reviewer.strip() or not rationale.strip() or not evidence_reference.strip():
            raise ValueError(
                "Reconciliation needs a reviewer, rationale, and provider evidence reference."
            )
        import dataclasses

        if any(type(value) is not int or value < 0 for value in dataclasses.asdict(usage).values()):
            raise ValueError("Usage counts must be nonnegative integers.")
        with request_lock(self.requests_path.with_suffix(".lock")):
            request = next(
                (row for row in self.unresolved_requests() if row["request_id"] == request_id), None
            )
            if request is None:
                raise ValueError("No unresolved request with this identity exists in this study.")
            pricing = ModelPricing.model_validate(request["pricing"])
            record = RequestUsageRecord(
                request_id=request_id,
                response_id=response_id,
                project_id=self.project_id,
                run_id=request["run_id"],
                stage_id=request["stage_id"],
                input_label=request["input_label"],
                provider=request["provider"],
                model=request["model"],
                timestamp_utc=utc_now(),
                **dataclasses.asdict(usage),
                pricing_snapshot_id=request["pricing_snapshot_id"],
                estimated_cost_usd=request["estimated_cost_usd"],
                calculated_cost_usd=calculate_cost_usd(usage, pricing),
                cost_is_estimated=False,
            )
            _append_jsonl(
                self.ledger_path.parent / "usage_reconciliations.jsonl",
                {
                    "request_id": request_id,
                    "reviewer": reviewer.strip(),
                    "rationale": rationale.strip(),
                    "evidence_reference": evidence_reference.strip(),
                    "timestamp_utc": utc_now(),
                    "record": record.model_dump(),
                },
            )
            _append_jsonl(self.ledger_path, record.model_dump())
            return record

    def preflight(
        self,
        *,
        stage_id: str,
        input_label: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, float]:
        with request_lock(self.requests_path.with_suffix(".lock")):
            if self.blocking_unresolved_requests():
                raise UnresolvedRequest(
                    "A previous request has unresolved usage. Reconcile its provider usage "
                    "before retrying; another request was not sent."
                )
            return self._reserve(
                stage_id=stage_id,
                input_label=input_label,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

    def estimate_usd(self, *, system_prompt: str, user_prompt: str) -> float:
        """Read-only bound using the same pricing allowance as request reservation."""
        estimated_usage = estimate_request_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self.max_output_tokens,
        )
        reserve_pricing = self.pricing.model_copy(
            update={
                "input_per_million_usd": max(
                    self.pricing.input_per_million_usd,
                    self.pricing.cached_input_per_million_usd or 0,
                    self.pricing.cache_write_per_million_usd or 0,
                ),
                "output_per_million_usd": max(
                    self.pricing.output_per_million_usd, self.pricing.reasoning_per_million_usd or 0
                ),
            }
        )
        return calculate_cost_usd(estimated_usage, reserve_pricing)

    def _reserve(
        self,
        *,
        stage_id: str,
        input_label: str,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[str, float]:
        request_id = f"request-{uuid.uuid4().hex}"
        estimate = self.estimate_usd(system_prompt=system_prompt, user_prompt=user_prompt)
        current = self.budget_exposure_usd()
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
                    result = send_cost_email(pause, self.policy.notification_recipient_env)
                    pause.notification_status = result.status
                    pause.notification_error = result.error
                pause_path = self.artifact_root / "cost_pause.json"
                pause_path.parent.mkdir(parents=True, exist_ok=True)
                pause_path.write_text(pause.model_dump_json(indent=2), encoding="utf-8")
                raise CostApprovalRequired(pause, pause_path)
            threshold += increment
        _append_jsonl(
            self.requests_path,
            {
                "request_id": request_id,
                "project_id": self.project_id,
                "run_id": self.run_id,
                "stage_id": stage_id,
                "input_label": input_label,
                "provider": self.provider,
                "model": self.model,
                "estimated_cost_usd": estimate,
                "timestamp_utc": utc_now(),
                "pricing": self.pricing.model_dump(),
                "pricing_snapshot_id": self.snapshot.id,
            },
        )
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
