from pathlib import Path

from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.workspace_ui import Step, render_workspace


ROOT = Path(__file__).resolve().parents[1]


def test_shell_escapes_project_metadata_and_preserves_engine_body():
    page = render_workspace(title="<script>", intro="<intro>", body="<section>Evidence</section>",
                            study='<study "name">', classification="synthetic", provider="mock")
    assert "<script>" not in page
    assert "&lt;study &quot;name&quot;&gt;" in page
    assert "<section>Evidence</section>" in page
    assert "Synthetic data" in page and "Offline demo model" in page
    assert "Skip to content" in page and 'id="main"' in page
    assert "https://" not in page  # no remote fonts, scripts, or tracking


def test_external_provider_is_not_labelled_offline():
    page = render_workspace(title="Study", intro="", body="", study="Research",
                            classification="sensitive", provider="anthropic")
    assert "External provider configured" in page
    assert "Offline" not in page


def test_home_shell_has_no_study_navigation():
    page = render_workspace(title="", intro="", body="<p>Home</p>", study=None, active="home")
    assert 'class="studybar"' not in page and "All studies" in page


def test_all_workspace_pages_share_navigation_and_style():
    app = DashboardApp(ProjectRunner(ROOT / "demo/project/project_demo.yaml"))
    for page in (app.render_setup(), app.render_imports(), app.render_configure(), app.render_codebook()):
        assert 'class="studybar"' in page
        assert 'aria-label="Study navigation"' in page
        assert "Sources" in page and "Codebook" in page
        assert page.count('href="/static/workspace.css"') == 1


def test_steps_mark_the_current_page_and_completion():
    steps = [Step("imports", "Sources", "/imports", "2 transcripts", "done"),
             Step("evidence", "Review", "/evidence?run_id=demo", "0 of 4 decided", "next")]
    page = render_workspace(title="Review", intro="", body="", study="Demo", classification="synthetic",
                            provider="mock", active="evidence", steps=steps)
    assert 'href="/evidence?run_id=demo" aria-current="page"' in page
    assert 'class="step done"' in page and 'class="step next"' in page
