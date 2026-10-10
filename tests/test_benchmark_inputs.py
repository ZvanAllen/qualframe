import copy
import json
from pathlib import Path

import pytest

from qualframe.benchmark_inputs import build_source_mapping, historical_cfir_payload
from qualframe.io.files import sha256_for_file
from qualframe.run_comparison import compare_raw_payloads


def fixture(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    for name in ["first.txt", "second.txt"]:
        (root / name).write_text(
            "A clear quote. We\u00a0can’t attend. Echo. Echo.", encoding="utf-8"
        )
    codebook = {
        "id": "cfir-reference",
        "version": "frozen",
        "codes": [
            dict(
                id="innovation-source",
                label="A. Source",
                raw_label="A. Source",
                parent_label="",
                definition="Synthetic source definition",
                domain="INNOVATION DOMAIN",
            ),
            dict(
                id="innovation-design",
                label="B. Design",
                raw_label="B. Design",
                parent_label="",
                definition="Synthetic design definition",
                domain="INNOVATION DOMAIN",
            ),
        ],
    }
    run = root / "artifacts" / "old"
    run.mkdir(parents=True)
    artifact = dict(
        run_id="old",
        stage_id="transcript_to_cfir",
        input_path="first.txt",
        input_sha256=sha256_for_file(root / "first.txt"),
        prompt_ref="frozen-prompt",
        prompt_sha256="abc",
        response_text="Saved original response.",
        model="historical-model",
        provider="synthetic",
        timestamp_utc="2026-01-01T00:00:00Z",
        parsed_output={
            "Innovation": [
                {
                    "CFIR Construct": "A. Source",
                    "Quote": "A clear quote.",
                    "Explanation": "Source rationale",
                },
                {"CFIR Construct": "B. Design", "Quote": "We can't attend."},
                {"CFIR Construct": "A. Source", "Quote": "Echo."},
                {"CFIR Construct": "Unknown", "Quote": "A clear quote."},
                {"CFIR Construct": "A. Source", "Quote": "No relevant quote found"},
                {"CFIR Construct": "Unknown", "Quote": "No relevant quote found"},
                {"Other column": "Invalid row"},
            ]
        },
    )
    (run / "coding.json").write_text(json.dumps(artifact), encoding="utf-8")
    manifest = dict(run_id="old", project_id="original-project", artifact_paths=["coding.json"])
    (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    plan = dict(
        discovered_inputs=[
            dict(path=name, kind="transcript", sha256=sha256_for_file(root / name))
            for name in ["first.txt", "second.txt"]
        ],
        planned_stage_runs=[
            dict(stage_id="transcript_to_cfir", input_path=name, domain="Innovation")
            for name in ["first.txt", "second.txt"]
        ],
    )
    (run / "run_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return root, run, codebook


def payload(root, run, book, **kwargs):
    return historical_cfir_payload(root, run, ["first.txt"], book, benchmark_id="pilot", **kwargs)


def test_historical_payload_retains_invalid_rows_absences_and_provenance(tmp_path):
    root, run, book = fixture(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = payload(root, run, book)
    assert len(result["included"]) == 2
    assert len(result["excluded"]) == 4
    assert len(result["absences"]) == 1
    assert result["included"][1]["exact_text"] == "We\u00a0can’t attend."
    assert result["included"][1]["proposed_quotation"] == "We can't attend."
    assert result["configuration_fingerprint"] is None
    assert result["index_sha256"] is None
    provenance = result["benchmark_provenance"]
    assert provenance["human_reference"] is False
    assert provenance["original_configuration_available"] is False
    assert provenance["excluded_original_sources"][0]["path"] == "second.txt"
    assert provenance["prompt_sha256s"] == ["abc"]
    assert provenance["project_id"] == "original-project" and result["project_id"] == "pilot"
    assert all(path.read_bytes() == content for path, content in before.items())
    assert payload(root, run, book) == result


def test_explicit_legacy_artifacts_and_copied_source_mapping_compare(tmp_path):
    root, run, book = fixture(tmp_path)
    manifest = json.loads((run / "run_manifest.json").read_text())
    manifest["artifact_paths"] = []
    (run / "run_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="explicit artifact mapping"):
        payload(root, run, book)
    a = payload(root, run, book, artifact_paths={"first.txt": ["coding.json"]})
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / "imported.txt").write_bytes((root / "first.txt").read_bytes())
    new_run = managed / "new-run"
    new_run.mkdir()
    artifact = json.loads((run / "coding.json").read_text())
    artifact.update(run_id="new", input_path="imported.txt")
    (new_run / "coding.json").write_text(json.dumps(artifact))
    (new_run / "run_manifest.json").write_text(
        json.dumps(
            dict(
                run_id="new",
                project_id="new-project",
                artifact_paths=["coding.json"],
                configuration_fingerprint="frozen-new",
            )
        )
    )
    old_mapping = build_source_mapping(root, ["first.txt"])
    b = historical_cfir_payload(
        managed,
        new_run,
        ["imported.txt"],
        book,
        benchmark_id="pilot",
        source_mapping={"imported.txt": old_mapping["first.txt"]},
        expected_domains=["Innovation"],
    )
    report = compare_raw_payloads(a, b)
    assert all(value == 1 for value in report["summary"].values())
    assert b["configuration_fingerprint"] == "frozen-new"
    assert not b["benchmark_provenance"]["original_cohort_known"]
    assert (
        b["benchmark_provenance"]["source_mapping"]["imported.txt"]["original_path"] == "first.txt"
    )


def test_missing_domains_empty_tables_source_drift_and_wrong_artifacts_fail(tmp_path):
    root, run, book = fixture(tmp_path)
    with pytest.raises(ValueError, match="each expected CFIR domain"):
        payload(root, run, book, expected_domains=["Innovation", "Individuals"])
    mapping = build_source_mapping(root, ["first.txt"])
    (root / "first.txt").write_text("Changed content.")
    with pytest.raises(ValueError, match="immutable source mapping"):
        payload(root, run, book, source_mapping=mapping)
    (root / "first.txt").write_text(
        "A clear quote. We\u00a0can’t attend. Echo. Echo.", encoding="utf-8"
    )
    path = run / "coding.json"
    artifact = json.loads(path.read_text())
    artifact["parsed_output"]["Innovation"] = []
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="empty historical domain"):
        payload(root, run, book)
    artifact["stage_id"] = "participant_parent_construct_rollup"
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="Only original"):
        payload(root, run, book, artifact_paths={"first.txt": "coding.json"})


def test_mapping_and_run_identity_cannot_be_silently_overridden(tmp_path):
    root, run, book = fixture(tmp_path)
    mapping = build_source_mapping(root, ["first.txt"])
    changed = copy.deepcopy(mapping)
    changed["first.txt"]["original_path"] = "second.txt"
    with pytest.raises(ValueError, match="mapping identity"):
        payload(root, run, book, source_mapping=changed)
    with pytest.raises(ValueError, match="exactly the selected"):
        payload(root, run, book, source_mapping={})
    with pytest.raises(ValueError, match="outside its declared root"):
        payload(root, run, book, artifact_paths={"first.txt": "../outside.json"})
    artifact = json.loads((run / "coding.json").read_text())
    artifact["run_id"] = "different"
    (run / "coding.json").write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="run/source identity"):
        payload(root, run, book)


def test_ambiguous_historical_catalog_entries_are_reported_not_rewritten(tmp_path):
    root, run, book = fixture(tmp_path)
    book["codes"].append(dict(book["codes"][0], definition="A different frozen definition"))
    before = copy.deepcopy(book)
    result = payload(root, run, book)
    assert result["codebook"] == before and book == before
    assert result["benchmark_provenance"]["ambiguous_catalog_code_ids"] == ["innovation-source"]
    assert {row["code_id"] for row in result["included"]} == {"innovation-design"}
    assert not result["absences"]


def test_qualified_delimiter_sensitivity_preserves_default_and_refuses_synonyms(tmp_path):
    root, run, book = fixture(tmp_path)
    for parent, identifier in [
        ("H. Innovation Deliverers", "deliverers"),
        ("I. Innovation Recipients", "recipients"),
    ]:
        book["codes"].append(
            dict(
                id=identifier + "-motivation",
                label=parent + " / 4. Motivation",
                raw_label="4. Motivation",
                parent_label=parent,
                definition="Synthetic motivation",
                domain="INNOVATION DOMAIN",
            )
        )
    labels = [
        "H4. Innovation Deliverers – Motivation",
        "H4. Innovation Deliverers — Motivation",
        "H4. Innovation Deliverers - Motivation",
        "H. Innovation Deliverers:Motivation",
        "H4. Innovation Delivery – Motivation",
        "H4. Innovation Deliverers – Motivation (general)",
        "H4. Innovation Deliverers–Motivation",
        "H4. Innovation Deliverers – Motivation – Extra",
        "4. Motivation",
    ]
    path = run / "coding.json"
    artifact = json.loads(path.read_text())
    artifact["parsed_output"]["Innovation"] = [
        {"CFIR Construct": label, "Quote": "A clear quote."} for label in labels
    ]
    path.write_text(json.dumps(artifact), encoding="utf-8")
    original_bytes = path.read_bytes()
    strict = payload(root, run, book)
    assert len(strict["included"]) == 1 and len(strict["excluded"]) == 8
    revised = payload(root, run, book, code_label_policy="qualified_delimiters_v2")
    assert len(revised["included"]) == 4 and len(revised["excluded"]) == 5
    assert revised["benchmark_provenance"]["normalization_version"].endswith(
        "qualified_delimiters_v2"
    )
    aliases = revised["benchmark_provenance"]["code_label_aliases"]
    assert len(aliases) == 3 and {a["canonical_code_id"] for a in aliases} == {
        "deliverers-motivation"
    }
    assert [a["original_label"] for a in aliases] == labels[:3]
    assert revised["included"][0]["code_label_normalization"] == aliases[0]
    assert revised["included"][0]["original_construct"] == labels[0]
    assert payload(root, run, book) == strict and path.read_bytes() == original_bytes
    assert "code_label_policy" not in strict["benchmark_provenance"]
    assert "code_label_aliases" not in strict["benchmark_provenance"]
    with pytest.raises(ValueError, match="Unknown CFIR"):
        payload(root, run, book, code_label_policy="semantic_guess")
