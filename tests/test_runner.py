import json
import shutil
from pathlib import Path

import yaml

from qualframe.models import StageArtifact
from qualframe.pipeline.project_runner import ProjectRunner


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runner_builds_empty_plan_when_no_workbooks(tmp_path: Path) -> None:
    """Runner should produce an empty plan when the workbooks directory is empty."""
    # Copy config files so the runner can resolve framework/pipeline/prompt-set specs.
    for rel in [
        "config/methods/cfir_directed_content_analysis_v1.yaml",
        "config/frameworks/cfir_v1.yaml",
        "config/pipelines/workbook_cfir.yaml",
        "config/prompt_sets/cfir_final_prompts_v1.yaml",
    ]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)

    shutil.copytree(REPO_ROOT / "prompts", tmp_path / "prompts")

    src = REPO_ROOT / "examples/project_template/project.yaml"
    manifest = yaml.safe_load(src.read_text())
    manifest["paths"]["raw_workbooks"] = str(tmp_path / "empty_workbooks")

    # project.yaml must be 3 levels deep for ProjectRunner's repo_root heuristic.
    dest_dir = tmp_path / "examples" / "project_template"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "project.yaml"
    dest.write_text(yaml.dump(manifest))

    runner = ProjectRunner(dest)
    plan = runner.build_run_plan()
    assert plan.project_id == "amn_cfir_pilot"
    assert plan.pipeline_id == "workbook_cfir_v0_1"
    assert plan.method_id == "cfir_directed_content_analysis_v1"
    assert plan.configuration_fingerprint
    assert plan.discovered_inputs == []


def test_runner_discovers_real_workbooks(tmp_path: Path) -> None:
    """Runner discovers .xlsx files placed in the workbooks directory."""
    for rel in [
        "config/methods/cfir_directed_content_analysis_v1.yaml",
        "config/frameworks/cfir_v1.yaml",
        "config/pipelines/workbook_cfir.yaml",
        "config/prompt_sets/cfir_final_prompts_v1.yaml",
    ]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)

    shutil.copytree(REPO_ROOT / "prompts", tmp_path / "prompts")

    workbooks_dir = tmp_path / "data" / "raw" / "workbooks"
    workbooks_dir.mkdir(parents=True)
    (workbooks_dir / "fake_1A.xlsx").write_bytes(b"")
    (workbooks_dir / "fake_2A.xlsx").write_bytes(b"")

    src = REPO_ROOT / "examples/project_template/project.yaml"
    manifest = yaml.safe_load(src.read_text())
    manifest["paths"]["raw_workbooks"] = str(workbooks_dir)

    dest_dir = tmp_path / "examples" / "project_template"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "project.yaml"
    dest.write_text(yaml.dump(manifest))

    runner = ProjectRunner(dest)
    plan = runner.build_run_plan()
    assert plan.project_id == "amn_cfir_pilot"
    assert len(plan.discovered_inputs) == 2


def test_execute_run_plan_with_mock_provider(tmp_path: Path) -> None:
    """Full execute_run_plan with MockProvider: artifacts and manifest should be written."""
    runner = ProjectRunner(REPO_ROOT / "examples/project_template/project.yaml")
    run_id = "test_run_20260101T000000Z"
    plan = runner.build_run_plan()
    n_workbooks = len(plan.discovered_inputs)

    # Force mock provider and redirect artifacts dir so tests are hermetic.
    runner.project.provider.name = "mock"
    runner.project.paths["artifacts"] = str(tmp_path)

    manifest_path = runner.execute_run_plan(plan, run_id)

    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["run_id"] == run_id
    assert manifest["project_id"] == "amn_cfir_pilot"
    assert manifest["method_id"] == "cfir_directed_content_analysis_v1"
    assert manifest["configuration_fingerprint"]
    assert any(asset["kind"] == "method" for asset in manifest["configuration_assets"])

    # Expected artifact count:
    #   per_file stages × n_workbooks  +  bundle_all stages × 1
    llm_stages = [s for s in runner.pipeline.stages if s.enabled and s.prompt_ref]
    per_file_count = sum(1 for s in llm_stages if s.input_grouping == "per_file") * n_workbooks
    bundle_count = sum(1 for s in llm_stages if s.input_grouping == "bundle_all")
    expected = per_file_count + bundle_count
    assert len(manifest["artifact_paths"]) == expected

    # All artifact files must exist and have the right shape
    artifact_root = tmp_path / run_id
    for rel_path in manifest["artifact_paths"]:
        artifact_file = artifact_root / rel_path
        assert artifact_file.exists(), f"Missing artifact: {rel_path}"
        artifact = json.loads(artifact_file.read_text())
        assert artifact["run_id"] == run_id
        assert artifact["response_text"].startswith("MOCK RESPONSE")
        assert artifact["provider"] == "mock"
        assert artifact["prompt_sha256"] is not None
        assert artifact["input_sha256"] is not None


