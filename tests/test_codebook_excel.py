import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from test_study_setup import make_test_repo

from qualframe.codebook_excel import convert_excel, read_excel
from qualframe.codebook_import_ui import confirmation_view, mapping_view
from qualframe.config import load_codebook_spec, load_project_manifest
from qualframe.excel_import_workflow import ExcelImportWorkflow
from qualframe.io.files import sha256_for_file
from qualframe.io.response_parser import coding_response_schema
from qualframe.models import CodebookPartitionPolicy, StudyCreationRequest
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.study_setup import StudyWorkspace


def workbook_bytes(rows, sheet="Codes"):
    book = Workbook()
    book.active.title = sheet
    for row in rows:
        book.active.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return stream.getvalue()


ROWS = [
    ["ID", "Label", "Definition", "Parent ID", "Examples"],
    ["01", "Access", "Obtaining a service", "", "First example\nSecond example"],
    ["01a", "Hours", "Service opening times", "01", ""],
]
OPTIONS = {
    "sheet": "Codes",
    "header_row": "1",
    "id": "A",
    "label": "B",
    "definition": "C",
    "parent_id": "D",
    "examples": "E",
    "name": "Service access",
    "codebook_id": "service",
    "version": "1.0",
}


def test_excel_hierarchy_and_exact_ids():
    sheet = read_excel(workbook_bytes(ROWS))[0]
    codebook = convert_excel(
        sheet,
        1,
        {k: OPTIONS[k] for k in ("id", "label", "definition", "parent_id", "examples")},
        name="Service",
        codebook_id="service",
        version="1",
    )
    assert [c.id for c in codebook.codes] == ["01", "01a"]
    assert codebook.codes[1].parent_id == "01"
    assert codebook.codes[0].examples == ["First example", "Second example"]


@pytest.mark.parametrize(
    "rows,match",
    [
        ([ROWS[0], ["a", "A", "", "", ""]], "missing Definition"),
        ([ROWS[0], ["a", "A", "definition", "", ""], ["a", "B", "definition", "", ""]], "unique"),
        ([ROWS[0], ["a", "A", "definition", "b", ""]], "unknown parent"),
        ([ROWS[0], ["a", "A", "definition", "b", ""], ["b", "B", "definition", "a", ""]], "cycle"),
    ],
)
def test_invalid_codes_fail_before_conversion(rows, match):
    sheet = read_excel(workbook_bytes(rows))[0]
    with pytest.raises(ValueError, match=match):
        convert_excel(
            sheet,
            1,
            {k: OPTIONS[k] for k in ("id", "label", "definition", "parent_id")},
            name="Test",
            codebook_id="test",
            version="1",
        )


def test_formula_and_invalid_workbooks_are_rejected():
    with pytest.raises(ValueError, match="formulas"):
        read_excel(workbook_bytes([["ID"], ["=1+1"]]))
    with pytest.raises(ValueError, match="Unable to read"):
        read_excel(b"not an xlsx")


def test_preview_commit_preserves_original_and_rejects_replay(tmp_path: Path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Excel import study", data_classification="synthetic")
    )
    project = root / created.project_manifest_path
    before = project.read_bytes()
    workflow = ExcelImportWorkflow(workspace, project)
    content = workbook_bytes(ROWS)
    token = workflow.stage("Codebook.xlsx", content, "Researcher", "Import definitions")
    options = {**OPTIONS, "token": token}
    assert "Map your columns" in mapping_view(workflow, options)
    assert "2 validated codes" in confirmation_view(workflow, options)
    assert project.read_bytes() == before
    record = workflow.commit(token, options)
    assert (root / record.original_path).read_bytes() == content
    assert sha256_for_file(root / record.original_path) == record.original_sha256
    conversion = json.loads((root / record.conversion_path).read_text())
    assert conversion["mapping"]["id"] == "A"
    assert conversion["normalized_sha256"] == record.sha256
    # New studies start without a codebook, so the first import is version 1.
    assert load_project_manifest(project).codebook.endswith("codebook_v1.yaml")
    with pytest.raises(ValueError, match="already been imported"):
        workflow.commit(token, options)


def test_preview_token_and_source_integrity(tmp_path: Path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Excel safety study", data_classification="synthetic")
    )
    workflow = ExcelImportWorkflow(workspace, root / created.project_manifest_path)
    with pytest.raises(ValueError, match="identifier"):
        workflow.load("../../elsewhere")
    token = workflow.stage("Codes.xlsx", workbook_bytes(ROWS), "Reviewer", "Test")
    (workflow.root / token / "source.xlsx").write_bytes(b"changed")
    with pytest.raises(ValueError, match="source changed"):
        workflow.convert(token, OPTIONS)


def test_header_selection_duplicate_headers_and_html_escape(tmp_path: Path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Preview safety study", data_classification="synthetic")
    )
    workflow = ExcelImportWorkflow(workspace, root / created.project_manifest_path)
    rows = [
        ["Instructions"],
        ["Value", "Value", "Definition"],
        ["01", "<script>bad</script>", "Text"],
    ]
    token = workflow.stage("Codes.xlsx", workbook_bytes(rows), "Reviewer", "Test")
    options = {**OPTIONS, "token": token, "header_row": "2", "parent_id": "", "examples": ""}
    page = mapping_view(workflow, options)
    assert "&lt;script&gt;" in page and "<script>bad" not in page
    codebook, _, _ = workflow.convert(token, options)
    assert codebook.codes[0].id == "01"
    with pytest.raises(ValueError, match="different column"):
        workflow.convert(token, {**options, "label": "A"})



