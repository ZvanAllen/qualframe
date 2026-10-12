from pathlib import Path

import pytest

from qualframe.app_workspace import ensure_workspace
from qualframe.dashboard import DashboardApp
from qualframe.demo_study import create_demo_study
from qualframe.evidence_review import load_evidence_review_records
from qualframe.methods_record import build_methods_record
from qualframe.pipeline.project_runner import ProjectRunner


@pytest.mark.parametrize("seconds, expected", [([], None), ([10], 10), ([30, 10, 20], 20), ([10, 30], 20)])
def test_methods_record_reports_median_review_time(tmp_path: Path, seconds, expected):
    root = ensure_workspace(tmp_path / "ws").root
    _, project, run_id = create_demo_study(root, with_comparison=False)
    app = DashboardApp(ProjectRunner(project))
    records = load_evidence_review_records(app.artifacts_dir / run_id / "evidence_review/index.json")
    for record, duration in zip(records, seconds):
        app.handle_action("/evidence-action", {
            "run_id": [run_id], "item": [record.record_id], "decision": ["accept"],
            "reviewer": ["Ada"], "seconds_on_item": [str(duration)],
        })
    review = build_methods_record(app, run_id)["review"]
    assert review["timed_decisions"] == len(seconds)
    assert review["median_seconds_per_decision"] == expected
