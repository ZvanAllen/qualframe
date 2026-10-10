"""Versioned provider and budget setup; never submits an API request."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from qualframe.models import (
    CostPolicySpec,
    ModelPricing,
    PricingSnapshotSpec,
    ProjectManifest,
    ProviderConfig,
)
from qualframe.study_setup import StudyWorkspace


STANDARD_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                    "openai_compatible": "QUALFRAME_ENDPOINT_API_KEY"}


class ProviderSetup(BaseModel):
    provider: Literal["openai", "anthropic", "openai_compatible"]
    model: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9._:/-]+$")
    max_tokens: int = Field(ge=128, le=64000)
    temperature: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    api_mode: Literal["chat_completions", "responses"] = "chat_completions"
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = (
        None
    )
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    absolute_limit_usd: float = Field(gt=0, le=10000, allow_inf_nan=False)
    input_rate: float = Field(ge=0, allow_inf_nan=False)
    output_rate: float = Field(ge=0, allow_inf_nan=False)
    pricing_date: date
    pricing_source: str = ""
    governance_confirmed: Literal[True]
    base_url: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def check_pricing_source(self):
        from urllib.parse import urlparse

        if self.provider == "openai_compatible":
            endpoint = urlparse(self.base_url or "")
            if endpoint.scheme not in {"http", "https"} or not endpoint.hostname:
                raise ValueError("Enter the endpoint address, for example http://localhost:11434/v1.")
            if endpoint.scheme == "http" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Use https for endpoints that are not on this computer.")
            if self.pricing_date > date.today():
                raise ValueError("Pricing verification date cannot be in the future.")
            return self
        if self.base_url:
            raise ValueError("Endpoint addresses apply only to compatible endpoints.")
        if self.input_rate <= 0 or self.output_rate <= 0:
            raise ValueError("Enter the provider's current prices so spending can be estimated.")
        parsed = urlparse(self.pricing_source)
        domains = {
            "openai": {"openai.com", "platform.openai.com", "developers.openai.com"},
            "anthropic": {
                "anthropic.com",
                "www.anthropic.com",
                "docs.anthropic.com",
                "platform.claude.com",
                "claude.com",
            },
        }
        if parsed.scheme != "https" or parsed.hostname not in domains[self.provider]:
            raise ValueError("Use an official provider HTTPS pricing source.")
        if self.pricing_date > date.today():
            raise ValueError("Pricing verification date cannot be in the future.")
        ProviderConfig(
            name=self.provider,
            temperature=self.temperature,
            api_mode=self.api_mode,
            reasoning_effort=self.reasoning_effort,
            anthropic_effort=self.anthropic_effort,
        )
        return self


def save_provider_setup(
    workspace: StudyWorkspace,
    project_path: Path,
    setup: ProviderSetup,
    *,
    actor: str,
    rationale: str,
    api_key: str = "",
    use_environment_key: bool = False,
) -> Path:
    actor, rationale = workspace._validate_action_fields(actor, rationale)
    root = workspace.managed_study_root(project_path)
    data = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    version_id = uuid.uuid4().hex
    config_root = root / "config" / f"provider-{version_id}"
    key_env = (
        f"QUALFRAME_{data['project_id'].upper().replace('-', '_')}_{setup.provider.upper()}_KEY"
    )
    standard_env = STANDARD_KEY_ENV.get(setup.provider)
    if use_environment_key and standard_env and os.getenv(standard_env):
        key_env = standard_env
    pricing = PricingSnapshotSpec(
        id=f"pricing-{version_id}",
        version="1",
        effective_date=setup.pricing_date.isoformat(),
        source_urls=[setup.pricing_source] if setup.pricing_source else [],
        models=[
            ModelPricing(
                provider=setup.provider,
                model=setup.model,
                input_per_million_usd=setup.input_rate,
                output_per_million_usd=setup.output_rate,
            )
        ],
    )
    policy = CostPolicySpec(
        id=f"budget-{version_id}",
        version="1",
        absolute_limit_usd=setup.absolute_limit_usd,
        approval_increment_usd=min(20, setup.absolute_limit_usd),
        notification_adapter="email",
    )
    updated = dict(data)
    updated["provider"] = {
        "name": setup.provider,
        "model": setup.model,
        "api_key_env": key_env,
        "max_tokens": setup.max_tokens,
        "temperature": setup.temperature,
        "api_mode": setup.api_mode,
        "reasoning_effort": setup.reasoning_effort,
        "anthropic_effort": setup.anthropic_effort,
    }
    if setup.provider == "openai_compatible":
        updated["provider"]["base_url"] = setup.base_url
        updated["provider"]["api_mode"] = "chat_completions"
    updated["cost_policy"] = (config_root / "cost.yaml").relative_to(workspace.repo_root).as_posix()
    updated["pricing_snapshot"] = (
        (config_root / "pricing.yaml").relative_to(workspace.repo_root).as_posix()
    )
    ProjectManifest.model_validate(updated)
    # All validation precedes persistent writes; credentials never enter these records.
    config_root.mkdir(parents=True)
    for filename, value in (
        ("cost.yaml", policy.model_dump()),
        ("pricing.yaml", pricing.model_dump()),
        ("project-before.yaml", data),
        ("project-after.yaml", updated),
    ):
        (config_root / filename).write_text(
            yaml.safe_dump(value, sort_keys=False), encoding="utf-8"
        )
    (config_root / "decision.json").write_text(
        json.dumps(
            {
                "actor": actor,
                "rationale": rationale,
                "governance_confirmed": True,
                "live_execution_authorized": False,
                "settings": setup.model_dump(mode="json"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary = project_path.with_name(f".provider-{version_id}.yaml")
    temporary.write_text(yaml.safe_dump(updated, sort_keys=False), encoding="utf-8")
    temporary.replace(project_path)
    if api_key.strip():
        # Session-only: discarded when this local app process exits.
        os.environ[key_env] = api_key.strip()
    return config_root
