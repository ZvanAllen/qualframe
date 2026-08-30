"""Launch a fresh, synthetic, no-network study in the real local application."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qualframe.dashboard import serve_dashboard
from qualframe.evidence_review import load_evidence_review_records, write_evidence_review_index
from qualframe.models import StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.study_setup import StudyWorkspace


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--study-id", help="Optional unique ID; existing studies are never overwritten.")
    parser.add_argument("--no-serve", action="store_true", help="Build and verify the demo, then exit.")
    parser.add_argument("--dry-run", action="store_true", help="Describe the demo without writing files.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Use an unprivileged port between 1024 and 65535.")
    if args.dry_run:
        print("Plan: create a synthetic study, run the mock provider, prepare exact evidence; no external API calls.")
        return 0
    study_id = args.study_id or datetime.now(timezone.utc).strftime("demo-%Y%m%d-%H%M%S-%f")
    created = StudyWorkspace(REPO_ROOT).create(StudyCreationRequest(
        title="Community service experience", study_id=study_id,
        data_classification="synthetic", include_synthetic_fixtures=True,
    ))
    project_path = REPO_ROOT / created.project_manifest_path
    runner = ProjectRunner(project_path)
    if runner.project.provider.name != "mock" or runner.project.data_classification != "synthetic":
        raise RuntimeError("Demo must use synthetic data and the local mock provider.")
    plan = runner.build_run_plan()
    if len(plan.discovered_inputs) != 2:
        raise RuntimeError("Expected exactly two synthetic source transcripts.")
    run_id = "synthetic-review"
    runner.save_run_plan(plan, run_id)
    runner.execute_run_plan(plan, run_id)
    index = write_evidence_review_index(project_manifest_path=project_path, run_id=run_id)
    records = load_evidence_review_records(index)
    if len(records) != 4 or any(record.validation_issues for record in records):
        raise RuntimeError("Expected four source-validated synthetic review records.")
    print("Ready: 2 synthetic transcripts, 4 evidence records, no external model calls.")
    print(f"Project: {created.project_manifest_path}")
    print(f"Review: http://127.0.0.1:{args.port}/evidence?run_id={run_id}")
    print("Mock assignments demonstrate software behavior, not model accuracy. Ctrl+C stops the server.")
    if not args.no_serve:
        serve_dashboard(project_path, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
