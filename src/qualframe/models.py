from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ProviderConfig(BaseModel):
    name: str = "mock"
    model: str | None = None
    api_key_env: str | None = None
    temperature: float | None = 0.0
    max_tokens: int = 4000
    api_mode: Literal["chat_completions", "responses"] = "chat_completions"
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None

    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible endpoint, e.g. a local Ollama server or Azure OpenAI /openai/v1/.",
    )

    @model_validator(mode="after")
    def validate_effort(self):
        if self.name == "openai_compatible" and not (self.base_url or "").strip():
            raise ValueError("An OpenAI-compatible provider needs an endpoint address.")
        if self.base_url and self.name != "openai_compatible":
            raise ValueError("Endpoint addresses apply only to OpenAI-compatible providers.")
        if self.reasoning_effort is not None and (self.name != "openai" or self.api_mode != "responses"):
            raise ValueError("Reasoning effort currently requires OpenAI Responses.")
        if self.reasoning_effort is not None and self.temperature is not None:
            raise ValueError("Omit temperature when configuring reasoning effort.")
        if self.anthropic_effort is not None and self.name != "anthropic":
            raise ValueError("Anthropic effort requires Anthropic.")
        if self.anthropic_effort is not None and self.temperature is not None:
            raise ValueError("Omit temperature when configuring Anthropic effort.")
        if self.api_mode == "responses" and self.name != "openai":
            raise ValueError("Responses API mode requires OpenAI.")
        return self


class GovernanceConfig(BaseModel):
    enforce_review_gates: bool = False
    require_release_for_export: bool = True


class StructuredOutputConfig(BaseModel):
    enforce: bool = False
    spec: str = "config/schemas/cfir_stage_outputs_v1.yaml"


class SegmentationPolicy(BaseModel):
    strategy: Literal[
        "model_proposed",
        "researcher_presegmented",
        "sentence",
        "paragraph",
    ] = "model_proposed"
    editable: bool = True
    allow_overlapping_units: bool = False


class ContextWindowPolicy(BaseModel):
    # "turns": speaker turns. The whole turn containing the passage is always kept;
    # before/after add whole turns (for example the question that prompted an answer).
    unit: Literal["characters", "sentences", "paragraphs", "turns"] = "sentences"
    before: int = Field(default=2, ge=0)
    after: int = Field(default=2, ge=0)


class CodingPolicy(BaseModel):
    decision_style: Literal["find_passages", "decide_each_code"] = "find_passages"
    cardinality: Literal["single_label", "multi_label"] = "multi_label"
    allow_overlapping_spans: bool = True
    max_codes_per_unit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_cardinality_limit(self) -> "CodingPolicy":
        if self.cardinality == "single_label" and self.max_codes_per_unit not in (None, 1):
            raise ValueError("single_label coding permits at most one code per meaning unit")
        return self


class CodebookPartitionPolicy(BaseModel):
    strategy: Literal[
        "full_codebook",
        "per_top_level_category",
        "custom_groups",
    ] = "full_codebook"
    custom_groups: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_custom_groups(self) -> "CodebookPartitionPolicy":
        if self.strategy == "custom_groups" and not self.custom_groups:
            raise ValueError("custom_groups partitioning requires at least one named group")
        for group_name, code_ids in self.custom_groups.items():
            if not group_name.strip():
                raise ValueError("custom partition group names cannot be blank")
            if not code_ids:
                raise ValueError(f"custom partition group '{group_name}' cannot be empty")
            if len(code_ids) != len(set(code_ids)):
                raise ValueError(f"custom partition group '{group_name}' contains duplicate code ids")
        return self


class CalibrationPolicy(BaseModel):
    complete_review_required: Literal[True] = True
    reference_status: Literal["human_coded", "human_adjudicated"] = "human_adjudicated"


class MethodSpec(BaseModel):
    id: str
    version: str
    name: str
    analysis_family: Literal["directed_content_analysis"] = "directed_content_analysis"
    evidence_location: Literal["model_offsets", "unique_exact_quote"] = "model_offsets"
    segmentation: SegmentationPolicy = Field(default_factory=SegmentationPolicy)
    context: ContextWindowPolicy = Field(default_factory=ContextWindowPolicy)
    coding: CodingPolicy = Field(default_factory=CodingPolicy)
    partitioning: CodebookPartitionPolicy = Field(default_factory=CodebookPartitionPolicy)
    calibration: CalibrationPolicy = Field(default_factory=CalibrationPolicy)


