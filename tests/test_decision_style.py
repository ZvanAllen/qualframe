"""Offline execution and provenance coverage for each coding style and split."""
import json
from pathlib import Path

import pytest
import yaml

from qualframe.app_workspace import ensure_workspace
from qualframe.configuration_lock import create_configuration_lock
from qualframe.decision_style import DECIDE_EACH_CODE_PROMPT, get_stage_prompt_path
from qualframe.evidence_review import write_evidence_review_index, load_evidence_review_records
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.models import CodingPolicy, StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.base import LLMResponse
from qualframe.qualbench import coding_profile, run_coding_set
from qualframe.study_setup import StudyWorkspace

ROOT = Path(__file__).resolve().parents[1]
TEXT = "The fictional participant sets a weekly goal. They review it each Friday."


def make_study(tmp_path, style="find_passages", split="full_codebook"):
    ensure_workspace(tmp_path, app_root=ROOT)
    workspace = StudyWorkspace(tmp_path)
    created = workspace.create(StudyCreationRequest(
        title="Synthetic decision test", data_classification="synthetic",
        template="generic_directed", include_synthetic_fixtures=False,
    ))
    project_path = tmp_path / created.project_manifest_path
    workspace.import_transcript(project_manifest_path=project_path, filename="synthetic.txt",
        content=TEXT.encode(), group_label="Synthetic", actor="Test", rationale="Offline test")
    codes = [dict(id="G1", label="Group one", definition="Heading", active=False),
             dict(id="G2", label="Group two", definition="Heading", active=False)]
    codes += [dict(id=code, label=code, definition="Synthetic " + code,
                   parent_id="G1" if code in "AB" else "G2", active=True) for code in "ABCD"]
    workspace.import_codebook(project_manifest_path=project_path, filename="synthetic.yaml",
        content=yaml.safe_dump(dict(id="synthetic-codes", version="1.0", name="Synthetic", codes=codes)).encode(),
        actor="Test", rationale="Offline test")
    project = yaml.safe_load(project_path.read_text())
    project["provider"] = dict(name="openai", model="offline-capture")
    project["cost_policy"] = None
    project["pricing_snapshot"] = None
    project_path.write_text(yaml.safe_dump(project), encoding="utf-8")
    method_path = tmp_path / project["method"]
    method = yaml.safe_load(method_path.read_text())
    method["coding"]["decision_style"] = style
    method["partitioning"] = dict(strategy=split)
    if split == "custom_groups":
        method["partitioning"]["custom_groups"] = {"first": ["A", "C"], "second": ["B", "D"]}
    method_path.write_text(yaml.safe_dump(method), encoding="utf-8")
    return project_path, method_path


def capture_run(monkeypatch, project_path, *, omitted=(), outside=False):
    runner = ProjectRunner(project_path)
    calls = []
    def complete(**kwargs):
        schema = kwargs["response_schema"]
        key = "decisions" if runner.method.coding.decision_style == "decide_each_code" else "codings"
        ids = schema["properties"][key]["items"]["properties"]["code_id"]["enum"]
        calls.append((kwargs, ids))
        if key == "decisions":
            items = [dict(code_id=code, present=code == "A", quote=TEXT if code == "A" else "",
                          rationale="Synthetic presence" if code == "A" else "Synthetic absence")
                     for code in ids if code not in omitted]
            if outside:
                items.append(dict(code_id="G1", present=False, quote="", rationale="Invalid heading"))
        else:
            items = [dict(code_id="A", quote=TEXT, rationale="Synthetic presence", meaning_unit="mu-1")] if "A" in ids else []
        return LLMResponse(text=json.dumps({key: items}), provider="openai", model="offline-capture")
    monkeypatch.setattr("qualframe.pipeline.project_runner.build_provider", lambda _: object())
    monkeypatch.setattr(runner, "_complete", complete)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, "synthetic-run")
    path = runner.execute_run_plan(plan, "synthetic-run")
    return runner, plan, path, calls


def test_default_prompt_and_lock_are_preserved_and_decisions_are_distinct(tmp_path):
    project, method_path = make_study(tmp_path)
    assert CodingPolicy().decision_style == "find_passages"
    first = create_configuration_lock(project)
    runner = ProjectRunner(project)
    stage = runner.pipeline.stages[0]
    default_prompt = get_stage_prompt_path(tmp_path, tmp_path / runner.framework.prompt_set, stage, runner.method)
    assert default_prompt.relative_to(tmp_path).as_posix() == "prompts/directed/v3/directed_coding.md"
    # Missing new key has exactly the old prompt semantics.
    method = yaml.safe_load(method_path.read_text())
    method["coding"].pop("decision_style")
    method_path.write_text(yaml.safe_dump(method), encoding="utf-8")
    legacy = ProjectRunner(project)
    assert legacy.method.coding.decision_style == "find_passages"
    assert get_stage_prompt_path(tmp_path, tmp_path / legacy.framework.prompt_set, stage, legacy.method) == default_prompt
    method["coding"]["decision_style"] = "decide_each_code"
    method_path.write_text(yaml.safe_dump(method), encoding="utf-8")
    second = create_configuration_lock(project)
    assert first.fingerprint_sha256 != second.fingerprint_sha256
    old_prompt = next(asset for asset in first.assets if asset.kind == "prompt")
    new_prompt = next(asset for asset in second.assets if asset.kind == "prompt")
    assert new_prompt.path == DECIDE_EACH_CODE_PROMPT
    assert old_prompt.sha256 != new_prompt.sha256
    assert next(a for a in first.assets if a.kind == "method").sha256 != next(a for a in second.assets if a.kind == "method").sha256
    path = tmp_path / DECIDE_EACH_CODE_PROMPT
    path.write_text(path.read_text() + "\nSynthetic hash check.\n", encoding="utf-8")
    assert create_configuration_lock(project).fingerprint_sha256 != second.fingerprint_sha256


