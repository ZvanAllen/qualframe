"""Offline fictional example: recording completeness, usage provenance and doc drift."""
from __future__ import annotations

import importlib.util
import json
import shutil
import socket
from pathlib import Path

import pytest

from qualframe.app_workspace import ensure_workspace
from qualframe.pipeline import project_runner
from qualframe.qualbench import build_qualbench, coding_profile, reference_coding_set

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("qualbench_example", ROOT / "scripts/run_qualbench_example.py")
example = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(example)


@pytest.fixture
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The worked example must not use a network or a hosted provider.")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    original = project_runner.build_provider

    def recorded_only(config):
        if config.name != "recorded":
            forbidden()
        return original(config)

    monkeypatch.setattr(project_runner, "build_provider", recorded_only)
    read = Path.read_text

    def no_env(path, *args, **kwargs):
        if path.name == ".env":
            raise AssertionError("The offline example must not read credentials.")
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", no_env)


def _copied_recording(tmp_path, cell):
    folder = tmp_path / cell.recording
    shutil.copytree(example.RECORDINGS / cell.recording, folder)
    return folder


def test_missing_cell_fails_before_creating_an_output(tmp_path, monkeypatch):
    monkeypatch.setattr(example, "validate_recording", lambda cell: (_ for _ in ()).throw(ValueError("missing cell")))
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="missing cell"):
        example.build_example(output)
    assert not output.exists()


