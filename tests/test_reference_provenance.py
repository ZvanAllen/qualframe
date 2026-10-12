import json
from pathlib import Path
import subprocess
import sys

import pytest
from openpyxl import Workbook

from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.reference_coding import list_references
from qualframe.qualbench_ui import render_qualbench
from qualframe.web_forms import UploadedFile
from test_qualbench import _cfir_study

ROOT = Path(__file__).resolve().parents[1]


def _workbook(path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inner Setting"
    sheet.append(("CFIR Construct", "Quote", "Explanation"))
    sheet.append(("A. Structure", "We met every week in the old library.", "Neutral"))
    workbook.save(path)
    return path


@pytest.mark.parametrize("independent", [False, True])
@pytest.mark.parametrize("kind", ["table", "cfir"])
def test_reference_upload_records_explicit_provenance(tmp_path, independent, kind):
    root, project, transcript = _cfir_study(tmp_path)
    app = DashboardApp(ProjectRunner(project))
    if kind == "table":
        content = b"Document,Code,Quotation\n1A,A. Structure,We met every week in the old library.\n"
        upload = UploadedFile(filename="coding.csv", content_type="text/csv", content=content)
    else:
        workbook = _workbook(tmp_path / "1A coding.xlsx")
        upload = UploadedFile(filename=workbook.name, content_type="application/octet-stream", content=workbook.read_bytes())
    fields = dict(study_identity=[app.runner.project.project_id], kind=[kind], label=["Reference"], statement=["Synthetic test provenance."])
    if independent:
        fields["independent_human_coding"] = ["true"]
    app.handle_upload("/import/reference-coding", fields, {"upload": [upload]})
    saved = json.loads(list_references(project)[0].read_text(encoding="utf-8"))
    assert saved["independent_human_coding"] is independent
    page = render_qualbench(app)
    assert "This is independent human coding" in page
    assert ("Independent human coding (declared by importer)." if independent else "Independent human coding not declared.") in page


@pytest.mark.parametrize("independent", [False, True])
def test_cli_import_records_provenance_and_keeps_false_default(tmp_path, independent):
    _, project, transcript = _cfir_study(tmp_path)
    workbook = _workbook(tmp_path / "1A coding.xlsx")
    command = [sys.executable, str(ROOT / "scripts/qualbench.py"), "import-reference",
               "--study", str(project), "--id", "synthetic-ref", "--label", "Reference",
               "--statement", "Synthetic provenance", "--by", "Ada", "--map", f"{transcript}={workbook}"]
    if independent:
        command.append("--independent-human-coding")
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    saved = json.loads(list_references(project)[0].read_text(encoding="utf-8"))
    assert saved["independent_human_coding"] is independent


@pytest.mark.parametrize("kind", ["table", "cfir"])
@pytest.mark.parametrize("identity", [None, "another-study"])
def test_reference_import_rejects_stale_or_missing_study_identity_before_writing(tmp_path, kind, identity):
    _, project, _ = _cfir_study(tmp_path)
    app = DashboardApp(ProjectRunner(project))
    fields = dict(kind=[kind], label=["Reference"], statement=["Human coding"], independent_human_coding=["true"])
    if identity is not None:
        fields["study_identity"] = [identity]
    before = list_references(project)
    with pytest.raises(ValueError, match="another study"):
        app.handle_upload("/import/reference-coding", fields, {"upload": [
            UploadedFile(filename="coding.csv" if kind == "table" else "1A.xlsx",
                         content_type="application/octet-stream", content=b"not parsed")
        ]})
    assert list_references(project) == before
    assert not (project.parent / "references/.staging").exists()
