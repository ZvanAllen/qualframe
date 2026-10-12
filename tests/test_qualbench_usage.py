"""Synthetic accounting checks for the cohort actually compared by QualBench."""
import json

import pytest

import qualframe.qualbench as qualbench


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run(tmp_path, monkeypatch, *, sources=None, ledger_rows=None, attempts=None):
    root = tmp_path / "workspace"
    run = root / "studies/synthetic/artifacts/full"
    sources = sources or {"t/one.txt": "one", "t/two.txt": "two", "t/three.txt": "three"}
    payload = dict(
        run_id=run.name, project_id="synthetic", sources=sources,
        codebook={"codes": [{"id": "a", "label": "A"}]},
        included=[], excluded=[], absences=[],
    )
    monkeypatch.setattr(qualbench, "raw_coding_payload", lambda *_: payload)
    _json(run / "run_settings.json", {"provider": {"name": "offline", "model": "test"}})
    _json(run / "run_plan.json", {
        "planned_stage_runs": [
            {"stage_id": "coding", "input_path": source} for source in sources
        ] + [{"stage_id": "rollup", "input_path": "outputs_from:coding"},
             {"stage_id": "network", "input_path": "outputs_from:rollup"}],
    })
    if ledger_rows is not None:
        ledger = run.parents[1] / "logs/cost_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("\n".join(json.dumps(dict(run_id=run.name, **row)) for row in ledger_rows),
                          encoding="utf-8")
    for index, row in enumerate(attempts or []):
        _json(run / "requests" / f"{index:02}.json", row)
    return root, run