def test_transcript_filter_applies_to_previous_stage_outputs(tmp_path: Path) -> None:
    """Filtered resume runs should not process every previous-stage artifact."""
    for rel in [
        "config/methods/cfir_directed_content_analysis_v1.yaml",
        "config/frameworks/cfir_v1.yaml",
        "config/pipelines/transcript_cfir.yaml",
        "config/prompt_sets/cfir_final_prompts_v1.yaml",
    ]:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)

    prompt_src = REPO_ROOT / "prompts" / "cfir" / "final"
    prompt_dst = tmp_path / "prompts" / "cfir" / "final"
    shutil.copytree(prompt_src, prompt_dst)

    transcripts_dir = tmp_path / "data" / "raw" / "transcripts" / "ON AMN"
    transcripts_dir.mkdir(parents=True)
    (transcripts_dir / "1A_test.txt").write_text("Participant 1A transcript", encoding="utf-8")
    (transcripts_dir / "2A_test.txt").write_text("Participant 2A transcript", encoding="utf-8")

    manifest = yaml.safe_load((REPO_ROOT / "examples/project_template/project_transcript.yaml").read_text())
    manifest["provider"]["name"] = "mock"
    manifest["paths"]["artifacts"] = str(tmp_path / "artifacts")

    dest_dir = tmp_path / "examples" / "project_template"
    dest_dir.mkdir(parents=True)
    project_yaml = dest_dir / "project_transcript.yaml"
    project_yaml.write_text(yaml.dump(manifest))

    runner = ProjectRunner(project_yaml)
    run_id = "resume_filter_test"
    previous_dir = tmp_path / "artifacts" / run_id / "participant_parent_construct_rollup"
    previous_dir.mkdir(parents=True)

    for participant in ("1A", "2A"):
        label = f"data/raw/transcripts/ON AMN/{participant}_test.txt"
        artifact = StageArtifact(
            run_id=run_id,
            stage_id="participant_parent_construct_rollup",
            input_path=label,
            input_sha256="input-sha",
            prompt_ref="participant_parent_construct_rollup",
            prompt_sha256="prompt-sha",
            response_text=f"rollup for {participant}",
            model=None,
            provider="mock",
            timestamp_utc="2026-01-01T00:00:00+00:00",
            parsed_output=None,
        )
        (previous_dir / f"{participant}_artifact.json").write_text(
            artifact.model_dump_json(indent=2),
            encoding="utf-8",
        )

    plan = runner.build_run_plan()
    manifest_path = runner.execute_run_plan(
        plan,
        run_id,
        stage_filter=["quote_context_enrichment"],
        transcript_filter="1A",
    )

    manifest_out = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest_out["artifact_paths"]) == 1
    assert [path.replace("\\", "/") for path in manifest_out["artifact_paths"]] == [
        "quote_context_enrichment/1A_test_artifact.json"
    ]

    quote_dir = tmp_path / "artifacts" / run_id / "quote_context_enrichment"
    assert sorted(path.name for path in quote_dir.glob("*_artifact.json")) == ["1A_test_artifact.json"]
