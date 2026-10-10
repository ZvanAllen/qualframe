"""Synthetic resume regressions; runnable against the original or staged runner."""

import dataclasses
import json
from pathlib import Path

import pytest
import yaml

from qualframe.adjudication import append_adjudication_action, latest_adjudication_by_item
from qualframe.io.files import sha256_for_file
from qualframe.models import CodebookSpec, MethodSpec, StageArtifact
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.providers.base import LLMResponse


def runner_fixture(tmp_path: Path, *, grouping="per_file", sources=1):
    paths = {
        "raw_transcripts": "data/transcripts",
        "raw_workbooks": "data/workbooks",
        "reference": "data/reference",
        "artifacts": "artifacts",
        "review_queue": "review_queue",
        "exports": "exports",
        "logs": "logs",
    }
    for value in paths.values():
        (tmp_path / value).mkdir(parents=True, exist_ok=True)
    source_dir = tmp_path / paths["raw_transcripts"] / "Network A"
    source_dir.mkdir()
    for index in range(1, sources + 1):
        (source_dir / f"{index}A_synthetic.txt").write_text("A synthetic transcript.")
    config = tmp_path / "config"
    config.mkdir()
    (config / "prompt.md").write_text("Return a synthetic table for {CFIR_DOMAIN}.")
    (config / "prompts.yaml").write_text(
        yaml.safe_dump(
            dict(
                id="synthetic-prompts",
                stages={"synthetic": {"file": "config/prompt.md"}},
            )
        )
    )
    (config / "framework.yaml").write_text(
        yaml.safe_dump(
            dict(
                id="synthetic",
                name="Synthetic framework",
                domains=["Domain"],
                required_columns=["Needed"],
                qa_rules=["required_columns_present", "prompt_version_required"],
                prompt_set="config/prompts.yaml",
            )
        )
    )
    tested = dict(id="tested", prompt_ref="synthetic", input_source="raw_transcripts")
    if grouping == "domain_iterations":
        tested["domain_iterations"] = True
    elif grouping == "bundle_all":
        tested["input_grouping"] = "bundle_all"
    elif grouping == "group_by_network":
        tested.update(group_by_network=True, input_source="previous_stage")
    (config / "pipeline.yaml").write_text(
        yaml.safe_dump(
            dict(
                id="synthetic-pipeline",
                framework="config/framework.yaml",
                mode="transcript_first",
                stages=[
                    dict(id="upstream", prompt_ref="synthetic", input_source="raw_transcripts"),
                    tested,
                    dict(id="last", prompt_ref="synthetic", input_source="previous_stage"),
                ],
            )
        )
    )
    project_path = tmp_path / "examples/project/project.yaml"
    project_path.parent.mkdir(parents=True)
    project_path.write_text(
        yaml.safe_dump(
            dict(
                project_id="synthetic",
                framework="config/framework.yaml",
                pipeline="config/pipeline.yaml",
                mode="transcript_first",
                paths=paths,
                provider={"name": "mock"},
            )
        )
    )
    runner = ProjectRunner(project_path)
    return runner, runner.build_run_plan()