def _row(request_id, label, cost, *, stage="coding", tokens=100):
    return dict(request_id=request_id, input_label=label, stage_id=stage,
                input_tokens=tokens, output_tokens=tokens // 2, calculated_cost_usd=cost)


def _attempt(request_id, label, elapsed):
    return dict(request_id=request_id, input_label=label, elapsed_seconds=elapsed)


def test_compared_cohort_usage_excludes_other_transcripts_and_later_stages(tmp_path, monkeypatch):
    rows = [
        _row("one", r"t\one.txt::Inner Setting", 99),
        _row("one", r"t\one.txt::Inner Setting", 2),  # reconciled entry replaces estimate
        _row("retry", "t/one.txt::Inner Setting", 1),  # separately charged attempt counts
        _row("two", "t/two.txt", 3),
        _row("three", "t/three.txt", 5),
        _row("rollup", "t/one.txt", 7, stage="rollup"),
        _row("network", "network-1", 11, stage="network"),
    ]
    attempts = [_attempt(row["request_id"], row["input_label"], elapsed)
                for row, elapsed in zip(rows[1:], [10, 3, 20, 30, 40, 50])]
    # A copied record with the same request ID must not duplicate elapsed time.
    attempts.append(_attempt("one", r"t\one.txt::Inner Setting", 10))
    root, run = _run(tmp_path, monkeypatch, ledger_rows=rows, attempts=attempts)
    coding = qualbench.run_coding_set(root, run)
    reference = qualbench.reference_coding_set(dict(
        run_id="ref", label="Synthetic reference", sources={"t/one.txt": "one", "t/two.txt": "two"},
        codebook=coding["codebook"], included=[], excluded=[], absences=[],
    ))
    report = qualbench.build_qualbench([coding], reference=reference)
    profile = report["coding_sets"][0]
    assert profile["transcripts"] == 2
    assert profile["cohort_requests"] == profile["requests"] == 3
    assert profile["cohort_input_tokens"] == 300
    assert profile["cohort_output_tokens"] == 150
    assert profile["cohort_cost_usd"] == profile["cost_usd"] == 6
    assert profile["cohort_elapsed_seconds"] == profile["elapsed_seconds"] == 33
    assert profile["cohort_requests_per_transcript"] == 1.5
    assert profile["cohort_input_tokens_per_transcript"] == 150
    assert profile["cohort_output_tokens_per_transcript"] == 75
    assert profile["cohort_cost_usd_per_transcript"] == 3
    assert profile["cohort_elapsed_seconds_per_transcript"] == 16.5
    assert profile["whole_run_requests"] == 6
    assert profile["whole_run_cost_usd"] == 29
    assert profile["whole_run_elapsed_seconds"] == 153
    assert coding["sources"] == {"t/one.txt": "one", "t/two.txt": "two", "t/three.txt": "three"}
    assert coding["usage"]["cost_usd"] == 29  # original loading remains whole run


def test_usage_follows_cross_study_content_mapping(tmp_path, monkeypatch):
    root, run = _run(
        tmp_path, monkeypatch, sources={"other/renamed.txt": "one", "other/extra.txt": "extra"},
        ledger_rows=[_row("one", r"other\renamed.txt::Partition", 4), _row("extra", "other/extra.txt", 9)],
        attempts=[_attempt("one", r"other\renamed.txt::Partition", 8), _attempt("extra", "other/extra.txt", 10)],
    )
    coding = qualbench.run_coding_set(root, run)
    first = qualbench.reference_coding_set(dict(
        run_id="ref", label="Reference", sources={"base/one.txt": "one"},
        codebook=coding["codebook"], included=[], excluded=[], absences=[],
    ))
    profile = qualbench.build_qualbench([first, coding])["coding_sets"][1]
    assert profile["cohort_cost_usd"] == 4
    assert profile["cohort_elapsed_seconds"] == 8
    assert profile["whole_run_cost_usd"] == 13


def test_usage_keeps_failed_attempt_time_and_uses_reservation_stage(tmp_path, monkeypatch):
    root, run = _run(
        tmp_path, monkeypatch, sources={"t/one.txt": "one"},
        ledger_rows=[_row("success", "t/one.txt", 2)],
        attempts=[_attempt("failed", "t/one.txt", 3), _attempt("success", "t/one.txt", 5),
                  _attempt("later-failure", "t/one.txt", 7)],
    )
    reservations = run.parents[1] / "logs/request_reservations.jsonl"
    reservations.write_text("\n".join(json.dumps(dict(run_id=run.name, **row)) for row in [
        _row("failed", "t/one.txt", 0), _row("later-failure", "t/one.txt", 0, stage="rollup")
    ]), encoding="utf-8")
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["cohort_requests"] == 2
    assert profile["cohort_elapsed_seconds"] == 8
    assert profile["whole_run_requests"] == 3
    assert profile["whole_run_elapsed_seconds"] == 15


def test_missing_ledger_keeps_known_request_time_but_cost_and_tokens_are_unknown(tmp_path, monkeypatch):
    root, run = _run(tmp_path, monkeypatch, sources={"t/one.txt": "one"},
                     attempts=[_attempt("one", "t/one.txt", 5)])
    reservations = run.parents[1] / "logs/request_reservations.jsonl"
    reservations.parent.mkdir(parents=True, exist_ok=True)
    reservations.write_text(json.dumps(dict(run_id=run.name, **_row("one", "t/one.txt", 0))),
                            encoding="utf-8")
    coding = qualbench.run_coding_set(root, run)
    profile = qualbench.coding_profile(coding)
    assert profile["cohort_requests"] == profile["whole_run_requests"] == 1
    assert profile["cohort_elapsed_seconds"] == 5
    for prefix in ("", "cohort_", "whole_run_"):
        for field in ("cost_usd", "input_tokens", "output_tokens", "cached_input_tokens",
                      "cache_write_tokens", "reasoning_tokens", "cost_is_estimated"):
            assert profile[prefix + field] is None
    assert "missing" in profile["usage_note"].lower()
    assert profile["cohort_cost_usd_per_transcript"] is None


@pytest.mark.parametrize("recorded_in", ["run_settings.json", "run_manifest.json"])
@pytest.mark.parametrize("absolute", [False, True])
def test_recorded_ledger_paths_override_conventional_path(tmp_path, monkeypatch, recorded_in, absolute):
    root, run = _run(tmp_path, monkeypatch, ledger_rows=[_row("wrong", "t/one.txt", 99)])
    ledger = root / "separate/study-logs/usage.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps(dict(run_id=run.name, **_row("one", "t/one.txt", 4))), encoding="utf-8")
    data = json.loads((run / recorded_in).read_text()) if (run / recorded_in).exists() else {}
    # Workspace-relative recorded paths survive moving the whole workspace.
    data["cost_ledger_path"] = str(ledger) if absolute else str(ledger.relative_to(root)).replace("/", "\\")
    _json(run / recorded_in, data)
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["whole_run_cost_usd"] == 4
    assert profile["cohort_cost_usd"] == 4


def test_missing_recorded_ledger_does_not_substitute_unrelated_conventional_ledger(tmp_path, monkeypatch):
    root, run = _run(tmp_path, monkeypatch, ledger_rows=[_row("wrong", "t/one.txt", 99)])
    _json(run / "run_manifest.json", {"cost_ledger_path": "missing/custom-ledger.jsonl"})
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["whole_run_cost_usd"] is None
    assert "missing" in profile["whole_run_usage_note"].lower()


def test_settings_ledger_precedes_manifest_and_filters_other_projects(tmp_path, monkeypatch):
    root, run = _run(tmp_path, monkeypatch, ledger_rows=[_row("wrong", "t/one.txt", 99)])
    ledger = root / "usage.jsonl"
    ledger.write_text("\n".join(json.dumps(dict(run_id=run.name, project_id=project, **row))
                               for project, row in [
                                   ("synthetic", _row("one", "t/one.txt", 4)),
                                   ("different", _row("collision", "t/one.txt", 88)),
                               ]), encoding="utf-8")
    settings = json.loads((run / "run_settings.json").read_text())
    settings["cost_ledger_path"] = "usage.jsonl"
    _json(run / "run_settings.json", settings)
    _json(run / "run_manifest.json", {"cost_ledger_path": "does-not-exist.jsonl"})
    assert qualbench.coding_profile(qualbench.run_coding_set(root, run))["cost_usd"] == 4


def test_token_details_and_estimated_cost_follow_latest_entries_and_cohort(tmp_path, monkeypatch):
    def detailed(row, cached, written, reasoning, estimated):
        return dict(row, cached_input_tokens=cached, cache_write_tokens=written,
                    reasoning_tokens=reasoning, cost_is_estimated=estimated)

    root, run = _run(tmp_path, monkeypatch, ledger_rows=[
        detailed(_row("one", "t/one.txt", 99), 99, 99, 99, True),
        detailed(_row("one", "t/one.txt", 2), 10, 20, 30, False),
        detailed(_row("two", "t/two.txt", 3), 1, 2, 3, False),
        detailed(_row("three", "t/three.txt", 4), 100, 200, 300, True),
    ])
    coding = qualbench.run_coding_set(root, run)
    reference = qualbench.reference_coding_set(dict(
        run_id="ref", label="Reference", sources={"t/one.txt": "one", "t/two.txt": "two"},
        codebook=coding["codebook"], included=[], excluded=[], absences=[],
    ))
    report = qualbench.build_qualbench([coding], reference=reference)
    profile = report["coding_sets"][0]
    assert profile["cost_is_estimated"] is profile["cohort_cost_is_estimated"] is False
    assert profile["whole_run_cost_is_estimated"] is True
    assert profile["cohort_cached_input_tokens"] == 11
    assert profile["cohort_cache_write_tokens"] == 22
    assert profile["cohort_reasoning_tokens"] == 33
    assert profile["whole_run_reasoning_tokens"] == 333
    assert profile["cohort_reasoning_tokens_per_transcript"] == 16.5
    assert "cohort_cost_is_estimated_per_transcript" not in profile
    output = qualbench.write_qualbench(report, tmp_path / "export")
    assert "whole_run_cost_is_estimated" in (output / "coding_sets.csv").read_text()


def test_legacy_token_details_are_unknown_and_unsettled_usage_is_not_zero(tmp_path, monkeypatch):
    root, run = _run(tmp_path, monkeypatch, sources={"t/one.txt": "one"},
                     ledger_rows=[_row("one", "t/one.txt", 4)])
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["cost_usd"] == 4
    assert profile["cached_input_tokens"] is profile["cache_write_tokens"] is profile["reasoning_tokens"] is None
    _json(run / "requests/failed.json", dict(_attempt("failed", "t/one.txt", 3), stage_id="coding"))
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["requests"] == 2
    assert profile["cost_usd"] is profile["input_tokens"] is None
    assert "not recorded" in profile["usage_note"].lower()


def test_missing_stage_attribution_does_not_claim_zero_cohort_usage(tmp_path, monkeypatch):
    root, run = _run(tmp_path, monkeypatch, sources={"t/one.txt": "one"},
                     attempts=[_attempt("one", "t/one.txt", 5)])
    profile = qualbench.coding_profile(qualbench.run_coding_set(root, run))
    assert profile["whole_run_requests"] == 1
    assert profile["whole_run_elapsed_seconds"] == 5
    assert profile["cohort_requests"] is profile["cohort_elapsed_seconds"] is None
    assert "stage" in profile["usage_note"].lower()
