import json

from qualframe.reference_coding import build_reference_from_table


def test_table_reference_keeps_explicit_active_flags_and_defaults_legacy_codes_to_active(tmp_path):
    project = tmp_path / "studies/synthetic/project.yaml"
    project.parent.mkdir(parents=True)
    project.write_text(json.dumps(dict(
        project_id="synthetic", framework="unused-framework.yaml", pipeline="unused-pipeline.yaml",
        codebook="codebook.yaml", paths={"raw_transcripts": "transcripts"},
    )), encoding="utf-8")
    codes = [
        dict(id="current", label="Current", definition="Current code", active=True),
        dict(id="retired", label="Retired", definition="Retired code", active=False),
        dict(id="legacy", label="Legacy", definition="No active field in the source"),
    ]
    (tmp_path / "codebook.yaml").write_text(json.dumps(dict(
        id="synthetic", version="1", name="Synthetic", codes=codes,
    )), encoding="utf-8")
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts/doc.txt").write_text("The synthetic room is blue.", encoding="utf-8")
    table = tmp_path / "coding.csv"
    table.write_text("Document,Code,Quotation\ndoc.txt,current,The synthetic room is blue.\n", encoding="utf-8")
    payload = build_reference_from_table(
        repo_root=tmp_path, project_path=project, reference_id="synthetic-ref", label="Synthetic",
        statement="Synthetic fixture only.", table=table, created_by="Tester",
    )
    assert {code["id"]: code["active"] for code in payload["codebook"]["codes"]} == {
        "current": True, "retired": False, "legacy": True,
    }
    assert payload["counts"]["included"] == 1
