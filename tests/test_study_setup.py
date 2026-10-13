from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from qualframe.dashboard import DashboardApp
from qualframe.config import load_project_manifest
from qualframe.models import MethodPolicyUpdate, StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.study_setup import StudyWorkspace, slugify_study_id
from qualframe.web_forms import UploadedFile


REPO_ROOT = Path(__file__).resolve().parents[1]


def make_test_repo(tmp_path: Path) -> Path:
    for directory in ("config", "prompts"):
        shutil.copytree(REPO_ROOT / directory, tmp_path / directory)
    shutil.copytree(
        REPO_ROOT / "demo" / "fixtures",
        tmp_path / "demo" / "fixtures",
    )
    return tmp_path


def test_slugify_study_id_is_safe_and_readable() -> None:
    assert slugify_study_id("Community Service Experience 2026") == (
        "community-service-experience-2026"
    )
    assert slugify_study_id("!!!").startswith("study-")


def test_create_generic_synthetic_study_is_runnable(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(repo_root)
    created = workspace.create(
        StudyCreationRequest(
            title="Synthetic Community Study",
            data_classification="synthetic",
            template="generic_directed",
            include_synthetic_fixtures=True,
        )
    )

    project_path = repo_root / created.project_manifest_path
    runner = ProjectRunner(project_path)
    plan = runner.build_run_plan()
    transcript_inputs = [item for item in plan.discovered_inputs if item.kind == "transcript"]

    assert created.study_id == "synthetic-community-study"
    assert created.imported_source_count == 3
    assert runner.project.data_classification == "synthetic"
    assert runner.project.source_manifest.endswith("source_import_manifest.jsonl")
    assert runner.project.provider.name == "mock"
    assert runner.method.id == "synthetic-community-study_method_v1"
    assert len(transcript_inputs) == 2
    assert all(item.sha256 for item in transcript_inputs)

    run_id = "setup-smoke"
    runner.save_run_plan(plan, run_id)
    manifest_path = runner.execute_run_plan(plan, run_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["run_cost_usd"] == 0
    assert len(manifest["artifact_paths"]) == 2

    imports = (
        project_path.parent / "source_import_manifest.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(imports) == 3
    assert all(json.loads(line)["sha256"] for line in imports)


def test_create_cfir_study_preserves_domain_iterations(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    created = StudyWorkspace(repo_root).create(
        StudyCreationRequest(
            title="Synthetic CFIR Study",
            study_id="synthetic-cfir-study",
            data_classification="synthetic",
            template="cfir",
            include_synthetic_fixtures=True,
        )
    )

    runner = ProjectRunner(repo_root / created.project_manifest_path)
    plan = runner.build_run_plan()
    first_stage = [
        item for item in plan.planned_stage_runs if item.stage_id == "transcript_to_cfir"
    ]
    assert runner.project.provider.name == "cached_demo"
    assert len(first_stage) == 12
    assert {item.domain for item in first_stage} == set(runner.framework.domains)


def test_new_study_dashboard_creates_dry_run_plan_without_execution(
    tmp_path: Path,
) -> None:
    repo_root = make_test_repo(tmp_path)
    created = StudyWorkspace(repo_root).create(
        StudyCreationRequest(
            title="Setup Interface Study",
            data_classification="synthetic",
            include_synthetic_fixtures=True,
        )
    )
    app = DashboardApp(ProjectRunner(repo_root / created.project_manifest_path))

    page = app.render()
    assert "Setup Interface Study" in page
    assert "Run AI coding" in page
    assert "Offline demo model" in page

    run_id, message = app.handle_action("/plan", {})
    assert "No model request was sent" in message
    plan_path = repo_root / "studies" / created.study_id / "artifacts" / run_id / "run_plan.json"
    assert plan_path.exists()
    planned_page = app.render(run_id=run_id)
    assert "Dry-run plan" in planned_page
    assert "No model request was sent" in planned_page


def test_setup_rejects_duplicate_and_misclassified_fixtures(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(repo_root)
    request = StudyCreationRequest(
        title="Repeatable Study",
        data_classification="synthetic",
    )
    workspace.create(request)
    with pytest.raises(FileExistsError):
        workspace.create(request)

    with pytest.raises(ValidationError, match="synthetic starter materials"):
        StudyCreationRequest(
            title="Sensitive Study",
            data_classification="sensitive",
            include_synthetic_fixtures=True,
        )


def test_managed_study_imports_are_validated_versioned_and_audited(
    tmp_path: Path,
) -> None:
    repo_root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(repo_root)
    created = workspace.create(
        StudyCreationRequest(
            title="Researcher Import Study",
            data_classification="synthetic",
            include_synthetic_fixtures=True,
        )
    )
    project_path = repo_root / created.project_manifest_path

    transcript = workspace.import_transcript(
        project_manifest_path=project_path,
        filename="SYN-03.txt",
        content=b"Interviewer: What helped?\nParticipant: Clear reminders helped.",
        group_label="Pilot Group",
        actor="researcher",
        rationale="Add the approved synthetic test transcript.",
    )
    assert transcript.provenance == "researcher_import"
    assert (repo_root / transcript.destination_path).exists()
    with pytest.raises(FileExistsError):
        workspace.import_transcript(
            project_manifest_path=project_path,
            filename="SYN-03.txt",
            content=b"duplicate",
            group_label="Pilot Group",
            actor="researcher",
            rationale="Duplicate check.",
        )

    codebook_yaml = b"""id: imported_service_codebook
version: 1.0.0
name: Imported service codebook
codes:
  - id: communication
    label: Communication
    definition: Clarity and responsiveness in communication.
"""
    codebook = workspace.import_codebook(
        project_manifest_path=project_path,
        filename="service-codebook.yaml",
        content=codebook_yaml,
        actor="researcher",
        rationale="Use the reviewed project-specific codebook.",
    )
    project = load_project_manifest(project_path)
    assert project.codebook.endswith("config/codebook_v2.yaml")
    assert codebook.source_kind == "codebook"

    metadata = workspace.import_metadata(
        project_manifest_path=project_path,
        filename="study-metadata.csv",
        content=(
            b"source_filename,study_group,time_point\n"
            b"SYN-01.txt,Alpha,Baseline\n"
            b"SYN-02.txt,Beta,Baseline\n"
            b"SYN-03.txt,Pilot,Follow-up\n"
        ),
        actor="researcher",
        rationale="Link approved study metadata to imported transcripts.",
    )
    project = load_project_manifest(project_path)
    assert project.metadata_file.endswith("data/reference/metadata_v1.csv")
    assert metadata.source_kind == "metadata"

    method_path = workspace.update_method_policy(
        project_manifest_path=project_path,
        update=MethodPolicyUpdate(
            segmentation_strategy="sentence",
            context_before=2,
            context_after=2,
            coding_cardinality="single_label",
            allow_overlapping_spans=False,
            partition_strategy="full_codebook",
        ),
        actor="researcher",
        rationale="Use sentence units and one code per unit for calibration.",
    )
    runner = ProjectRunner(project_path)
    assert method_path.name == "method_v2.yaml"
    assert runner.method.coding.cardinality == "single_label"
    assert runner.method.coding.max_codes_per_unit == 1
    assert runner.method.segmentation.strategy == "sentence"
    assert runner.configuration_lock.fingerprint_sha256

    changes = (
        project_path.parent / "logs/study_changes.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["change_kind"] for line in changes] == [
        "codebook_import",
        "metadata_import",
        "method_update",
    ]


def test_metadata_import_rejects_unknown_transcript(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(repo_root)
    created = workspace.create(
        StudyCreationRequest(
            title="Metadata Validation Study",
            data_classification="synthetic",
            include_synthetic_fixtures=True,
        )
    )
    with pytest.raises(ValueError, match="not imported"):
        workspace.import_metadata(
            project_manifest_path=repo_root / created.project_manifest_path,
            filename="metadata.csv",
            content=b"source_filename,group\nMISSING.txt,Unknown\n",
            actor="researcher",
            rationale="Validate linkage.",
        )


def test_dashboard_import_and_method_editor_change_real_run_plan(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    created = StudyWorkspace(repo_root).create(
        StudyCreationRequest(
            title="Interface Policy Study",
            data_classification="synthetic",
            include_synthetic_fixtures=False,
        )
    )
    app = DashboardApp(ProjectRunner(repo_root / created.project_manifest_path))

    import_page = app.render_imports()
    assert "Add transcripts" in import_page
    assert "Transcript" in import_page
    codebook = (repo_root / "config/codebooks/example_directed_codebook_v1.yaml").read_bytes()
    app.handle_upload("/import/codebook", {"actor": ["researcher"], "rationale": ["Starter codebook."]},
                      {"upload": UploadedFile(filename="codebook.yaml", content_type="text/yaml", content=codebook)})
    message = app.handle_upload(
        "/import/transcript",
        {
            "group_label": ["Pilot"],
            "actor": ["researcher"],
            "rationale": ["Add an approved synthetic transcript."],
        },
        {
            "upload": UploadedFile(
                filename="SYN-UI-01.txt",
                content_type="text/plain",
                content=b"Interviewer: What helped?\nParticipant: Clear reminders helped.",
            )
        },
    )
    assert "Imported SYN-UI-01.txt" in message

    method_page = app.render_configure()
    assert "Run coding" in method_page
    assert "One request per top-level category" in method_page
    method_message = app.handle_method_update(
        {
            "segmentation_strategy": ["sentence"],
            "context_before": ["1"],
            "context_after": ["1"],
            "coding_cardinality": ["single_label"],
            "partition_strategy": ["per_top_level_category"],
            "actor": ["researcher"],
            "rationale": ["Test top-level partitioning and one-code policy."],
        }
    )
    assert "new method version" in method_message

    plan = app.runner.build_run_plan()
    assert len(plan.planned_stage_runs) == 2
    assert {item.domain for item in plan.planned_stage_runs} == {"access", "experience"}
    assert app.runner.method.coding.cardinality == "single_label"
    assert app.runner.method.segmentation.strategy == "sentence"


def test_dashboard_runs_managed_mock_plan_in_background(tmp_path: Path) -> None:
    repo_root = make_test_repo(tmp_path)
    created = StudyWorkspace(repo_root).create(
        StudyCreationRequest(
            title="Background Mock Study",
            data_classification="synthetic",
            include_synthetic_fixtures=True,
        )
    )
    app = DashboardApp(ProjectRunner(repo_root / created.project_manifest_path))
    run_id = "browser-mock-run"
    plan = app.runner.build_run_plan()
    app.runner.save_run_plan(plan, run_id)

    planned_page = app.render(run_id=run_id)
    assert "Run locally with mock" in planned_page
    selected, message = app.handle_action("/execute", {"run_id": [run_id]})
    assert selected == run_id
    assert "background execution" in message

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = app._job_snapshot(run_id)
        if job is not None and job.status != "running":
            break
        time.sleep(0.01)
    else:
        pytest.fail("local mock execution did not finish")

    manifest_path = (
        repo_root / "studies" / created.study_id / "artifacts" / run_id / "run_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["run_cost_usd"] == 0
    assert "Status" in app.render(run_id=run_id)


def test_a_study_of_published_documents_is_treated_as_real_data(tmp_path):
    from qualframe.models import StudyCreationRequest
    from qualframe.study_setup import StudyWorkspace

    root = make_test_repo(tmp_path)
    created = StudyWorkspace(root).create(StudyCreationRequest(title="Published reports", data_classification="published"))
    import yaml
    manifest = yaml.safe_load((root / created.project_manifest_path).read_text(encoding="utf-8"))
    assert manifest["data_classification"] == "published"
    with pytest.raises(ValueError):
        StudyCreationRequest(title="Fixtures", data_classification="published", include_synthetic_fixtures=True)
