from pathlib import Path

import pytest
import yaml

from qualframe.coding_instructions import current_instructions, save_instructions, use_instructions
from qualframe.dashboard import DashboardApp
from qualframe.models import StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.study_setup import StudyWorkspace
from test_study_setup import make_test_repo


def _app(tmp_path: Path, *, template: str = "generic_directed") -> DashboardApp:
    root = make_test_repo(tmp_path)
    created = StudyWorkspace(root).create(StudyCreationRequest(
        title="Synthetic decision style settings", data_classification="synthetic",
        template=template, include_synthetic_fixtures=False,
    ))
    return DashboardApp(ProjectRunner(root / created.project_manifest_path))


def _form(style: str | None = "decide_each_code", partition: str = "full_codebook") -> dict[str, list[str]]:
    result = {
        "segmentation_strategy": ["model_proposed"], "context_before": ["1"], "context_after": ["1"],
        "coding_cardinality": ["multi_label"], "partition_strategy": [partition],
        "actor": ["Synthetic researcher"], "rationale": ["Check style versioning without model calls."],
    }
    if style is not None:
        result["coding_decision_style"] = [style]
    return result


def test_style_form_versions_method_and_preserves_default_instructions(tmp_path: Path) -> None:
    app = _app(tmp_path)
    project_path = app._managed_project_path()
    previous = app.repo_root / app.runner.project.method
    previous_bytes = previous.read_bytes()
    _, original_prompt, original_text, _ = current_instructions(app.repo_root, project_path)
    page = app.render_configure()
    assert 'value="find_passages" checked' in page
    assert 'value="decide_each_code"' in page
    assert "fewer, stronger codings." in page
    assert "more complete; suited to checklists such as CFIR or BCT annotation. It costs a little more output." in page

    app.handle_method_update(_form())
    assert app.runner.method.coding.decision_style == "decide_each_code"
    assert app.runner.method.evidence_location == "unique_exact_quote"
    assert app.runner.project.method.endswith("method_v2.yaml")
    assert previous.read_bytes() == previous_bytes
    _, decision_prompt, decision_text, _ = current_instructions(app.repo_root, project_path)
    assert decision_prompt != original_prompt
    assert '"decisions"' in decision_text
    page = app.render_configure()
    assert 'value="decide_each_code" checked' in page
    assert "readonly" in page
    assert 'action="/instructions/save"' not in page
    assert "Your Find passages that fit instructions are kept" in page

    # Saving unrelated options from an older client must not reset the selected style.
    app.handle_method_update(_form(None))
    assert app.runner.method.coding.decision_style == "decide_each_code"
    app.handle_method_update(_form("find_passages"))
    assert current_instructions(app.repo_root, project_path)[1:3] == (original_prompt, original_text)
    assert 'action="/instructions/save"' in app.render_configure()


def test_style_change_keeps_custom_groups(tmp_path: Path) -> None:
    app = _app(tmp_path)
    method_path = app.repo_root / app.runner.project.method
    data = yaml.safe_load(method_path.read_text(encoding="utf-8"))
    groups = {"First group": ["synthetic_a"], "Second group": ["synthetic_b"]}
    data["partitioning"] = {"strategy": "custom_groups", "custom_groups": groups}
    method_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    app._refresh_runner()
    page = app.render_configure()
    assert 'value="custom_groups" selected' in page
    assert "one request per custom group" in page
    app.handle_method_update(_form(partition="custom_groups"))
    assert app.runner.method.partitioning.strategy == "custom_groups"
    assert app.runner.method.partitioning.custom_groups == groups
    assert app.runner.method.coding.decision_style == "decide_each_code"


def test_cfir_reference_does_not_offer_or_accept_style_change(tmp_path: Path) -> None:
    app = _app(tmp_path, template="cfir")
    previous = app.runner.project.method
    page = app.render_configure()
    assert 'name="coding_decision_style"' not in page
    assert "asks for a decision on every construct using its published instructions" in page
    with pytest.raises(ValueError, match="CFIR reference workflow keeps its published"):
        app.handle_method_update(_form())
    assert app.runner.project.method == previous
    assert not (app._managed_project_path().parent / "config/method_v2.yaml").exists()


def test_decision_instructions_cannot_be_edited_or_switched_and_custom_prompt_is_kept(tmp_path: Path) -> None:
    app = _app(tmp_path)
    project_path = app._managed_project_path()
    original_text = current_instructions(app.repo_root, project_path)[2]
    custom_ref = save_instructions(
        app.study_workspace, project_path, text=original_text + "\nKeep synthetic examples brief.\n",
        label="Synthetic custom instructions", actor="Synthetic researcher", rationale="Offline test.",
    )
    app._refresh_runner()
    custom_prompt = current_instructions(app.repo_root, project_path)
    app.handle_method_update(_form())
    decision_text = current_instructions(app.repo_root, project_path)[2]
    with pytest.raises(ValueError, match="uses fixed instructions"):
        save_instructions(app.study_workspace, project_path, text=decision_text + "\nEdit\n", label="Blocked",
                          actor="Synthetic researcher", rationale="Offline test.")
    with pytest.raises(ValueError, match="uses fixed instructions"):
        use_instructions(app.study_workspace, project_path, framework_ref=custom_ref,
                         actor="Synthetic researcher", rationale="Offline test.")
    app.handle_method_update(_form("find_passages"))
    assert current_instructions(app.repo_root, project_path) == custom_prompt
