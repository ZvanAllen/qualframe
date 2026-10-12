from __future__ import annotations

import csv
import json

from openpyxl import Workbook
import pytest

from qualframe.reference_coding import (
    build_reference_coding,
    build_reference_from_table,
    load_reference_coding,
    locate_reference_quote,
    save_reference_coding,
)
from test_qualbench import _cfir_study


def _import(tmp_path, kind, source, quote):
    root, project, transcript = _cfir_study(tmp_path)
    (root / transcript).write_text(source, encoding="utf-8")
    common = dict(repo_root=root, project_path=project, reference_id="synthetic-reference",
                  label="Synthetic reference", statement="Synthetic fixture only.", created_by="Tester")
    if kind == "table":
        table = tmp_path / "reference.csv"
        with table.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Document", "Code", "Quotation"])
            writer.writerow(["1A", "A. Structure", quote])
        payload = build_reference_from_table(**common, table=table)
        files = {"table": table}
    else:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Inner Setting"
        sheet.append(["CFIR Construct", "Quote", "Explanation"])
        sheet.append(["A. Structure", quote, "Synthetic annotation"])
        path = tmp_path / "reference.xlsx"
        workbook.save(path)
        workbook.close()
        files = {transcript: path}
        payload = build_reference_coding(**common, files=files)
    return root, project, payload, files


@pytest.mark.parametrize("kind", ["table", "cfir"])
@pytest.mark.parametrize("source,quote,starts,method", [
    ("The bell rang. Then the bell rang. Finally the bell rang.", "the bell rang.", [20, 43], "exact_repeated"),
    ("banana", "ana", [1, 3], "exact_repeated"),
    ("A shared phrase. A  shared phrase. A shared phrase.", "A shared phrase.", [0, 35], "exact_repeated"),
    ("The room is blue. The room is blue.", '“The room is blue.”', [0, 18], "exact_repeated"),
    ("We   met here. We\tmet here.", "We met here.", [0, 15], "normalized_repeated"),
    ('We said “yes”—twice. We said “yes”–twice.', 'We said "yes"-twice.', [0, 21], "normalized_repeated"),
])
def test_repeated_reference_quotes_keep_every_candidate_as_one_annotation(tmp_path, kind, source, quote, starts, method):
    _, _, payload, _ = _import(tmp_path, kind, source, quote)
    [item] = payload["included"]
    assert payload["excluded"] == []
    assert payload["counts"]["included"] == 1
    assert payload["counts"]["quotations_not_found"] == 0
    assert item["match"] == "repeated" and item["anchoring_method"] == method
    assert not {"start", "end", "exact_text"} & item.keys()
    assert [span["start"] for span in item["alternative_spans"]] == starts
    assert len(item["alternative_spans"]) == len(starts)
    for span in item["alternative_spans"]:
        assert span["exact_text"] == source[span["start"]:span["end"]]
        assert span["end"] > span["start"]
    expected_counts = {"included", "excluded", "absences", "unmatched_constructs", "quotations_not_found"}
    if kind == "table":
        expected_counts |= {"presence_only", "documents_not_found"}
    assert payload["counts"].keys() == expected_counts


@pytest.mark.parametrize("kind", ["table", "cfir"])
@pytest.mark.parametrize("source,quote,method", [
    ("A  shared phrase. A shared phrase.", "A shared phrase.", "unique_exact_quote"),
    ("We\n  met in the bright room.", "We met in the bright room.", "normalized_quote_candidate"),
    ("We met every week at the clinic. It was hard at first. Later the residents came to rely on it.",
     "We met every week at the clinic ... came to rely on it.", "ellipsis_parts"),
])
def test_existing_unique_reference_anchors_keep_their_shape_and_precedence(tmp_path, kind, source, quote, method):
    _, _, payload, _ = _import(tmp_path, kind, source, quote)
    [item] = payload["included"]
    start, end, expected_method = locate_reference_quote(source, quote)
    assert item["start"] == start and item["end"] == end
    assert item["exact_text"] == source[start:end]
    assert item["anchoring_method"] == expected_method == method
    assert "match" not in item and "alternative_spans" not in item


@pytest.mark.parametrize("kind", ["table", "cfir"])
@pytest.mark.parametrize("quote", [
    "A quotation that does not occur.",
    "We met at the town hall ... all the children arrived.",
])
def test_unresolved_quotes_and_ambiguous_ellipsis_parts_remain_excluded(tmp_path, kind, quote):
    source = "We met at the town hall. Later we met again. We met at the town hall. Then all the children arrived."
    _, _, payload, _ = _import(tmp_path, kind, source, quote)
    assert payload["included"] == []
    [item] = payload["excluded"]
    assert item["issues"] == ["Quotation not found once in the transcript"]
    assert "alternative_spans" not in item
    assert payload["counts"]["quotations_not_found"] == 1


@pytest.mark.parametrize("kind", ["table", "cfir"])
@pytest.mark.parametrize("repeated", [False, True])
def test_saved_references_round_trip_with_or_without_alternatives(tmp_path, kind, repeated):
    quote = "The room is blue."
    source = quote + (" " + quote if repeated else "")
    root, project, payload, files = _import(tmp_path, kind, source, quote)
    saved = save_reference_coding(project, payload, files)
    original_bytes = saved.read_bytes()
    loaded = load_reference_coding(saved, root)
    assert loaded == json.loads(original_bytes)
    assert saved.read_bytes() == original_bytes
    [item] = loaded["included"]
    if repeated:
        assert item["match"] == "repeated" and len(item["alternative_spans"]) == 2
    else:
        # This is also the existing v1 record shape, without any newly required field.
        assert "alternative_spans" not in item and item["start"] == 0
    assert loaded["kind"] == "qualframe_reference_coding_v1"


@pytest.mark.parametrize("quote", ["", "   ", '""', "“”"])
def test_empty_reference_quote_cannot_create_alternatives(quote):
    from qualframe.reference_coding import _reference_quote_anchor
    assert _reference_quote_anchor("Repeated spaces here. Repeated spaces here.", quote) is None
