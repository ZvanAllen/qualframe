from pathlib import Path

from qualframe.configuration_lock import (
    compare_configuration_locks,
    create_configuration_lock,
    write_configuration_lock,
)
from qualframe.pipeline.project_runner import ProjectRunner


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_configuration_lock_is_stable_and_includes_method_and_prompts(tmp_path: Path) -> None:
    project_path = REPO_ROOT / "examples/project_template/project_transcript.yaml"

    first = create_configuration_lock(project_path)
    second = create_configuration_lock(project_path)

    assert first.fingerprint_sha256 == second.fingerprint_sha256
    kinds = {asset.kind for asset in first.assets}
    assert {"project", "method", "framework", "pipeline", "prompt_set", "prompt", "provider"} <= kinds
    method_assets = [asset for asset in first.assets if asset.kind == "method"]
    assert len(method_assets) == 1
    assert method_assets[0].id == "cfir_directed_content_analysis_v1"

    output = write_configuration_lock(first, tmp_path / "analysis_configuration_lock.json")
    assert output.exists()
    assert first.fingerprint_sha256 in output.read_text(encoding="utf-8")


def test_configuration_impact_identifies_changed_assets() -> None:
    project_path = REPO_ROOT / "examples/project_template/project_transcript.yaml"
    previous = create_configuration_lock(project_path)
    current = previous.model_copy(deep=True)
    method_asset = next(asset for asset in current.assets if asset.kind == "method")
    method_asset.sha256 = "f" * 64
    current.fingerprint_sha256 = "e" * 64

    impact = compare_configuration_locks(previous, current)

    assert impact.requires_rerun is True
    assert impact.changed_asset_kinds == ["method"]


def test_generic_contract_project_plans_and_executes_with_mock(tmp_path: Path) -> None:
    project_path = REPO_ROOT / "examples/project_template/project_directed_analysis.yaml"
    runner = ProjectRunner(project_path)
    runner.project.paths["artifacts"] = str(tmp_path / "artifacts")
    runner.project.paths["review_queue"] = str(tmp_path / "review_queue")

    plan = runner.build_run_plan()

    assert plan.method_id == "directed_content_analysis_v1"
    assert plan.codebook_id == "example_directed_codebook"
    assert plan.configuration_fingerprint == runner.configuration_lock.fingerprint_sha256
    assert len(plan.planned_stage_runs) == 2
    assert all(item.input_path.endswith(".txt") for item in plan.planned_stage_runs)

    manifest_path = runner.execute_run_plan(plan, "generic_contract_test")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert '"method_id": "directed_content_analysis_v1"' in manifest_text
    assert '"codebook_id": "example_directed_codebook"' in manifest_text
    assert len(list((tmp_path / "artifacts" / "generic_contract_test" / "directed_coding").glob("*.json"))) == 2