class ReviewPolicySpec(BaseModel):
    id: str
    version: str
    calibration_review: Literal["complete"] = "complete"
    post_calibration: Literal["complete", "risk_based", "random", "combined"] = "risk_based"
    random_sample_percent: float | None = Field(default=None, ge=0, le=100)
    risk_rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sampling(self) -> "ReviewPolicySpec":
        if self.post_calibration in {"random", "combined"} and self.random_sample_percent is None:
            raise ValueError(f"{self.post_calibration} review requires random_sample_percent")
        if self.post_calibration in {"risk_based", "combined"} and not self.risk_rules:
            raise ValueError(f"{self.post_calibration} review requires at least one risk rule")
        return self


class AnalysisPlanSpec(BaseModel):
    id: str
    version: str
    metadata_dimensions: list[str] = Field(default_factory=list)
    outputs: list[Literal[
        "evidence_table",
        "code_by_group_matrix",
        "co_occurrence",
        "negative_cases",
        "methods_appendix",
    ]] = Field(default_factory=lambda: ["evidence_table", "methods_appendix"])


class CostPolicySpec(BaseModel):
    id: str
    version: str
    currency: Literal["USD"] = "USD"
    approval_increment_usd: float = Field(default=20.0, gt=0)
    absolute_limit_usd: float = Field(gt=0)
    notification_adapter: Literal["email", "none"] = "email"
    notification_recipient_env: str | None = "QUALFRAME_ALERT_EMAIL"

    @model_validator(mode="after")
    def validate_cost_limits(self) -> "CostPolicySpec":
        if self.approval_increment_usd > self.absolute_limit_usd:
            raise ValueError("approval_increment_usd cannot exceed absolute_limit_usd")
        if self.notification_adapter == "email" and not self.notification_recipient_env:
            raise ValueError("email notifications require notification_recipient_env")
        return self


class ModelPricing(BaseModel):
    provider: str
    model: str
    input_per_million_usd: float = Field(ge=0)
    cached_input_per_million_usd: float | None = Field(default=None, ge=0)
    cache_write_per_million_usd: float | None = Field(default=None, ge=0)
    output_per_million_usd: float = Field(ge=0)
    reasoning_per_million_usd: float | None = Field(default=None, ge=0)


class PricingSnapshotSpec(BaseModel):
    id: str
    version: str
    effective_date: str
    currency: Literal["USD"] = "USD"
    source_urls: list[str] = Field(default_factory=list)
    models: list[ModelPricing]

    @model_validator(mode="after")
    def validate_unique_models(self) -> "PricingSnapshotSpec":
        identities = [(item.provider, item.model) for item in self.models]
        if len(identities) != len(set(identities)):
            raise ValueError("pricing snapshot provider/model pairs must be unique")
        return self


class RequestUsageRecord(BaseModel):
    request_id: str
    response_id: str | None = None
    project_id: str
    run_id: str
    stage_id: str
    input_label: str
    provider: str
    model: str
    timestamp_utc: str
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    pricing_snapshot_id: str
    estimated_cost_usd: float = Field(ge=0)
    calculated_cost_usd: float = Field(ge=0)
    cost_is_estimated: bool = False


class CostApprovalAction(BaseModel):
    action_id: str
    project_id: str
    run_id: str
    threshold_usd: float = Field(gt=0)
    decision: Literal["approve", "stop"]
    reviewer: str
    rationale: str
    timestamp_utc: str


class CostPauseRecord(BaseModel):
    project_id: str
    run_id: str
    stage_id: str
    input_label: str
    current_cost_usd: float = Field(ge=0)
    projected_cost_usd: float = Field(ge=0)
    threshold_usd: float = Field(gt=0)
    absolute_limit_usd: float = Field(gt=0)
    notification_adapter: str
    notification_status: Literal["not_configured", "sent", "failed"]
    notification_error: str | None = None
    created_at_utc: str