def saved(runner, *, stage="tested", source="1A_synthetic", filename=None, rows=None):
    run_root = runner.repo_root / "artifacts/resumed"
    path = run_root / stage / (filename or f"{source}_artifact.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    source_path = runner.repo_root / f"data/transcripts/Network A/{source}.txt"
    artifact = StageArtifact(
        run_id="resumed",
        stage_id=stage,
        input_path=source_path.relative_to(runner.repo_root).as_posix(),
        input_sha256=sha256_for_file(source_path),
        prompt_ref="synthetic",
        prompt_sha256="frozen",
        response_text="Preserved synthetic model response.",
        model="mock",
        provider="mock",
        timestamp_utc="2026-09-11T00:00:00Z",
        parsed_output=rows or {"one": [{"Other": "value"}], "two": [{"Other": "value"}]},
    )
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return path, artifact


def current_items(runner, manifest_path):
    from qualframe.qa.inventory import review_item_paths

    return review_item_paths(
        manifest_path.parent,
        runner.repo_root / "review_queue/resumed",
        json.loads(manifest_path.read_text()),
    )


@pytest.mark.parametrize(
    "grouping", ["per_file", "domain_iterations", "bundle_all", "group_by_network"]
)
def test_saved_artifact_qa_is_recovered_for_every_resume_branch(tmp_path, monkeypatch, grouping):
    runner, plan = runner_fixture(tmp_path, grouping=grouping)
    if grouping == "group_by_network":
        saved(runner, stage="upstream")
    filename = {
        "bundle_all": "bundle_artifact.json",
        "group_by_network": "Network_A_artifact.json",
    }.get(grouping)
    artifact_path, _ = saved(runner, filename=filename)
    original = artifact_path.read_bytes()
    monkeypatch.setattr(
        runner, "_complete", lambda **kwargs: pytest.fail("Cached resume must not call a provider")
    )
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    manifest = json.loads(path.read_text())
    # This assertion demonstrates the original bug before importing new inventory code.
    assert manifest["qa_failure_count"] == 2
    assert len(manifest["artifact_paths"]) == 1  # Keep stage-filter scope.
    paths = current_items(runner, path)
    assert len(paths) == 2
    assert all(json.loads(p.read_text())["rule_id"] == "required_columns_present" for p in paths)
    before = {p: p.read_bytes() for p in paths}
    again = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    assert json.loads(again.read_text())["qa_failure_count"] == 2
    assert current_items(runner, again) == paths
    assert all(p.read_bytes() == content for p, content in before.items())
    assert artifact_path.read_bytes() == original


def test_failed_invocation_recovers_qa_from_saved_prior_stage(tmp_path, monkeypatch):
    runner, plan = runner_fixture(tmp_path)

    def interrupted(**kwargs):
        if kwargs["stage_id"] == "upstream":
            return LLMResponse(text="| Other |\n|---|\n| value |", provider="mock", model="mock")
        raise RuntimeError("Synthetic interruption before the second artifact")

    monkeypatch.setattr(runner, "_complete", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        runner.execute_run_plan(plan, "resumed", stage_filter=["upstream", "tested"])
    run_root = runner.repo_root / "artifacts/resumed"
    original_path = next((run_root / "upstream").glob("*_artifact.json"))
    original = original_path.read_bytes()
    assert not (run_root / "run_manifest.json").exists()
    calls = []

    def resumed(**kwargs):
        calls.append(kwargs["stage_id"])
        return LLMResponse(text="| Needed |\n|---|\n| value |", provider="mock", model="mock")

    monkeypatch.setattr(runner, "_complete", resumed)
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["upstream", "tested"])
    assert json.loads(path.read_text())["qa_failure_count"] == 1
    assert calls == ["tested"]
    assert len(current_items(runner, path)) == 1
    assert original_path.read_bytes() == original


def test_inventory_deduplicates_paths_without_collapsing_sources_stages_or_rows(tmp_path):
    from qualframe.qa.inventory import write_run_qa_inventory

    runner, _ = runner_fixture(tmp_path, sources=2)
    first, _ = saved(runner)
    second, _ = saved(runner, source="2A_synthetic")
    third, _ = saved(runner, stage="last")
    root = runner.repo_root / "artifacts/resumed"
    calls = []

    def evaluate(artifact):
        calls.append((artifact.stage_id, artifact.input_path))
        return runner._artifact_qa(artifact)

    result = write_run_qa_inventory(
        run_id="resumed",
        artifact_root=root,
        review_root=runner.repo_root / "review_queue/resumed",
        artifact_paths=[str(p.relative_to(root)) for p in [first, second, first, third]],
        evaluate=evaluate,
    )
    assert len(calls) == 3
    assert len(result["artifact_paths"]) == 3
    assert result["qa_failure_count"] == 6
    inventory = json.loads((root / result["qa_inventory_path"]).read_text())
    assert len({item["item_id"] for item in inventory["items"]}) == 6


def test_stored_schema_and_directed_method_failures_are_reconstructed(tmp_path):
    runner, _ = runner_fixture(tmp_path)
    runner.method = MethodSpec(
        id="single", name="Synthetic", version="1", coding={"cardinality": "single_label"}
    )
    runner.codebook = CodebookSpec(
        id="synthetic",
        name="Synthetic",
        version="1",
        codes=[
            dict(id="a", label="A", definition="Synthetic A"),
            dict(id="b", label="B", definition="Synthetic B"),
        ],
    )
    _, artifact = saved(
        runner,
        rows={
            "Coding": [
                {"Meaning Unit ID": "unit", "Code ID": "a"},
                {"Meaning Unit ID": "unit", "Code ID": "b"},
            ]
        },
    )
    artifact.structured_output_valid = False
    artifact.structured_output_issues = ["Synthetic saved schema issue"]
    failures = runner._artifact_qa(artifact)
    assert [item.rule_id for item in failures].count("structured_output_schema") == 1
    assert [item.rule_id for item in failures].count("directed_method_policy") == 1
    assert [item.rule_id for item in failures].count("required_columns_present") == 2


def test_explicit_source_legacy_review_path_and_decision_history_survive_resume(tmp_path):
    runner, plan = runner_fixture(tmp_path)
    artifact_path, artifact = saved(runner, rows={"one": [{"Needed": "value"}]})
    artifact.structured_output_valid = False
    artifact.structured_output_issues = ["Synthetic schema failure"]
    artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    review_root = runner.repo_root / "review_queue/resumed"
    review_root.mkdir(parents=True)
    old = review_root / "tested_structured_output_schema_0000.json"
    old.write_text(json.dumps(dataclasses.asdict(runner._artifact_qa(artifact)[0])))
    action = append_adjudication_action(
        review_dir=review_root,
        artifact_root=runner.repo_root / "artifacts/resumed",
        run_id="resumed",
        item_path=old,
        decision="approve",
        reviewer="Synthetic reviewer",
        rationale="Synthetic legacy decision preservation test",
    )
    history = review_root / "adjudication/actions.jsonl"
    before = {p: p.read_bytes() for p in (old, history)}
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    assert current_items(runner, path) == [old]
    runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    assert current_items(runner, path) == [old]
    assert all(p.read_bytes() == content for p, content in before.items())
    assert latest_adjudication_by_item(review_root)[old.name].action_id == action.action_id


def test_ambiguous_legacy_decision_is_not_copied_to_multiple_artifacts(tmp_path):
    runner, plan = runner_fixture(tmp_path, sources=2)
    _, artifact = saved(runner, rows={"one": [{"Other": "value"}]})
    saved(runner, source="2A_synthetic", rows={"one": [{"Other": "value"}]})
    review_root = runner.repo_root / "review_queue/resumed"
    review_root.mkdir(parents=True)
    old = review_root / "old.json"
    old.write_text(json.dumps(dataclasses.asdict(runner._run_qa(artifact)[0])))
    original = old.read_bytes()
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    assert len(current_items(runner, path)) == 2 and old not in current_items(runner, path)
    manifest = json.loads(path.read_text())
    inventory = json.loads((path.parent / manifest["qa_inventory_path"]).read_text())
    assert inventory["unassociated_legacy_paths"] == ["old.json"]
    assert old.read_bytes() == original


def test_inventory_reader_checks_hashes_and_preserves_legacy_fallback(tmp_path):
    from qualframe.qa.inventory import review_item_paths

    runner, plan = runner_fixture(tmp_path)
    saved(runner)
    root = runner.repo_root / "artifacts/resumed"
    review = runner.repo_root / "review_queue/resumed"
    review.mkdir(parents=True)
    legacy = review / "legacy.json"
    legacy.write_text('{"kind":"disagreement"}')
    assert review_item_paths(root, review, {"run_id": "old"}) == [legacy]
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    manifest = json.loads(path.read_text())
    assert legacy in current_items(runner, path)  # Independent disagreements remain available.
    item = current_items(runner, path)[0]
    item.write_text("tampered")
    with pytest.raises(ValueError, match="changed"):
        review_item_paths(root, review, manifest)


def test_generated_review_decision_survives_resume_and_displays_on_windows(tmp_path):
    from qualframe.dashboard import DashboardApp

    runner, plan = runner_fixture(tmp_path)
    saved(runner, rows={"one": [{"Other": "value"}]})
    manifest_path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    review_root = runner.repo_root / "review_queue/resumed"
    item = current_items(runner, manifest_path)[0]
    append_adjudication_action(
        review_dir=review_root,
        artifact_root=manifest_path.parent,
        run_id="resumed",
        item_path=item,
        decision="approve",
        reviewer="Synthetic reviewer",
        rationale="Synthetic generated decision test",
    )
    history = review_root / "adjudication/actions.jsonl"
    before = history.read_bytes()
    runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    assert current_items(runner, manifest_path) == [item]
    assert history.read_bytes() == before
    assert "<td>approve</td>" in DashboardApp(runner)._render_run("resumed")


def test_filtered_source_never_inherits_anonymous_legacy_approval(tmp_path):
    runner, plan = runner_fixture(tmp_path, sources=2)
    _, first = saved(runner, rows={"one": [{"Other": "value"}]})
    saved(runner, source="2A_synthetic", rows={"one": [{"Other": "value"}]})
    review = runner.repo_root / "review_queue/resumed"
    review.mkdir(parents=True)
    old = review / "old-first-source.json"
    old.write_text(json.dumps(dataclasses.asdict(runner._run_qa(first)[0])))
    action = append_adjudication_action(
        review_dir=review,
        artifact_root=runner.repo_root / "artifacts/resumed",
        run_id="resumed",
        item_path=old,
        decision="approve",
        reviewer="Synthetic reviewer",
        rationale="Old decision concerns the first source only",
    )
    before = old.read_bytes()
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"], transcript_filter="2A")
    current = current_items(runner, path)
    assert len(current) == 1 and old not in current
    assert old.read_bytes() == before
    latest = latest_adjudication_by_item(review)
    assert latest[old.name].action_id == action.action_id
    assert str(current[0].relative_to(review)) not in latest


@pytest.mark.parametrize(
    "fields",
    [
        {"qa_inventory_path": "qa/inventory.json"},
        {"qa_inventory_sha256": "a" * 64},
        {"qa_inventory_path": "", "qa_inventory_sha256": "a" * 64},
    ],
)
def test_incomplete_inventory_pointer_does_not_fall_back_to_legacy(tmp_path, fields):
    from qualframe.qa.inventory import review_item_paths

    with pytest.raises(ValueError, match="both"):
        review_item_paths(tmp_path / "artifacts", tmp_path / "review", fields)


@pytest.mark.parametrize("mutation", ["item_scope", "item_hash_binding", "malformed_items"])
def test_inventory_attribution_schema_is_checked_after_hash_validation(tmp_path, mutation):
    from qualframe.qa.inventory import review_item_paths

    runner, plan = runner_fixture(tmp_path)
    saved(runner)
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    manifest = json.loads(path.read_text())
    inventory_path = path.parent / manifest["qa_inventory_path"]
    inventory = json.loads(inventory_path.read_text())
    if mutation == "item_scope":
        inventory["items"][0]["artifact_path"] = "outside/unknown.json"
    elif mutation == "item_hash_binding":
        inventory["items"][0]["artifact_sha256"] = "a" * 64
    else:
        inventory["items"] = None
    inventory_path.write_text(json.dumps(inventory))
    manifest["qa_inventory_sha256"] = sha256_for_file(inventory_path)
    with pytest.raises(ValueError):
        review_item_paths(path.parent, runner.repo_root / "review_queue/resumed", manifest)


def test_windows_manifest_separators_and_unassociated_legacy_files(tmp_path):
    from qualframe.qa.inventory import review_item_paths

    runner, plan = runner_fixture(tmp_path)
    saved(runner)
    review = runner.repo_root / "review_queue/resumed"
    review.mkdir(parents=True)
    orphan = review / "old-incomplete.json"
    orphan.write_text("{")
    path = runner.execute_run_plan(plan, "resumed", stage_filter=["tested"])
    manifest = json.loads(path.read_text())
    manifest["qa_inventory_path"] = manifest["qa_inventory_path"].replace("/", "\\")
    manifest["artifact_paths"] = [value.replace("/", "\\") for value in manifest["artifact_paths"]]
    assert len(review_item_paths(path.parent, review, manifest)) == 2
    assert orphan.read_text() == "{"
