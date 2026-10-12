from copy import deepcopy
from types import SimpleNamespace

import pytest

from qualframe.qualbench import build_qualbench, write_qualbench
from qualframe.qualbench_ui import _report_html
from test_qualbench import _set


@pytest.mark.parametrize("field,value", [("label", "Changed label"), ("definition", "Changed meaning"),
    ("parent_label", "B. Other"), ("parent_id", "q")])
def test_code_content_differences_warn_without_blocking(tmp_path, field, value):
    left, right = _set("left", []), _set("right", [])
    right["codebook"] = deepcopy(right["codebook"])
    right["codebook"]["codes"][1][field] = value
    report = build_qualbench([left, right])
    assert report["presence"]
    assert report["codebook_differences"] == [dict(left="left", right="right", code_id="c", fields=[field])]
    assert "Code c differs" in report["warnings"][0]
    folder = write_qualbench(report, tmp_path / "report")
    assert "Code c differs" in (folder / "README.md").read_text(encoding="utf-8")
    page = _report_html(SimpleNamespace(_file_link=lambda path, label: label), folder)
    assert "Codebook compatibility" in page and "Code c differs" in page


def test_section_and_code_order_do_not_trigger_semantic_warning():
    left, right = _set("left", []), _set("right", [])
    right["codebook"]["codes"] = list(reversed(deepcopy(right["codebook"]["codes"])))
    right["codebook"]["codes"][0]["section"] = "Display addendum"
    report = build_qualbench([left, right])
    assert report["warnings"] == [] and report["codebook_differences"] == []


def test_reference_code_definition_is_checked_too():
    model, reference = _set("model", []), _set("reference", [], kind="reference")
    reference["codebook"]["codes"][0]["definition"] = "Earlier definition"
    report = build_qualbench([model], reference=reference)
    assert report["codebook_differences"][0]["right"] == "reference"