class StageSpec(BaseModel):
    id: str
    description: str = ""
    prompt_ref: str | None = None
    enabled: bool = True
    input_kind: str = "unknown"
    output_kind: str = "unknown"
    review_gate: bool = False
    # "per_file": one LLM call per input; "bundle_all": one call with all inputs combined
    input_grouping: str = "per_file"
    # "raw_workbooks": read from disk; "previous_stage": use prior stage's response texts
    input_source: str = "raw_workbooks"
    # When True, runner repeats this stage once per framework domain, substituting {CFIR_DOMAIN}
    # in the prompt. Outputs for the same transcript are compiled into one multi-sheet artifact.
    domain_iterations: bool = False
    # When True, the CFIR codebook from data/reference/codebook.* is appended to the user prompt.
    use_codebook: bool = False
    # When True, previous-stage inputs are grouped by AMN network (parent folder of the transcript
    # path) and one LLM call is made per network. Produces one artifact per network.
    group_by_network: bool = False
    # When True, the original source transcript is appended to the user prompt alongside the
    # previous-stage output. Used for stages that need to look up quotes in the full transcript
    # (e.g. quote context enrichment). Requires input_source: previous_stage.
    include_original_transcript: bool = False


class PipelineSpec(BaseModel):
    id: str
    description: str = ""
    framework: str
    mode: Literal["workbook_first", "transcript_first"]
    stages: list[StageSpec] = Field(default_factory=list)


class FrameworkSpec(BaseModel):
    id: str
    name: str
    analysis_mode: str = "deductive"
    domains: list[str] = Field(default_factory=list)
    parent_construct_regex: str | None = None
    subconstruct_regex: str | None = None
    network_labels: list[str] = Field(default_factory=list)
    valence_labels: dict[str, list[str]] = Field(default_factory=dict)
    qa_rules: list[str] = Field(default_factory=list)
    required_columns: list[str] = Field(default_factory=list)
    special_rollups: dict[str, object] = Field(default_factory=dict)
    prompt_set: str | None = None


class CodebookEntry(BaseModel):
    id: str
    label: str
    parent_id: str | None = None
    definition: str
    inclusion_guidance: str = ""
    exclusion_guidance: str = ""
    examples: list[str] = Field(default_factory=list)
    active: bool = True


class CodebookSpec(BaseModel):
    id: str
    version: str
    name: str
    codes: list[CodebookEntry]

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "CodebookSpec":
        ids = [code.id for code in self.codes]
        if len(ids) != len(set(ids)):
            raise ValueError("codebook code ids must be unique")
        known_ids = set(ids)
        parents = {code.id: code.parent_id for code in self.codes}
        for code in self.codes:
            if code.parent_id == code.id:
                raise ValueError(f"code '{code.id}' cannot be its own parent")
            if code.parent_id is not None and code.parent_id not in known_ids:
                raise ValueError(f"code '{code.id}' references unknown parent '{code.parent_id}'")
            seen: set[str] = set()
            current = code.id
            while parents.get(current) is not None:
                if current in seen:
                    raise ValueError(f"codebook hierarchy contains a cycle involving '{code.id}'")
                seen.add(current)
                current = parents[current]  # type: ignore[assignment]
        return self


class MeaningUnit(BaseModel):
    id: str
    source_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    segmentation_method: Literal[
        "model_proposed",
        "researcher_presegmented",
        "sentence",
        "paragraph",
        "reviewer_edited",
    ]
    version: int = Field(default=1, ge=1)
    derived_from_id: str | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> "MeaningUnit":
        if self.end_offset <= self.start_offset:
            raise ValueError("meaning-unit end_offset must be greater than start_offset")
        return self