@pytest.mark.parametrize("mutation", ["missing", "extra", "empty", "prompt", "tokens", "provider", "model", "api_mode", "temperature"])
def test_legacy_recording_refuses_incomplete_or_changed_inputs(tmp_path, mutation):
    cell = example.CELLS[0]
    folder = _copied_recording(tmp_path, cell)
    response = next((folder / "responses").glob("*.txt"))
    info_path = folder / "recording.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        response.unlink()
    elif mutation == "extra":
        (folder / "responses/extra.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "empty":
        response.write_text("", encoding="utf-8")
    elif mutation == "prompt":
        info["prompt_sha256"] = "changed"
    elif mutation == "tokens":
        info["provider_settings"]["max_tokens"] = 32000
    else:
        info["provider_settings"]["name" if mutation == "provider" else mutation] = "changed"
    info_path.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(ValueError):
        example.validate_recording(cell, tmp_path)


@pytest.mark.parametrize("mutation", ["status", "complete", "expected_requests", "completed_requests",
                                      "codebook_sha256", "response_sha256", "transcripts", "policy_context"])
def test_new_recording_refuses_incomplete_or_changed_identity(tmp_path, mutation):
    cell = example.CELLS[1]
    folder = _copied_recording(tmp_path, cell)
    path = folder / "recording.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "policy_context":
        info["method_policy"]["context"]["before"] += 1
    else:
        info[mutation] = "changed"
    path.write_text(json.dumps(info), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or mismatched"):
        example.validate_recording(cell, tmp_path)


def test_new_recording_policy_name_does_not_change_analysis_identity(tmp_path):
    cell = example.CELLS[1]
    folder = _copied_recording(tmp_path, cell)
    path = folder / "recording.json"
    info = json.loads(path.read_text(encoding="utf-8"))
    info["method_policy"]["name"] = "Another fictional replay study analysis method"
    path.write_text(json.dumps(info), encoding="utf-8")
    assert example.validate_recording(cell, tmp_path)["complete"] is True


def test_existing_replays_preserve_reference_assessment_and_cost_provenance(tmp_path, offline):
    workspace = ensure_workspace(tmp_path / "workspace").root
    cell = example.CELLS[0]
    info = example.validate_recording(cell)
    example.validate_recording(example.REFERENCE_CELL)
    coding = example._replay_cell(workspace, cell)
    illustrative = example._replay_cell(workspace, example.REFERENCE_CELL)
    illustrative.update(run_id="reference:illustrative-a", label="Illustrative coder A",
                        statement=example.REFERENCE_STATEMENT, independent_human_coding=False)
    report = build_qualbench([coding], reference=reference_coding_set(illustrative))
    profile = report["coding_sets"][0]
    assert "cost_usd" not in profile  # replay estimates were discarded
    example._original_usage(profile, cell, info)
    assert profile["cost_usd"] == profile["whole_run_cost_usd"] == info["estimated_cost_usd"]
    assert profile["input_tokens"] == info["reported_usage"]["input_tokens"]
    assert profile["cost_is_estimated"] is True
    assert profile["elapsed_seconds"] is profile["cohort_elapsed_seconds"] is None
    assert profile["whole_run_elapsed_seconds"] is None
    assert profile["usage_ledger_path"] is None
    assert report["reference"]["independent_human_coding"] is False
    assert report["reference_records_explicit_absences"] is False
    units = [r for r in report["units"] if r["coding_set"] == "reference:illustrative-a"]
    assert len(units) == 90
    assert all(r["assessed"] for r in units)
    assert sum(r["present"] for r in units) == 37
    assert report["code_universes"] == {"code": 15, "parent code": 4}
    assert not report["exclusions"]
    with pytest.raises(ValueError, match="complete six-document"):
        example._original_usage(dict(profile, transcripts=5), cell, info)


def test_original_usage_keeps_actual_ledger_cost_separate_from_replay_estimates():
    cell = example.CELLS[1]
    profile = {"transcripts": 6}
    info = dict(actual_cost_usd=0.123456, estimated_cost_usd=99, requests=24,
                reported_usage={"input_tokens": 9999, "output_tokens": 9999},
                usage_breakdown={"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30,
                                 "cache_write_tokens": 0, "reasoning_tokens": 5},
                cost_source="provider_usage_ledger", provider_settings={"name": "offline", "model": "fixture"})
    example._original_usage(profile, cell, info)
    assert profile["cost_usd"] == 0.123456
    assert profile["cost_is_estimated"] is False
    assert profile["requests"] == 24
    assert profile["input_tokens"] == 100
    assert profile["reasoning_tokens"] == 5
    assert profile["cohort_cost_usd_per_transcript"] == 0.123456 / 6
    assert profile["elapsed_seconds"] is None


@pytest.mark.parametrize("cell", [example.CELLS[2], example.CELLS[6]])
def test_decide_replay_preserves_original_omissions(tmp_path, offline, cell):
    metadata = example.validate_recording(cell)
    workspace = ensure_workspace(tmp_path / "workspace").root
    coding = example._replay_cell(workspace, cell)
    assert coding_profile(coding)["no_decision_count"] == metadata["no_decision_count"]
    assert len(coding["sources"]) == 6


def test_example_rebuilds_all_cells_offline_and_matches_documentation(tmp_path, monkeypatch, offline):
    workspaces = []
    replay = example._replay_cell

    def tracked(workspace, cell):
        workspaces.append(workspace)
        return replay(workspace, cell)

    monkeypatch.setattr(example, "_replay_cell", tracked)
    output = tmp_path / "example"
    report = example.build_example(output)
    assert len(workspaces) == 9
    assert all(not path.exists() for path in workspaces)
    assert len(report["coding_sets"]) == 9
    assert report["bootstrap_settings"] == {"replicates": 2000, "seed": 1, "cluster_by_folder": False}
    assert report["reference"]["independent_human_coding"] is False
    assert report["reference_records_explicit_absences"] is False
    assert report["code_universes"] == {"code": 15, "parent code": 4}
    assert not report["exclusions"] and not report["transcripts_left_out"]
    assert not report["codebook_differences"]
    compared = [row for row in report["presence"] if row["comparison"] == "versus reference"
                and row["scope_kind"] == "all" and row["level"] == "code"]
    assert len(compared) == 10  # eight saved cells and two trivial baselines
    assert all(row["n_units"] == 90 for row in compared)  # omissions do not reduce the reference mask
    assert sum(row["requests"] for row in report["coding_sets"] if row["kind"] != "reference") == 120
    for row in report["coding_sets"]:
        if row["kind"] == "reference":
            continue
        assert row["elapsed_seconds"] is row["whole_run_elapsed_seconds"] is None
        assert row["original_usage_source"].startswith("demo/recordings/")
        metadata = report["example_recordings"][row["set_id"]]
        if "no_decision_count" in metadata:
            assert row["no_decision_count"] == metadata["no_decision_count"]
    docs = (ROOT / "docs/examples/qualbench-2x2.md").read_text(encoding="utf-8")
    assert docs.count(example.TABLES_START) == docs.count(example.TABLES_END) == 1
    documented = docs.split(example.TABLES_START, 1)[1].split(example.TABLES_END, 1)[0].strip()
    generated = example.render_key_tables(report)
    assert documented == generated
    assert (output / "example_tables.md").read_text(encoding="utf-8").strip() == generated
    assert json.loads((output / "example_numbers.json").read_text(encoding="utf-8")) == example.example_numbers(report)
    assert all((output / name).is_file() for name in ("report.json", "coding_sets.csv", "presence.csv", "bootstrap.csv", "passages.csv"))
    with pytest.raises(FileExistsError, match="already exists"):
        example.build_example(output)
