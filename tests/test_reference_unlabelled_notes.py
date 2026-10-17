"""Synthetic coverage of notes in workbook and table columns without headings."""
from __future__ import annotations

import csv

from openpyxl import Workbook
import pytest

from qualframe import reference_coding
from test_qualbench import _cfir_study


def _workbook(path, rows, title="Inner Setting"):
    book = Workbook()
    sheet = book.active
    sheet.title = title
    for row in rows:
        sheet.append(row)
    book.save(path)
    book.close()


def test_cfir_workbook_keeps_unlabelled_marks_and_labelled_notes(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    header = ["CFIR Construct", "Quote", "Explanation", "Reviewer", None, "  "]
    row = ["A. Structure", "Synthetic passage.", "Synthetic explanation", "Checked", "x", 0]
    row += [None] * (26 - len(row)) + ["margin mark"]
    _workbook(path, [["Synthetic checklist"], header, row,
                     ["A. Structure", "No relevant quote found", None, None, None]])

    rows, skipped = reference_coding.read_cfir_coding_workbook(path)

    assert skipped == []
    assert rows[0] == dict(sheet="Inner Setting", row=3, domain="Inner Setting",
                           construct="A. Structure", quote="Synthetic passage.",
                           explanation="Synthetic explanation",
                           notes={"reviewer": "Checked", "column E": "x", "column F": "0",
                                  "column AA": "margin mark"})
    assert rows[1]["notes"] == {}


def test_cfir_repeated_header_reassigns_unlabelled_columns(tmp_path):
    path = tmp_path / "synthetic.xlsx"
    _workbook(path, [["CFIR Construct", "Quote", "Notes", None],
                     ["A. Structure", "First synthetic passage.", "labelled", "first mark"],
                     ["CFIR Construct", "Quote", None, "Notes"],
                     ["A. Structure", "Second synthetic passage.", "second mark", "labelled"]])

    rows, _ = reference_coding.read_cfir_coding_workbook(path)

    assert [row["notes"] for row in rows] == [
        {"notes": "labelled", "column D": "first mark"},
        {"notes": "labelled", "column C": "second mark"},
    ]


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_coding_table_keeps_unlabelled_marks_and_original_label_case(tmp_path, suffix):
    path = tmp_path / f"synthetic.{suffix}"
    header = ["Document", "Code", "Quotation", "Reviewer Notes", "", "  "]
    row = ["Synthetic document", "test-code", "Synthetic passage.", "Checked", "x", 0]
    row += [None] * (26 - len(row)) + ["margin mark"]
    if suffix == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([header, row, ["Another document", "test-code"]])
    else:
        _workbook(path, [header, row, ["Another document", "test-code"]], "Synthetic table")

    rows, used = reference_coding.read_coding_table(path)

    assert used == {"document": "Document", "code": "Code", "quotation": "Quotation"}
    assert rows[0] == dict(row=2, document="Synthetic document", code="test-code",
                           quote="Synthetic passage.",
                           notes={"Reviewer Notes": "Checked", "column E": "x", "column F": "0",
                                  "column AA": "margin mark"})
    assert rows[1] == dict(row=3, document="Another document", code="test-code", quote="", notes={})


@pytest.mark.parametrize("kind", ["cfir", "csv", "xlsx"])
@pytest.mark.parametrize("headings,values,generated", [
    (["column E", ""], ["labelled review", "unlabelled mark"],
     {"column E (unlabelled)": "unlabelled mark"}),
    (["", "COLUMN D"], ["unlabelled mark", "later labelled review"],
     {"column D (unlabelled)": "unlabelled mark"}),
    (["", "column D", "Column D (Unlabelled)", "COLUMN D (UNLABELLED 2)", ""],
     ["unlabelled mark", "labelled review", "labelled suffix", "second labelled suffix", "another mark"],
     {"column D (unlabelled 3)": "unlabelled mark", "column H": "another mark"}),
])
def test_generated_note_keys_preserve_all_labelled_and_unlabelled_values(tmp_path, kind, headings, values, generated):
    header = (["CFIR Construct", "Quote", "Explanation"] if kind == "cfir"
              else ["Document", "Code", "Quote"])
    prefix = (["A. Structure", "Synthetic passage.", "Synthetic explanation"] if kind == "cfir"
              else ["Synthetic document", "test-code", "Synthetic passage."])
    # The same unnamed values must use the same keys when a labelled cell is empty.
    rows = [header + headings, prefix + values,
            prefix + ["" if heading else value for heading, value in zip(headings, values)]]
    path = tmp_path / ("synthetic.csv" if kind == "csv" else "synthetic.xlsx")
    if kind == "csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows(rows)
    else:
        _workbook(path, rows)
    reader = (reference_coding.read_cfir_coding_workbook if kind == "cfir"
              else reference_coding.read_coding_table)

    imported, _ = reader(path)

    labelled = {(heading.casefold() if kind == "cfir" else heading): value
                for heading, value in zip(headings, values) if heading}
    assert imported[0]["notes"] == labelled | generated
    assert imported[1]["notes"] == generated
    assert len({key.casefold() for key in imported[0]["notes"]}) == len(imported[0]["notes"])


@pytest.mark.parametrize("kind", ["cfir", "table"])
def test_unlabelled_notes_do_not_change_reference_coding(tmp_path, monkeypatch, kind):
    root, project, transcript = _cfir_study(tmp_path)
    common = dict(repo_root=root, project_path=project, reference_id="synthetic-reference",
                  label="Synthetic reference", statement="Synthetic fixture only.", created_by="Tester")
    if kind == "cfir":
        path = tmp_path / "synthetic.xlsx"
        _workbook(path, [["CFIR Construct", "Quote", "Explanation", "Notes", None],
                         ["A. Structure", "We met every week in the old library.", None, "checked", "keep"],
                         ["A. Structure", "No relevant quote found", None, "checked", "absent"],
                         ["A. Structure", "Synthetic passage not in the transcript.", None, "checked", "exclude"]])
        reader_name = "read_cfir_coding_workbook"
        build = lambda: reference_coding.build_reference_coding(**common, files={transcript: path})
    else:
        path = tmp_path / "synthetic.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerows([
                ["Document", "Code", "Quotation", "Notes", ""],
                ["1A", "A. Structure", "We met every week in the old library.", "checked", "keep"],
                ["1A", "A. Structure", "", "checked", "presence"],
                ["1A", "A. Structure", "Synthetic passage not in the transcript.", "checked", "exclude"],
            ])
        reader_name = "read_coding_table"
        build = lambda: reference_coding.build_reference_from_table(**common, table=path)

    updated = build()
    reader = getattr(reference_coding, reader_name)

    def without_unlabelled_notes(path):
        rows, metadata = reader(path)
        for row in rows:
            row["notes"] = {key: value for key, value in row["notes"].items() if key != "column E"}
        return rows, metadata

    monkeypatch.setattr(reference_coding, reader_name, without_unlabelled_notes)
    prior = build()
    assert updated["counts"] == prior["counts"]
    for bucket in ("included", "excluded", "absences"):
        assert len(updated[bucket]) == len(prior[bucket])
        for current, previous in zip(updated[bucket], prior[bucket]):
            assert current["notes"]["column E"]
            assert {key: value for key, value in current["notes"].items() if key != "column E"} == previous["notes"]
            assert {key: value for key, value in current.items() if key != "notes"} == {
                key: value for key, value in previous.items() if key != "notes"
            }