class EvidenceSpan(BaseModel):
    id: str
    meaning_unit_id: str
    source_id: str
    source_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of UTF-8 extracted source text; offsets address this text.",
    )
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_text: str
    exact_text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    context_start_offset: int | None = Field(default=None, ge=0)
    context_end_offset: int | None = Field(default=None, gt=0)
    speaker: str | None = None
    creation_method: Literal[
        "model_proposed",
        "researcher_presegmented",
        "automatic",
        "reviewer_edited",
        "researcher_added",
    ]
    derived_from_span_id: str | None = None

    @model_validator(mode="after")
    def validate_span(self) -> "EvidenceSpan":
        if self.end_offset <= self.start_offset:
            raise ValueError("evidence-span end_offset must be greater than start_offset")
        if not self.exact_text:
            raise ValueError("evidence-span exact_text cannot be empty")
        expected_hash = hashlib.sha256(self.exact_text.encode("utf-8")).hexdigest()
        if self.exact_text_sha256 is None:
            self.exact_text_sha256 = expected_hash
        elif self.exact_text_sha256 != expected_hash:
            raise ValueError("exact_text_sha256 does not match exact_text")
        if (self.context_start_offset is None) != (self.context_end_offset is None):
            raise ValueError("context offsets must both be provided or both omitted")
        if self.context_start_offset is not None and self.context_end_offset is not None:
            if self.context_start_offset > self.start_offset:
                raise ValueError("context_start_offset must not follow the exact span")
            if self.context_end_offset < self.end_offset:
                raise ValueError("context_end_offset must not precede the exact span end")
        return self


class CodeAssignment(BaseModel):
    id: str
    meaning_unit_id: str
    evidence_span_id: str
    codebook_id: str
    codebook_version: str
    code_id: str
    origin: Literal["human", "model", "imported", "adjudicated"]
    rationale: str | None = None
    run_id: str | None = None
    review_status: Literal["unreviewed", "accepted", "edited", "rejected", "deferred"] = "unreviewed"
    derived_from_assignment_id: str | None = None


class EvidenceReviewRecord(BaseModel):
    record_id: str
    run_id: str
    stage_id: str
    artifact_path: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sheet_name: str
    row_index: int = Field(ge=1)
    source_id: str
    source_path: str
    source_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of original source file bytes, checked before review actions.",
    )
    meaning_unit_id: str
    proposed_start_offset: int
    proposed_end_offset: int
    proposed_exact_text: str
    raw_start_value: str | None = None
    raw_end_value: str | None = None
    anchoring_method: Literal["model_offsets", "unique_exact_quote", "unresolved_exact_quote", "normalized_quote_candidate", "no_evidence", "researcher_selection"] = "model_offsets"
    record_kind: Literal["evidence", "absence"] = "evidence"
    proposed_code_id: str | None = None
    proposed_rationale: str | None = None
    anchor_match_count: int | None = None
    context_text: str | None = None
    evidence_span: EvidenceSpan | None = None
    assignment: CodeAssignment | None = None
    code_label: str | None = None
    code_definition: str | None = None
    model: str | None = None
    provider: str | None = None
    prompt_sha256: str
    configuration_fingerprint: str | None = None
    validation_issues: list[str] = Field(default_factory=list)


class EvidenceReviewAction(BaseModel):
    action_id: str
    run_id: str
    record_id: str
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["accept", "edit", "reject", "defer"]
    reviewer: str
    rationale: str
    derived_artifact_path: str | None = None
    timestamp_utc: str


class PromptSpec(BaseModel):
    file: str
    notes: str = ""


class PromptSet(BaseModel):
    id: str
    description: str = ""
    stages: dict[str, PromptSpec] = Field(default_factory=dict)


class ProjectManifest(BaseModel):
    project_id: str
    title: str | None = None
    created_at_utc: str | None = None
    data_classification: Literal["synthetic", "published", "deidentified", "sensitive"] | None = None
    source_manifest: str | None = None
    metadata_file: str | None = None
    framework: str
    pipeline: str
    method: str | None = None
    codebook: str | None = None
    review_policy: str | None = None
    analysis_plan: str | None = None
    cost_policy: str | None = None
    pricing_snapshot: str | None = None
    mode: Literal["workbook_first", "transcript_first"] = "workbook_first"
    paths: dict[str, str]
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    structured_output: StructuredOutputConfig = Field(default_factory=StructuredOutputConfig)

    @model_validator(mode="after")
    def validate_cost_configuration_pair(self) -> "ProjectManifest":
        if bool(self.cost_policy) != bool(self.pricing_snapshot):
            raise ValueError(
                "cost_policy and pricing_snapshot must be configured together"
            )
        return self


class StudyCreationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    study_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$",
    )
    data_classification: Literal["synthetic", "published", "deidentified", "sensitive"]
    template: Literal["generic_directed", "cfir"] = "generic_directed"
    include_synthetic_fixtures: bool = False

    @model_validator(mode="after")
    def validate_fixture_classification(self) -> "StudyCreationRequest":
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("study title cannot be blank")
        if self.include_synthetic_fixtures and self.data_classification != "synthetic":
            raise ValueError(
                "synthetic starter materials require the synthetic data classification"
            )
        return self


