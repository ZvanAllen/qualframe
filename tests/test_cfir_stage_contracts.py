"""Opt-in CFIR contracts use synthetic outputs and never call external providers."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from qualframe.config import load_stage_output_spec
from qualframe.configuration_lock import create_configuration_lock
from qualframe.io.files import sha256_for_file
from qualframe.models import StageArtifact, StageOutputRule
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.base import LLMResponse
from qualframe.qa.inventory import review_item_paths
from qualframe.structured_output import scoped_contract_sha256, validate_stage_output


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_stage_output_spec(ROOT / "config/schemas/cfir_stage_outputs_v2.yaml")
STAGES = list(SPEC.stages)
DOMAINS = ["Innovation", "Outer Setting", "Inner Setting", "Individuals", "Implementation Process"]


def rows_for(stage, domains=None):
    domains = domains or (DOMAINS if stage == STAGES[3] else ["Innovation"] if stage == STAGES[4] else DOMAINS + ["Outcomes Addendum"])
    tables = {}
    for domain in domains:
        row = dict.fromkeys(SPEC.stages[stage].required_columns, "Synthetic value")
        row.update({"CFIR Domain": domain, "CFIR Construct": "Synthetic construct"})
        if stage == STAGES[3]:
            row["Source File(s)"] = "1A; 2A"
        if stage == STAGES[4]:
            row.update({
                "Facilitator Networks": "ON AMN; BC AMN", "Barrier Networks": "",
                "Mixed Networks": "", "Neutral/Unclear Networks": "",
                "Overall Valence": "Facilitator", "Source File(s)": "ON AMN; BC AMN",
            })
        tables[domain] = [row]
    return tables


def markdown(tables):
    parts = []
    for sheet, rows in tables.items():
        keys = list(rows[0])
        parts.append(f"## Sheet: {sheet}\n| " + " | ".join(keys) + " |\n| " + " | ".join("---" for _ in keys) + " |")
        parts.extend("| " + " | ".join(row[key] for key in keys) + " |" for row in rows)
    return "\n".join(parts)


def fixture_runner(tmp_path, *, scoped=True):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    path = tmp_path / "examples/project/project.yaml"
    path.parent.mkdir(parents=True)
    project = yaml.safe_load((ROOT / "examples/project_template/project_transcript_scoped.yaml").read_text())
    project["governance"]["enforce_review_gates"] = False
    project["structured_output"]["enforce"] = scoped
    path.write_text(yaml.safe_dump(project), encoding="utf-8")
    for directory in project["paths"].values():
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for network, source in [("ON AMN", "1A"), ("BC AMN", "2A")]:
        folder = tmp_path / "data/raw/transcripts" / network
        folder.mkdir()
        (folder / f"{source}_synthetic.txt").write_text("A fictional interview for a structural test.")
    return ProjectRunner(path)


def fake_completion(**kwargs):
    stage = kwargs["stage_id"]
    domains = [kwargs["input_label"].rsplit("::", 1)[1]] if stage == STAGES[0] else None
    return LLMResponse(text=markdown(rows_for(stage, domains)), provider="mock", model="mock")


@pytest.mark.parametrize("stage", STAGES)
def test_v2_accepts_preserved_prompt_column_contract(stage):
    assert validate_stage_output(stage, rows_for(stage), SPEC) == []
    prompt_paths = [
        "01_code_to_domain.md", "02_subconstruct_rollup.md", "03_add_context.md",
        "04_group_level_synthesis.md", "05_final_synthesis.md",
    ]
    prompt = (ROOT / "prompts/cfir/final" / prompt_paths[STAGES.index(stage)]).read_text(encoding="utf-8")
    if stage == STAGES[4]:
        section = prompt.split("OUTPUT COLUMNS (EXACT ORDER)", 1)[1].split("QUOTE HANDLING", 1)[0]
        assert [item.strip() for item in section.strip().split("|")] == SPEC.stages[stage].required_columns
    elif stage != STAGES[2]:
        assert " | ".join(SPEC.stages[stage].required_columns) in prompt
    else:
        assert ", ".join(SPEC.stages[stage].required_columns) in prompt


@pytest.mark.parametrize("stage", STAGES[:3])
def test_page_number_is_required_without_claiming_its_value_is_accurate(stage):
    tables = rows_for(stage)
    tables["Innovation"][0].pop("Page Number")
    assert any("missing columns: Page Number" in item for item in validate_stage_output(stage, tables, SPEC))
    assert not validate_stage_output(stage, rows_for(stage), SPEC)


@pytest.mark.parametrize("stage", STAGES[3:])
def test_legacy_coding_headers_are_rejected_in_synthesis(stage):
    tables = rows_for(stage)
    row = tables["Innovation"][0]
    row["Quote"] = row.pop("Combined Evidence Quotes")
    row["Explanation"] = row.pop("Synthesized Explanation")
    issues = validate_stage_output(stage, tables, SPEC)
    assert any("missing columns: Combined Evidence Quotes, Synthesized Explanation" in item for item in issues)


@pytest.mark.parametrize("stage", STAGES[3:])
def test_synthesis_domain_scope_is_explicit(stage):
    tables = rows_for(stage)
    tables["Innovation"][0]["CFIR Domain"] = "Outcomes Addendum"
    assert any("out-of-scope" in item for item in validate_stage_output(stage, tables, SPEC))


def test_network_requires_five_domains_and_cross_requires_correct_valence_column():
    tables = rows_for(STAGES[3])
    del tables["Individuals"]
    assert validate_stage_output(STAGES[3], tables, SPEC) == ["Missing required values for 'CFIR Domain': Individuals."]
    tables = rows_for(STAGES[4])
    tables["Innovation"][0].pop("Valence Explanation")
    assert any("missing columns: Valence Explanation" in item for item in validate_stage_output(STAGES[4], tables, SPEC))
    tables = rows_for(STAGES[4])
    tables["Innovation"][0]["Overall Valence"] = "Neutral/Unclear"
    assert any("out-of-scope value for 'Overall Valence'" in item for item in validate_stage_output(STAGES[4], tables, SPEC))


def test_exact_headers_and_scope_are_opt_in_and_legacy_schema_is_unchanged():
    legacy = load_stage_output_spec(ROOT / "config/schemas/cfir_stage_outputs_v1.yaml")
    assert scoped_contract_sha256(legacy) is None
    assert all(rule.qa_rules is None for rule in legacy.stages.values())
    tables = {"Innovation": [{"Explanation": "x", "Quote": "x", "CFIR Construct": "x", "CFIR Domain": "Any", "Extra": "x"}]}
    assert not validate_stage_output(STAGES[0], tables, legacy)
    assert validate_stage_output(STAGES[0], tables, SPEC)
    assert legacy.stages[STAGES[3]].required_columns == ["CFIR Domain", "CFIR Construct", "Quote", "Explanation", "Source File(s)"]
    default = yaml.safe_load((ROOT / "examples/project_template/project_transcript.yaml").read_text())
    assert default["structured_output"] == {"enforce": False, "spec": "config/schemas/cfir_stage_outputs_v1.yaml"}


def test_misspelled_scoped_rules_and_inconsistent_value_contracts_fail_loading():
    with pytest.raises(ValidationError):
        StageOutputRule(qa_rules=["typo_rule"])
    with pytest.raises(ValidationError, match="must be required"):
        StageOutputRule(allowed_values={"Missing": ["x"]})
    with pytest.raises(ValidationError, match="must be allowed"):
        StageOutputRule(required_columns=["Domain"], allowed_values={"Domain": ["A"]}, required_values={"Domain": ["B"]})


def test_scoped_qa_uses_stage_columns_and_cross_rules_only(tmp_path):
    runner = fixture_runner(tmp_path)
    def artifact(stage):
        return StageArtifact(run_id="r", stage_id=stage, input_path="synthetic", input_sha256=None,
            prompt_ref="p", prompt_sha256="frozen", response_text="synthetic", model="mock",
            provider="mock", timestamp_utc="2026-09-12T00:00:00Z", parsed_output=rows_for(stage))
    network = artifact(STAGES[3])
    assert runner._run_qa(network) == []
    cross = artifact(STAGES[4])
    cross.parsed_output["Innovation"][0].update({"Barrier Networks": "ON AMN; Unknown", "Source File(s)": "ON AMN; NB AMN"})
    assert {item.rule_id for item in runner._run_qa(cross)} == {
        "allowed_network_labels_only", "one_network_one_valence", "source_files_covered_by_valence_columns",
    }
    runner.structured_output_spec.stages[STAGES[4]].qa_rules = []
    assert runner._run_qa(cross) == []
    runner.structured_output_spec = None
    assert {item.rule_id for item in runner._run_qa(network)} == {"required_columns_present", "source_files_covered_by_valence_columns"}


def test_full_scoped_run_and_resume_preserve_artifacts_and_recover_qa(tmp_path, monkeypatch):
    runner = fixture_runner(tmp_path)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, "scoped")
    calls = []
    def complete(**kwargs):
        calls.append(kwargs["stage_id"])
        if kwargs["stage_id"] == STAGES[4]:
            tables = rows_for(STAGES[4])
            tables["Innovation"][0]["Barrier Networks"] = "ON AMN"
            return LLMResponse(text=markdown(tables), provider="mock", model="mock")
        return fake_completion(**kwargs)
    monkeypatch.setattr(runner, "_complete", complete)
    path = runner.execute_run_plan(plan, "scoped")
    manifest = json.loads(path.read_text())
    assert len(calls) == 19 and len(manifest["artifact_paths"]) == 9
    assert manifest["status"] == "completed" and manifest["qa_failure_count"] == 1
    assert manifest["structured_output_failure_count"] == 0
    before = {p: p.read_bytes() for p in path.parent.glob("*/*_artifact.json")}
    items = review_item_paths(path.parent, tmp_path / "review_queue/scoped", manifest)
    assert len(items) == 1
    assert json.loads(items[0].read_text())["rule_id"] == "one_network_one_valence"
    for artifact in before:
        assert json.loads(artifact.read_text())["structured_output_contract_sha256"] == scoped_contract_sha256(SPEC)
    monkeypatch.setattr(runner, "_complete", lambda **kw: pytest.fail("Resume must not dispatch"))
    runner.save_run_plan(plan, "scoped")
    runner.execute_run_plan(plan, "scoped")
    resumed = json.loads(path.read_text())
    assert resumed["qa_failure_count"] == 1 and resumed["qa_inventory_sha256"] == manifest["qa_inventory_sha256"]
    assert review_item_paths(path.parent, tmp_path / "review_queue/scoped", resumed) == items
    assert all(p.read_bytes() == content for p, content in before.items())


def test_resumed_network_schema_failure_still_blocks_cross_stage(tmp_path, monkeypatch):
    runner = fixture_runner(tmp_path)
    plan = runner.build_run_plan()
    def complete(**kwargs):
        if kwargs["stage_id"] == STAGES[3]:
            return LLMResponse(text=markdown(rows_for(STAGES[3], ["Innovation"])), provider="mock", model="mock")
        assert kwargs["stage_id"] != STAGES[4]
        return fake_completion(**kwargs)
    monkeypatch.setattr(runner, "_complete", complete)
    path = runner.execute_run_plan(plan, "scoped")
    manifest = json.loads(path.read_text())
    assert manifest["status"] == "blocked_validation" and manifest["structured_output_failure_count"] == 2
    before = {p: p.read_bytes() for p in path.parent.glob("*/*_artifact.json")}
    monkeypatch.setattr(runner, "_complete", lambda **kw: pytest.fail("Invalid cached stage must block before dispatch"))
    runner.execute_run_plan(plan, "scoped")
    assert json.loads(path.read_text())["structured_output_failure_count"] == 2
    assert not (path.parent / STAGES[4]).exists()
    assert all(p.read_bytes() == value for p, value in before.items())


def test_interrupted_scoped_run_recovers_all_prior_artifacts_without_a_manifest(tmp_path, monkeypatch):
    runner = fixture_runner(tmp_path)
    plan = runner.build_run_plan()
    def interrupted(**kwargs):
        if kwargs["stage_id"] == STAGES[4]:
            raise RuntimeError("Synthetic interruption before final response")
        return fake_completion(**kwargs)
    monkeypatch.setattr(runner, "_complete", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        runner.execute_run_plan(plan, "interrupted")
    root = tmp_path / "artifacts/interrupted"
    assert not (root / "run_manifest.json").exists()
    before = {p: p.read_bytes() for p in root.glob("*/*_artifact.json")}
    assert len(before) == 8
    calls = []
    def resumed(**kwargs):
        calls.append(kwargs["stage_id"])
        return fake_completion(**kwargs)
    monkeypatch.setattr(runner, "_complete", resumed)
    path = runner.execute_run_plan(plan, "interrupted")
    manifest = json.loads(path.read_text())
    assert calls == [STAGES[4]]
    assert len(manifest["artifact_paths"]) == 9
    assert manifest["qa_failure_count"] == manifest["structured_output_failure_count"] == 0
    assert all(p.read_bytes() == content for p, content in before.items())


def test_v2_filename_alone_does_not_activate_contract_or_scoped_qa(tmp_path):
    runner = fixture_runner(tmp_path, scoped=False)
    assert runner.structured_output_spec is None
    assert not any(a.kind == "structured_output_schema" for a in runner.configuration_lock.assets)
    assert runner.framework.qa_rules == ["required_columns_present", "allowed_network_labels_only",
        "one_network_one_valence", "source_files_covered_by_valence_columns", "prompt_version_required"]


def test_changed_scoped_contract_cannot_overwrite_or_resume_prior_run(tmp_path, monkeypatch):
    runner = fixture_runner(tmp_path)
    plan = runner.build_run_plan()
    runner.save_run_plan(plan, "frozen")
    schema = tmp_path / "config/schemas/cfir_stage_outputs_v2.yaml"
    data = yaml.safe_load(schema.read_text())
    data["stages"][STAGES[0]]["qa_rules"] = []
    schema.write_text(yaml.safe_dump(data), encoding="utf-8")
    changed = ProjectRunner(runner.project_manifest_path)
    assert changed.configuration_lock.fingerprint_sha256 != plan.configuration_fingerprint
    before = {p: p.read_bytes() for p in (tmp_path / "artifacts/frozen").iterdir()}
    monkeypatch.setattr(changed, "_complete", lambda **kw: pytest.fail("Changed contract must not dispatch"))
    with pytest.raises(ValueError, match="configuration changed"):
        changed.execute_run_plan(plan, "frozen")
    for operation in [changed.save_run_plan, changed.execute_run_plan]:
        with pytest.raises(ValueError, match="different or unknown configuration"):
            operation(changed.build_run_plan(), "frozen")
    assert all(p.read_bytes() == value for p, value in before.items())


@pytest.mark.parametrize("kind", ["legacy", "changed_hash", "missing_status"])
def test_unbound_artifacts_cannot_be_adopted_by_scoped_execution(tmp_path, monkeypatch, kind):
    runner = fixture_runner(tmp_path)
    plan = runner.build_run_plan()
    monkeypatch.setattr(runner, "_complete", fake_completion)
    path = runner.execute_run_plan(plan, "scoped", stage_filter=[STAGES[0]])
    artifact_path = next(path.parent.glob("*/*_artifact.json"))
    data = json.loads(artifact_path.read_text())
    if kind == "legacy":
        data.pop("structured_output_contract_sha256")
        data["structured_output_schema_id"] = "cfir_stage_outputs_v1"
    elif kind == "changed_hash":
        data["structured_output_contract_sha256"] = "0" * 64
    else:
        data["structured_output_valid"] = None
    artifact_path.write_text(json.dumps(data), encoding="utf-8")
    before = artifact_path.read_bytes()
    monkeypatch.setattr(runner, "_complete", lambda **kw: pytest.fail("Unbound artifact must not dispatch"))
    with pytest.raises(ValueError, match="not validated under this scoped"):
        runner.execute_run_plan(plan, "scoped")
    assert artifact_path.read_bytes() == before


def test_scoped_schema_is_a_frozen_configuration_asset(tmp_path):
    runner = fixture_runner(tmp_path)
    asset = next(a for a in create_configuration_lock(runner.project_manifest_path).assets if a.kind == "structured_output_schema")
    assert asset.id == SPEC.id
    assert asset.sha256 == sha256_for_file(tmp_path / "config/schemas/cfir_stage_outputs_v2.yaml")