def convert_active_rows(rows, *, header_row=1, include_active=True):
    mapping = {k: OPTIONS[k] for k in ("id", "label", "definition", "parent_id", "examples")}
    if include_active:
        mapping["active"] = "F"
    return convert_excel(
        read_excel(workbook_bytes(rows))[0], header_row, mapping,
        name="Service", codebook_id="service", version="1",
    )


@pytest.mark.parametrize(
    "value,expected",
    [
        ("yes", True), (" NO ", False), ("TrUe", True), ("false", False),
        ("1", True), ("0", False), (1, True), (0, False),
        (True, True), (False, False), (None, True), ("   ", True),
    ],
)
def test_optional_active_values(value, expected):
    codebook = convert_active_rows([ROWS[0] + ["Active"], ROWS[1] + [value]])
    assert codebook.codes[0].active is expected


@pytest.mark.parametrize("value", ["maybe", "on", "off", "y", "n", 2, -1])
def test_invalid_active_identifies_actual_excel_row(value):
    rows = [["Instructions"], ROWS[0] + ["Active"], [], ROWS[1] + [value]]
    with pytest.raises(ValueError, match=r"Row 4: Active.*yes/no.*true/false.*1/0"):
        convert_active_rows(rows, header_row=2)


def test_unmapped_active_defaults_to_true():
    codebook = convert_active_rows(
        [ROWS[0] + ["Active"], ROWS[1] + ["no"], ROWS[2] + ["invalid"]],
        include_active=False,
    )
    assert all(code.active for code in codebook.codes)
    assert all(code.active for code in convert_active_rows(ROWS, include_active=False).codes)


@pytest.mark.parametrize(
    "strategy,group", [("full_codebook", "all_codes"), ("per_top_level_category", "01")],
)
def test_inactive_imported_parent_preserves_hierarchy_but_not_model_options(strategy, group):
    codebook = convert_active_rows([
        ROWS[0] + ["Active"], ROWS[1] + ["no"], ROWS[2] + ["yes"],
    ])
    assert codebook.codes[0].active is False
    assert codebook.codes[1].parent_id == "01"
    runner = SimpleNamespace(
        codebook=codebook, method=SimpleNamespace(partitioning=CodebookPartitionPolicy(strategy=strategy)),
    )
    stage = SimpleNamespace(domain_iterations=[], input_source="raw_transcripts", use_codebook=True)
    partitions = ProjectRunner._generic_codebook_partitions(runner, stage)
    assert set(partitions) == {group}
    codes = json.loads(partitions[group])["codes"]
    assert [code["id"] for code in codes] == ["01a"]
    schema = coding_response_schema([code["id"] for code in codes])
    assert schema["properties"]["codings"]["items"]["properties"]["code_id"]["enum"] == ["01a"]


def test_active_mapping_preview_and_saved_version(tmp_path: Path):
    root = make_test_repo(tmp_path)
    workspace = StudyWorkspace(root)
    created = workspace.create(
        StudyCreationRequest(title="Inactive parent import", data_classification="synthetic")
    )
    workflow = ExcelImportWorkflow(workspace, root / created.project_manifest_path)
    token = workflow.stage(
        "Codes.xlsx", workbook_bytes([ROWS[0] + ["Active"], ROWS[1] + [False], ROWS[2] + [True]]),
        "Reviewer", "Test hierarchy-only parent",
    )
    mapping_page = mapping_view(workflow, {"token": token})
    active_control = mapping_page.split('<select name="active">', 1)[1].split('</select>', 1)[0]
    assert '<option value="F" selected>' in active_control
    assert "blank" in mapping_page and "yes/no" in mapping_page
    options = {**OPTIONS, "token": token, "active": "F"}
    preview = confirmation_view(workflow, options)
    assert "<th>Active</th>" in preview
    assert "<td>No</td>" in preview and "<td>Yes</td>" in preview
    assert "1 active; 1 inactive" in preview
    record = workflow.commit(token, options)
    saved = load_codebook_spec(root / record.destination_path)
    assert [code.active for code in saved.codes] == [False, True]
    assert saved.codes[1].parent_id == "01"
    conversion = json.loads((root / record.conversion_path).read_text())
    assert conversion["mapping"]["active"] == "F"



def test_downloadable_example_has_active_column_and_preserves_demo_codes():
    fixture_dir = Path(__file__).resolve().parents[1] / "demo" / "datasets" / "ai-scribe"
    expected = load_codebook_spec(fixture_dir / "codebook.yaml")
    sheet = read_excel((fixture_dir / "codebook.xlsx").read_bytes())[0]
    assert sheet.rows[0][-1] == "Active"
    imported = convert_excel(
        sheet, 1,
        {"id": "A", "label": "B", "parent_id": "C", "definition": "D",
         "inclusion_guidance": "E", "exclusion_guidance": "F", "active": "G"},
        name=expected.name, codebook_id=expected.id, version=expected.version,
    )
    assert len(imported.codes) == len(expected.codes) == 15
    for actual, original in zip(imported.codes, expected.codes, strict=True):
        assert actual.active is True
        for field in ("id", "label", "parent_id", "definition", "inclusion_guidance", "exclusion_guidance"):
            assert (getattr(actual, field) or "") == (getattr(original, field) or "")
