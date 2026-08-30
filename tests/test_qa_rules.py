from __future__ import annotations

from qualframe.qa.rules import (
    check_allowed_network_labels,
    check_network_valence_exclusivity,
    check_prompt_version_present,
    check_required_keys,
    check_source_files_covered_by_valence,
    run_qa_on_artifact,
)

ALLOWED = ["ON AMN", "BC AMN", "AB AMN", "NS AMN"]
REQUIRED = ["CFIR Domain", "CFIR Construct", "Quote", "Explanation"]


# --- check_required_keys ---

def test_required_keys_pass():
    row = {"CFIR Domain": "X", "CFIR Construct": "A", "Quote": "q", "Explanation": "e"}
    assert check_required_keys(row, REQUIRED).passed


def test_required_keys_fail():
    row = {"CFIR Domain": "X", "CFIR Construct": "A"}
    result = check_required_keys(row, REQUIRED)
    assert not result.passed
    assert "Quote" in result.details


# --- check_network_valence_exclusivity ---

def test_valence_exclusivity_pass():
    row = {"Facilitator Networks": "ON AMN", "Barrier Networks": "BC AMN"}
    assert check_network_valence_exclusivity(row).passed


def test_valence_exclusivity_fail():
    row = {"Facilitator Networks": "ON AMN; BC AMN", "Barrier Networks": "BC AMN"}
    result = check_network_valence_exclusivity(row)
    assert not result.passed
    assert "BC AMN" in result.details


# --- check_allowed_network_labels ---

def test_allowed_labels_pass():
    row = {"Facilitator Networks": "ON AMN", "Barrier Networks": "BC AMN"}
    assert check_allowed_network_labels(row, ALLOWED).passed


def test_allowed_labels_fail():
    row = {"Facilitator Networks": "ON AMN; UNKNOWN NETWORK"}
    result = check_allowed_network_labels(row, ALLOWED)
    assert not result.passed
    assert "UNKNOWN NETWORK" in result.details


def test_allowed_labels_empty_row_passes():
    assert check_allowed_network_labels({}, ALLOWED).passed


# --- check_source_files_covered_by_valence ---

def test_source_covered_pass():
    row = {
        "Source File(s)": "ON AMN",
        "Facilitator Networks": "ON AMN",
    }
    assert check_source_files_covered_by_valence(row).passed


def test_source_covered_fail():
    row = {
        "Source File(s)": "ON AMN; BC AMN",
        "Facilitator Networks": "ON AMN",
    }
    result = check_source_files_covered_by_valence(row)
    assert not result.passed
    assert "BC AMN" in result.details


def test_source_covered_no_column_skips():
    assert check_source_files_covered_by_valence({}).passed


# --- check_prompt_version_present ---

def test_prompt_sha_present():
    assert check_prompt_version_present("abc123").passed


def test_prompt_sha_missing():
    assert not check_prompt_version_present(None).passed
    assert not check_prompt_version_present("").passed


# --- run_qa_on_artifact dispatcher ---

def test_dispatcher_no_failures_clean_artifact():
    failures = run_qa_on_artifact(
        run_id="r1",
        stage_id="s1",
        prompt_sha256="abc",
        parsed_output={
            "Sheet1": [
                {"CFIR Domain": "X", "CFIR Construct": "A", "Quote": "q", "Explanation": "e"}
            ]
        },
        allowed_network_labels=ALLOWED,
        required_columns=REQUIRED,
    )
    assert failures == []


def test_dispatcher_catches_missing_prompt_sha():
    failures = run_qa_on_artifact(
        run_id="r1",
        stage_id="s1",
        prompt_sha256=None,
        parsed_output=None,
        allowed_network_labels=ALLOWED,
        required_columns=REQUIRED,
    )
    assert any(f.rule_id == "prompt_version_required" for f in failures)


def test_dispatcher_catches_missing_columns():
    failures = run_qa_on_artifact(
        run_id="r1",
        stage_id="s1",
        prompt_sha256="abc",
        parsed_output={"Sheet1": [{"CFIR Domain": "X"}]},
        allowed_network_labels=ALLOWED,
        required_columns=REQUIRED,
    )
    assert any(f.rule_id == "required_columns_present" for f in failures)
    assert all(f.row_index == 0 for f in failures if f.rule_id == "required_columns_present")
