"""Create the offline demo study: six fictional interviews, a codebook, and recorded coding runs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from qualframe.app_workspace import APP_ROOT
from qualframe.evidence_review import write_evidence_review_index
from qualframe.models import CreatedStudy
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.recorded_provider import load_recording_info, recordings_root
from qualframe.study_setup import StudyWorkspace

DEMO_DATASET = "ai-scribe"
DEMO_TITLE = "AI documentation assistant (demo)"
# Recorded October 2026 over the fictional demo transcripts (see scripts/record_demo.py).
# The demo study is coded by each comparison recording that is present, oldest first, and
# then by the primary recording, so the primary run is the one opened for review and the
# last comparison is the one Compare shows first.
PRIMARY_RECORDING = "claude-sonnet-5-5-2026-10"
COMPARISON_RECORDINGS = ("gpt-oss-20b-ollama-2026-10", "gpt-6-1-sol-2026-10")
RUN_IDS = {
    "claude-sonnet-5-5-2026-10": "claude-sonnet-5-5",
    "gpt-6-1-sol-2026-10": "gpt-6-1-sol",
    "gpt-oss-20b-ollama-2026-10": "gpt-oss-20b",
}


def available_recordings(*, include_illustrative: bool = False) -> list[dict]:
    """Recordings bundled with the app. Hand-written illustrative ones are for tests unless asked for."""
    root = recordings_root()
    found = []
    for folder in sorted(root.glob("*/recording.json")) if root.exists() else []:
        try:
            info = load_recording_info(folder.parent.name)
        except (OSError, ValueError):
            continue
        if include_illustrative or info.get("kind") != "illustrative":
            found.append(info)
    return found


def _use_recording(project_path: Path, recording: str) -> None:
    data = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    data["provider"] = {"name": "recorded", "model": recording, "temperature": None, "max_tokens": 16000}
    # Recorded responses cost nothing; the template's placeholder pricing does not apply.
    data.pop("cost_policy", None)
    data.pop("pricing_snapshot", None)
    temporary = project_path.with_name(".project-demo.yaml")
    temporary.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    temporary.replace(project_path)


def run_recording(project_path: Path, recording: str, run_id: str) -> str:
    _use_recording(project_path, recording)
    runner = ProjectRunner(project_path)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, run_id)
    runner.execute_run_plan(plan, run_id)
    write_evidence_review_index(project_manifest_path=project_path, run_id=run_id)
    return run_id


def create_demo_study(workspace_root: Path, *, with_comparison: bool = True) -> tuple[CreatedStudy, Path, str]:
    """Create a fresh demo study and code it with the bundled recording. No network access."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    workspace = StudyWorkspace(workspace_root)
    created = workspace.create_from_dataset(
        dataset_root=APP_ROOT / "demo/datasets" / DEMO_DATASET,
        title=DEMO_TITLE,
        study_id=f"demo-{stamp}",
    )
    project_path = workspace_root / created.project_manifest_path
    present = {info["id"] for info in available_recordings(include_illustrative=True)}
    if with_comparison:
        for recording in COMPARISON_RECORDINGS:
            if recording in present:
                run_recording(project_path, recording, RUN_IDS.get(recording, recording))
    primary = run_recording(project_path, PRIMARY_RECORDING, RUN_IDS.get(PRIMARY_RECORDING, PRIMARY_RECORDING))
    return created, project_path, primary
