import json
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook
from test_study_setup import make_test_repo

from qualframe.codebook_excel import convert_excel, read_excel
from qualframe.codebook_import_ui import confirmation_view, mapping_view
from qualframe.config import load_project_manifest
from qualframe.excel_import_workflow import ExcelImportWorkflow
from qualframe.io.files import sha256_for_file
from qualframe.models import StudyCreationRequest
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
