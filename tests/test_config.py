from pathlib import Path

from qualframe.config import (
    load_analysis_plan_spec,
    load_codebook_spec,
    load_cost_policy_spec,
    load_framework_spec,
    load_method_spec,
    load_pipeline_spec,
    load_project_manifest,
    load_prompt_set,
    load_pricing_snapshot_spec,
    load_review_policy_spec,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_example_configs_load() -> None:
    project = load_project_manifest(REPO_ROOT / "examples/project_template/project.yaml")
    framework = load_framework_spec(REPO_ROOT / project.framework)
    pipeline = load_pipeline_spec(REPO_ROOT / project.pipeline)
    prompt_set = load_prompt_set(REPO_ROOT / framework.prompt_set)

    assert project.project_id == "amn_cfir_pilot"
    assert framework.id == "cfir_v1"
    assert pipeline.id == "workbook_cfir_v0_1"
    assert "cross_network_synthesis" in prompt_set.stages


def test_generic_directed_analysis_assets_load() -> None:
    method = load_method_spec(REPO_ROOT / "config/methods/directed_content_analysis_v1.yaml")
    codebook = load_codebook_spec(
        REPO_ROOT / "config/codebooks/example_directed_codebook_v1.yaml"
    )
    review = load_review_policy_spec(
        REPO_ROOT / "config/review_policies/calibration_then_risk_v1.yaml"
    )
    analysis = load_analysis_plan_spec(
        REPO_ROOT / "config/analysis_plans/example_group_comparison_v1.yaml"
    )
    cost = load_cost_policy_spec(
        REPO_ROOT / "config/cost_policies/example_local_email_20_usd_v1.yaml"
    )
    pricing = load_pricing_snapshot_spec(
        REPO_ROOT / "config/pricing/mock_pricing_v1.yaml"
    )

    assert method.analysis_family == "directed_content_analysis"
    assert codebook.version == "1.0.0"
    assert review.calibration_review == "complete"
    assert analysis.metadata_dimensions == ["study_group", "time_point"]
    assert cost.approval_increment_usd == 20
    assert pricing.models[0].model == "synthetic-contract-fixture"
