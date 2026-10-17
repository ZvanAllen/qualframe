"""Code identity tests use disposable repositories and synthetic run metadata."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from qualframe import code_provenance
from qualframe.methods_record import build_methods_record, methods_markdown, render_methods_page
from qualframe.pipeline.project_runner import ProjectRunner


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=10,
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("Git is needed for the disposable checkout fixture")
    root = tmp_path / "code"
    package = root / "src/qualframe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# synthetic package\n", encoding="utf-8")
    (package / "code_provenance.py").write_text("# synthetic code\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "add", "src")
    _git(root, "-c", "user.name=Synthetic Test", "-c", "user.email=test@localhost",
         "-c", "commit.gpgsign=false", "commit", "-m", "synthetic fixture")
    monkeypatch.setattr(code_provenance, "__file__", str(package / "code_provenance.py"))
    return root, package, _git(root, "rev-parse", "HEAD")


def test_clean_executing_checkout_is_selected_instead_of_cwd(checkout, tmp_path, monkeypatch):
    root, _, commit = checkout
    study = tmp_path / "unrelated-study"
    study.mkdir()
    monkeypatch.chdir(study)
    # Inherited repository overrides cannot redirect code provenance.
    monkeypatch.setenv("GIT_DIR", str(study / "missing.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(study))
    index_before = (root / ".git/index").read_bytes()
    assert code_provenance.get_code_provenance() == {"git_commit": commit, "git_dirty": False}
    assert (root / ".git/index").read_bytes() == index_before


@pytest.mark.parametrize("change", ["tracked", "untracked", "staged"])
def test_dirty_checkout_records_head_and_changes(checkout, change):
    root, package, commit = checkout
    if change == "untracked":
        (root / "new-file.txt").write_text("synthetic addition", encoding="utf-8")
    else:
        (package / "__init__.py").write_text("# synthetic edit\n", encoding="utf-8")
        if change == "staged":
            _git(root, "add", "src/qualframe/__init__.py")
    assert code_provenance.get_code_provenance() == {"git_commit": commit, "git_dirty": True}


def test_source_archive_has_null_provenance_without_calling_git(tmp_path, monkeypatch):
    package = tmp_path / "archive/src/qualframe"
    package.mkdir(parents=True)
    monkeypatch.setattr(code_provenance, "__file__", str(package / "code_provenance.py"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("No checkout: Git should not be called"))
    assert code_provenance.get_code_provenance() == {"git_commit": None, "git_dirty": None}


def test_installed_package_inside_unrelated_repository_is_not_that_checkout(checkout, monkeypatch):
    root, _, _ = checkout
    installed = root / ".venv/Lib/site-packages/qualframe"
    installed.mkdir(parents=True)
    (installed / "__init__.py").write_text("# installed distribution\n", encoding="utf-8")
    monkeypatch.setattr(code_provenance, "__file__", str(installed / "code_provenance.py"))
    assert code_provenance.get_code_provenance() == {"git_commit": None, "git_dirty": None}


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("git", 5),
                                     subprocess.CalledProcessError(128, "git")])
def test_git_unavailable_or_unreadable_is_harmless(checkout, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(subprocess, "run", fail)
    assert code_provenance.get_code_provenance() == {"git_commit": None, "git_dirty": None}


def test_unborn_repository_does_not_claim_known_identity(checkout):
    root, package, _ = checkout
    unborn = root / "unborn"
    unborn_package = unborn / "src/qualframe"
    unborn_package.mkdir(parents=True)
    (unborn_package / "__init__.py").write_text("# no commits\n", encoding="utf-8")
    _git(unborn, "init")
    _git(unborn, "add", "src")
    # The fixture's executing checkout is retained; this test's inner package is
    # selected explicitly below so its missing HEAD cannot fall back to a parent.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(code_provenance, "__file__", str(unborn_package / "code_provenance.py"))
        assert code_provenance.get_code_provenance() == {"git_commit": None, "git_dirty": None}


def test_run_settings_record_identity_once_and_preserve_it_on_resume(tmp_path, monkeypatch):
    original = {"git_commit": "a" * 40, "git_dirty": True}
    monkeypatch.setattr(code_provenance, "get_code_provenance", lambda: original)
    runner = object.__new__(ProjectRunner)
    runner.project = SimpleNamespace(provider=SimpleNamespace(model_dump=lambda **kw: {"name": "mock"}))
    runner.method = None
    runner.codebook = None
    runner._record_run_settings(tmp_path, "synthetic-run")
    path = tmp_path / "run_settings.json"
    first_bytes = path.read_bytes()
    settings = json.loads(first_bytes)
    assert settings["qualframe_version"]
    assert {key: settings[key] for key in original} == original
    monkeypatch.setattr(code_provenance, "get_code_provenance", lambda: pytest.fail("Resume must preserve original provenance"))
    runner._record_run_settings(tmp_path, "synthetic-run")
    assert path.read_bytes() == first_bytes


@pytest.mark.parametrize("settings, commit_label, dirty_label", [
    ({"qualframe_version": "0.11.0", "git_commit": "b" * 40, "git_dirty": True}, "b" * 40, "yes"),
    ({"qualframe_version": "0.11.0", "git_commit": "b" * 40, "git_dirty": False}, "b" * 40, "no"),
    ({"qualframe_version": "0.11.0", "git_commit": None, "git_dirty": None}, "not recorded", "not recorded"),
    ({"qualframe_version": "0.10.0"}, "not recorded", "not recorded"),
    ({}, "not recorded", "not recorded"),
])
def test_methods_json_markdown_and_page_use_saved_identity(tmp_path, monkeypatch, settings, commit_label, dirty_label):
    root = tmp_path / "artifacts/synthetic-run"
    root.mkdir(parents=True)
    settings_path = root / "run_settings.json"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    original = settings_path.read_bytes()
    app = SimpleNamespace(
        artifacts_dir=root.parent, review_dir=tmp_path / "review", repo_root=tmp_path,
        runner=SimpleNamespace(project=SimpleNamespace(title="Synthetic study", project_id="synthetic", data_classification="synthetic"), codebook=None),
        _run_root=lambda artifacts, run: artifacts / run,
        _managed_project_path=lambda: tmp_path / "no-project.yaml",
        _render_workspace_page=lambda **kwargs: kwargs["body"],
    )
    monkeypatch.setattr(code_provenance, "get_code_provenance", lambda: pytest.fail("Methods must not backfill current identity"))
    record = build_methods_record(app, "synthetic-run")
    assert record["git_commit"] == settings.get("git_commit")
    assert record["git_dirty"] == settings.get("git_dirty")
    json_record = json.loads(json.dumps(record))
    assert json_record["git_commit"] == record["git_commit"]
    assert json_record["git_dirty"] is record["git_dirty"]
    markdown = methods_markdown(record)
    assert f"- Git commit: {commit_label}" in markdown
    assert f"- Uncommitted code changes: {dirty_label}" in markdown
    page = render_methods_page(app, "synthetic-run")
    assert f"<th>Git commit</th><td>{commit_label}</td>" in page
    assert f"<th>Uncommitted code changes</th><td>{dirty_label}</td>" in page
    assert settings_path.read_bytes() == original
