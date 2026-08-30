from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qualframe.adjudication import load_adjudication_actions
from qualframe.dashboard import DashboardApp, make_handler
from qualframe.models import CostPauseRecord, RunManifest
from qualframe.pipeline.project_runner import ProjectRunner


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_PROJECT = REPO_ROOT / "demo/project/project_demo.yaml"


def test_local_dashboard_renders_run_and_records_adjudication(tmp_path: Path) -> None:
    runner = ProjectRunner(DEMO_PROJECT)
    runner.project.paths["artifacts"] = str(tmp_path / "artifacts")
    runner.project.paths["review_queue"] = str(tmp_path / "review_queue")
    runner.project.paths["exports"] = str(tmp_path / "exports")
    run_id = "dashboard-run"
    artifact_root = tmp_path / "artifacts" / run_id
    review_root = tmp_path / "review_queue" / run_id
    artifact_root.mkdir(parents=True)
    review_root.mkdir(parents=True)
    manifest = RunManifest(
        run_id=run_id,
        project_id=runner.project.project_id,
        framework_id=runner.framework.id,
        pipeline_id=runner.pipeline.id,
        completed_at_utc="2026-08-02T00:00:00+00:00",
        artifact_paths=[],
        qa_failure_count=1,
    )
    (artifact_root / "run_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    (review_root / "item.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "stage_id": "cross_network_synthesis",
                "rule_id": "one_network_one_valence",
                "reason": "Synthetic conflict",
            }
        ),
        encoding="utf-8",
    )

    app = DashboardApp(runner)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base_url + "/", timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "Study workspace" in page
        assert "one_network_one_valence" in page
        assert "loopback-only" in page
        assert ('href="/presentation"' in page) == (REPO_ROOT / "demo/presentation/index.html").exists()
        assert "/setup" in page

        with urlopen(base_url + "/setup", timeout=5) as response:
            setup_page = response.read().decode("utf-8")
        assert "Create a study" in setup_page
        assert "No model request is made during setup" in setup_page
        assert "Directed content analysis" in setup_page

        form = urlencode(
            {
                "run_id": run_id,
                "item": "item.json",
                "decision": "approve",
                "reviewer": "dashboard-reviewer",
                "rationale": "Approve the synthetic test item.",
                "edited_row_json": "",
            }
        ).encode()
        request = Request(base_url + "/adjudicate", data=form, method="POST")
        with urlopen(request, timeout=5) as response:
            redirected_page = response.read().decode("utf-8")
        assert "Recorded adjudication action" in redirected_page
        actions = load_adjudication_actions(review_root)
        assert len(actions) == 1
        assert actions[0].decision == "approve"

        with urlopen(
            base_url + "/file?path=review_queue/dashboard-run/item.json", timeout=5
        ) as response:
            downloaded = json.loads(response.read().decode("utf-8"))
        assert downloaded["reason"] == "Synthetic conflict"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_dashboard_exposes_cost_pause_and_records_decision(tmp_path: Path) -> None:
    runner = ProjectRunner(DEMO_PROJECT)
    runner.project.paths["artifacts"] = str(tmp_path / "artifacts")
    runner.project.paths["review_queue"] = str(tmp_path / "review_queue")
    runner.project.paths["exports"] = str(tmp_path / "exports")
    runner.project.paths["logs"] = str(tmp_path / "logs")
    run_id = "cost-paused-run"
    artifact_root = tmp_path / "artifacts" / run_id
    artifact_root.mkdir(parents=True)
    pause = CostPauseRecord(
        project_id=runner.project.project_id,
        run_id=run_id,
        stage_id="directed_coding",
        input_label="synthetic-01",
        current_cost_usd=18.5,
        projected_cost_usd=21.25,
        threshold_usd=20,
        absolute_limit_usd=100,
        notification_adapter="email",
        notification_status="not_configured",
        created_at_utc="2026-08-02T00:00:00+00:00",
    )
    (artifact_root / "cost_pause.json").write_text(
        pause.model_dump_json(indent=2), encoding="utf-8"
    )

    app = DashboardApp(runner)
    page = app.render(run_id=run_id)
    assert "Paused for cost approval" in page
    assert "USD 21.2500" in page
    assert "No request was sent" in page

    selected, message = app.handle_action(
        "/cost",
        {
            "run_id": [run_id],
            "threshold_usd": ["20.0"],
            "decision": ["approve"],
            "reviewer": ["researcher"],
            "rationale": ["Approve the next bounded synthetic request."],
        },
    )

    assert selected == run_id
    assert "Recorded cost decision" in message
    approval_line = (tmp_path / "logs" / "cost_approvals.jsonl").read_text(
        encoding="utf-8"
    )
    approval = json.loads(approval_line)
    assert approval["decision"] == "approve"
    assert approval["threshold_usd"] == 20