class SourceImportRecord(BaseModel):
    source_id: str
    source_kind: Literal["transcript", "codebook", "metadata"]
    original_filename: str
    destination_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    imported_at_utc: str
    provenance: Literal["checked_in_synthetic_fixture", "researcher_import"]
    imported_by: str | None = None
    rationale: str | None = None
    original_path: str | None = None
    original_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    conversion_path: str | None = None


class CreatedStudy(BaseModel):
    study_id: str
    title: str
    project_manifest_path: str
    data_classification: Literal["synthetic", "published", "deidentified", "sensitive"]
    template: Literal["generic_directed", "cfir"]
    imported_source_count: int = Field(ge=0)


class MethodPolicyUpdate(BaseModel):
    context_unit: Literal["characters", "sentences", "paragraphs", "turns"] = "sentences"
    segmentation_strategy: Literal[
        "model_proposed",
        "researcher_presegmented",
        "sentence",
        "paragraph",
    ]
    context_before: int = Field(ge=0, le=10)
    context_after: int = Field(ge=0, le=10)
    coding_cardinality: Literal["single_label", "multi_label"]
    coding_decision_style: Literal["find_passages", "decide_each_code"] = "find_passages"
    allow_overlapping_spans: bool = True
    partition_strategy: Literal["full_codebook", "per_top_level_category", "custom_groups"]


class StudyChangeAction(BaseModel):
    action_id: str
    project_id: str
    change_kind: Literal["codebook_import", "metadata_import", "method_update", "instructions_update"]
    previous_ref: str | None = None
    new_ref: str
    actor: str
    rationale: str
    timestamp_utc: str


class ConfigurationAssetRef(BaseModel):
    kind: Literal[
        "project",
        "method",
        "framework",
        "codebook",
        "pipeline",
        "prompt_set",
        "prompt",
        "review_policy",
        "analysis_plan",
        "cost_policy",
        "pricing_snapshot",
        "provider",
        "governance",
        "structured_output",
        "structured_output_schema",
    ]
    id: str
    version: str | None = None
    path: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LockedAnalysisConfiguration(BaseModel):
    lock_id: str
    project_id: str
    status: Literal["locked"] = "locked"
    created_at_utc: str
    fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assets: list[ConfigurationAssetRef]


class ConfigurationImpact(BaseModel):
    previous_fingerprint: str
    current_fingerprint: str
    changed_asset_kinds: list[str] = Field(default_factory=list)
    requires_rerun: bool = False


class DiscoveredInput(BaseModel):
    path: str
    kind: str
    sha256: str | None = None


class PlannedStageRun(BaseModel):
    stage_id: str
    input_path: str  # primary input path, or descriptive label for chained/bundled stages
    input_paths: list[str] = Field(default_factory=list)  # all inputs for bundle stages
    output_hint: str
    prompt_ref: str | None = None
    review_gate: bool = False
    domain: str | None = None  # set when stage uses domain_iterations=True


class RunPlan(BaseModel):
    project_id: str
    framework_id: str
    pipeline_id: str
    method_id: str | None = None
    codebook_id: str | None = None
    configuration_fingerprint: str | None = None
    mode: str
    discovered_inputs: list[DiscoveredInput] = Field(default_factory=list)
    planned_stage_runs: list[PlannedStageRun] = Field(default_factory=list)
    # A test run on some of the study's transcripts (paths relative to the studies folder).
    transcript_sample: list[str] | None = None


class WorkbookValidationResult(BaseModel):
    path: str
    valid: bool
    missing_domain_sheets: list[str] = Field(default_factory=list)
    # sheet name → list of missing columns
    column_issues: dict[str, list[str]] = Field(default_factory=dict)