@pytest.mark.parametrize("style", ["find_passages", "decide_each_code"])
@pytest.mark.parametrize("split,expected", [("full_codebook", [list("ABCD")]),
    ("custom_groups", [list("AC"), list("BD")]), ("per_top_level_category", [list("AB"), list("CD")])])
def test_style_executes_each_partition_with_only_active_codes(tmp_path, monkeypatch, style, split, expected):
    project, _ = make_study(tmp_path, style, split)
    runner, plan, path, calls = capture_run(monkeypatch, project)
    assert [ids for _, ids in calls] == expected
    for kwargs, ids in calls:
        prompt = kwargs["user_prompt"]
        assert ("decide every code, version 1" in prompt) == (style == "decide_each_code")
        book = json.loads(prompt.rsplit("Codebook:\n\n", 1)[1])
        assert [code["id"] for code in book["codes"]] == ids
        assert all(code["active"] for code in book["codes"])
    manifest = json.loads(path.read_text())
    assert manifest["status"] == "completed"
    assert manifest["no_decision_count"] == 0
    index = write_evidence_review_index(project_manifest_path=project, run_id="synthetic-run")
    records = load_evidence_review_records(index)
    assert sum(record.record_kind == "evidence" for record in records) == 1
    assert sum(record.record_kind == "absence" for record in records) == (3 if style == "decide_each_code" else 0)
    artifact = json.loads((path.parent / manifest["artifact_paths"][0]).read_text())
    prompt_asset = next(a for a in manifest["configuration_assets"] if a["kind"] == "prompt")
    assert artifact["prompt_sha256"] == sha256_for_text((tmp_path / prompt_asset["path"]).read_text(encoding="utf-8"))
    assert prompt_asset["sha256"] == sha256_for_file(tmp_path / prompt_asset["path"])
    assert json.loads((path.parent / "run_settings.json").read_text())["decision_style"] == style


@pytest.mark.parametrize("omitted", [("D",), tuple("ABCD")])
def test_missing_decisions_are_nonblocking_counted_and_resume_stable(tmp_path, monkeypatch, omitted):
    project, _ = make_study(tmp_path, "decide_each_code", "custom_groups")
    runner, plan, path, calls = capture_run(monkeypatch, project, omitted=omitted)
    manifest = json.loads(path.read_text())
    assert manifest["status"] == "completed"
    assert manifest["no_decision_count"] == len(omitted)
    assert manifest["qa_failure_count"] == len(omitted)
    index = write_evidence_review_index(project_manifest_path=project, run_id="synthetic-run")
    profile = coding_profile(run_coding_set(tmp_path, path.parent))
    assert profile["no_decision_count"] == len(omitted)
    assert profile["no_evidence_rows"] == 4 - len(omitted) - ("A" not in omitted)
    before = (path.parent / manifest["artifact_paths"][0]).read_bytes()
    runner.execute_run_plan(plan, "synthetic-run")
    after = json.loads(path.read_text())
    assert len(calls) == 2
    assert after["no_decision_count"] == len(omitted)
    assert after["qa_inventory_sha256"] == manifest["qa_inventory_sha256"]
    assert (path.parent / manifest["artifact_paths"][0]).read_bytes() == before


def test_decisions_reject_codes_not_in_the_requested_part(tmp_path, monkeypatch):
    project, _ = make_study(tmp_path, "decide_each_code")
    with pytest.raises(ValueError, match="outside the requested part"):
        capture_run(monkeypatch, project, outside=True)


@pytest.mark.parametrize("missing_book", [True, False])
def test_decisions_require_an_active_structured_codebook_before_execution(tmp_path, missing_book):
    project_path, _ = make_study(tmp_path, "decide_each_code")
    project = yaml.safe_load(project_path.read_text())
    if missing_book:
        project["codebook"] = None
        project_path.write_text(yaml.safe_dump(project), encoding="utf-8")
    else:
        path = tmp_path / project["codebook"]
        book = yaml.safe_load(path.read_text())
        for code in book["codes"]:
            code["active"] = False
        path.write_text(yaml.safe_dump(book), encoding="utf-8")
    with pytest.raises(ValueError, match="structured codebook with at least one active code"):
        ProjectRunner(project_path).build_run_plan()
