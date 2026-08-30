from pathlib import Path

from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.workspace_ui import render_workspace


ROOT = Path(__file__).resolve().parents[1]


def test_shell_escapes_project_metadata_and_preserves_engine_body():
    page = render_workspace(title="<script>", intro="<intro>", body="<section>Evidence</section>",
                            study='<study "name">', classification="synthetic", provider="mock")
    assert "<script>" not in page
    assert "&lt;study &quot;name&quot;&gt;" in page
    assert "<section>Evidence</section>" in page
    assert "Synthetic data" in page and "Offline mock" in page
    assert "Skip to content" in page and 'id="main"' in page
    assert "https://" not in page  # no remote fonts, scripts, or tracking


def test_external_provider_is_not_labelled_offline():
    page = render_workspace(title="Study", intro="", body="", study="Research",
                            classification="sensitive", provider="anthropic")
    assert "External provider configured" in page
    assert "Offline mock" not in page and "Offline cached" not in page


def test_all_workspace_pages_share_navigation_and_style():
    app = DashboardApp(ProjectRunner(ROOT / "demo/project/project_demo.yaml"))
    for page in (app.render_setup(), app.render_imports(), app.render_configure()):
        assert 'class="sidebar"' in page
        assert 'aria-label="Study navigation"' in page
        assert "Source library" in page
        assert page.count('<style>') == 1
        assert "@media(max-width:650px)" in page


def test_evidence_navigation_only_exists_when_supplied():
    kwargs = dict(title="Study", intro="", body="", study="Demo", classification="synthetic", provider="mock")
    assert "Evidence review</a>" not in render_workspace(**kwargs)
    page = render_workspace(**kwargs, active="evidence", evidence_url="/evidence?run_id=demo")
    assert 'href="/evidence?run_id=demo" class="nav-link active"' in page