class StageArtifact(BaseModel):
    run_id: str
    stage_id: str
    input_path: str
    input_sha256: str | None
    prompt_ref: str | None
    prompt_sha256: str
    evidence_location: Literal["model_offsets", "unique_exact_quote"] = "model_offsets"
    response_text: str
    model: str | None
    provider: str | None
    timestamp_utc: str
    # sheet_name → list of row dicts; None if parsing produced no tables
    parsed_output: dict[str, list[dict[str, str]]] | None = None
    # Requested active codes omitted from each part; never evidence or explicit absence.
    no_decisions: dict[str, list[str]] = Field(default_factory=dict)
    structured_output_schema_id: str | None = None
    # Scoped contracts bind resumed artifacts to their original validation/QA policy.
    structured_output_contract_sha256: str | None = None
    structured_output_valid: bool | None = None
    structured_output_issues: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    project_id: str
    framework_id: str
    pipeline_id: str
    method_id: str | None = None
    codebook_id: str | None = None
    configuration_fingerprint: str | None = None
    configuration_assets: list[ConfigurationAssetRef] = Field(default_factory=list)
    completed_at_utc: str
    # paths to each StageArtifact JSON, relative to the run's artifact_root directory
    artifact_paths: list[str] = Field(default_factory=list)
    qa_failure_count: int = 0
    no_decision_count: int = Field(default=0, ge=0)
    qa_inventory_path: str | None = None
    qa_inventory_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: Literal["completed", "awaiting_review", "blocked_validation"] = "completed"
    pending_gate: str | None = None
    approved_gates: list[str] = Field(default_factory=list)
    release_status: Literal["not_required", "unreleased", "released"] = "not_required"
    structured_output_failure_count: int = 0
    run_cost_usd: float | None = Field(default=None, ge=0)
    project_cost_usd: float | None = Field(default=None, ge=0)
    cost_ledger_path: str | None = None


class GateAction(BaseModel):
    action_id: str
    run_id: str
    stage_id: str
    decision: Literal["approve", "reject"]
    reviewer: str
    rationale: str
    timestamp_utc: str


class ReleaseAction(BaseModel):
    action_id: str
    run_id: str
    reviewer: str
    rationale: str
    timestamp_utc: str


class DisagreementSpec(BaseModel):
    id: str
    identity_columns: list[str] = Field(default_factory=lambda: ["CFIR Domain", "CFIR Construct"])
    compare_columns: list[str] = Field(default_factory=list)
    case_sensitive: bool = False


class DisagreementRecord(BaseModel):
    record_id: str
    kind: Literal["disagreement"] = "disagreement"
    status: Literal["pending"] = "pending"
    run_id: str
    stage_id: str
    spec_id: str
    sheet: str
    identity: dict[str, str]
    field: str
    left_value: str | None
    right_value: str | None
    left_artifact: str
    right_artifact: str
    left_prompt_sha256: str
    right_prompt_sha256: str
    left_input_sha256: str | None
    right_input_sha256: str | None
    detected_at_utc: str


class AdjudicationAction(BaseModel):
    action_id: str
    run_id: str
    item_path: str
    item_sha256: str
    decision: Literal["approve", "edit", "reject", "defer"]
    reviewer: str
    rationale: str
    edited_row: dict[str, str] | None = None
    derived_artifact_path: str | None = None
    timestamp_utc: str


class StageOutputRule(BaseModel):
    required_columns: list[str] = Field(default_factory=list)
    require_rows: bool = True
    exact_column_order: bool = False
    allowed_values: dict[str, list[str]] = Field(default_factory=dict)
    required_values: dict[str, list[str]] = Field(default_factory=dict)
    # None preserves framework-level rules and required columns. [] disables only
    # framework QA for this stage; structured-output validation remains enforced.
    qa_rules: list[Literal[
        "required_columns_present", "allowed_network_labels_only",
        "one_network_one_valence", "source_files_covered_by_valence_columns",
        "prompt_version_required",
    ]] | None = None

    @model_validator(mode="after")
    def validate_column_values(self):
        for column in self.allowed_values.keys() | self.required_values.keys():
            if column not in self.required_columns:
                raise ValueError(f"Constrained column '{column}' must be required.")
            allowed = self.allowed_values.get(column)
            required = self.required_values.get(column, [])
            if allowed is not None and not set(required).issubset(allowed):
                raise ValueError(f"Required values for '{column}' must be allowed.")
        return self


class StageOutputSpec(BaseModel):
    id: str
    stages: dict[str, StageOutputRule] = Field(default_factory=dict)
