from __future__ import annotations

from qualframe.io.response_parser import parse_markdown_tables


STAGE1_SAMPLE = """\
## Sheet: Innovation Domain

| CFIR Domain | CFIR Construct | Quote | Explanation |
| --- | --- | --- | --- |
| I. INNOVATION DOMAIN | A. Innovation Source | Some quote here. | Facilitating: explanation. |
| I. INNOVATION DOMAIN | B. Innovation Evidence-Base | Another quote. | Facilitating: more text. |

## Sheet: Outer Setting

| CFIR Domain | CFIR Construct | Quote | Explanation |
| --- | --- | --- | --- |
| Outer Setting | X. Something | A quote. | A barrier. |
"""

STAGE2_SAMPLE = """\
Some preamble text.

## Sheet: Innovation

| CFIR Domain | CFIR Construct | Combined Evidence Quotes | Synthesized Explanation | Source File(s) |
|---|---|---|---|---|
| Innovation | A. Innovation Source | "Quote from 2A" – 2A | Facilitator. | 2A; 4A |
| | | "Quote from 4A" – 4A | | |
| Innovation | B. Evidence-Base | "Another quote." – 2A | Mixed. | 2A |
"""

WORKSHEET_HEADING_SAMPLE = """\
## Worksheet 1: Innovation

| CFIR Domain | CFIR Construct | Quote | Explanation |
| --- | --- | --- | --- |
| Innovation | A. Source | A quote. | Facilitating. |
"""

NO_HEADING_TABLE = """\
Some intro text.

| Col A | Col B |
| --- | --- |
| val1 | val2 |
| val3 | val4 |
"""


def test_stage1_two_sheets():
    result = parse_markdown_tables(STAGE1_SAMPLE)
    assert set(result.keys()) == {"Innovation Domain", "Outer Setting"}
    assert len(result["Innovation Domain"]) == 2
    assert result["Innovation Domain"][0]["CFIR Construct"] == "A. Innovation Source"


def test_stage2_continuation_rows_merged():
    result = parse_markdown_tables(STAGE2_SAMPLE)
    assert "Innovation" in result
    rows = result["Innovation"]
    # Two substantive rows (A and B); continuation row merged into A
    assert len(rows) == 2
    # The quote cell for A should contain both quotes
    quote_a = rows[0].get("Combined Evidence Quotes", "")
    assert "2A" in quote_a
    assert "4A" in quote_a


def test_worksheet_n_heading_normalised():
    result = parse_markdown_tables(WORKSHEET_HEADING_SAMPLE)
    assert "Innovation" in result
    assert len(result["Innovation"]) == 1


def test_no_heading_falls_back_to_output_key():
    result = parse_markdown_tables(NO_HEADING_TABLE)
    assert "output" in result
    assert len(result["output"]) == 2
    assert result["output"][0]["Col A"] == "val1"


def test_empty_text_returns_empty():
    assert parse_markdown_tables("") == {}


def test_narrative_only_returns_empty():
    assert parse_markdown_tables("Some narrative without any tables.") == {}


def test_row_dict_keys_match_headers():
    result = parse_markdown_tables(STAGE1_SAMPLE)
    for row in result["Innovation Domain"]:
        assert set(row.keys()) == {"CFIR Domain", "CFIR Construct", "Quote", "Explanation"}


STAGE3_MULTILINE_CELL_SAMPLE = """\
## Sheet: Innovation

| CFIR Domain | CFIR Construct | Quote | Page Number | Explanation |
|---|---|---|---|---|
| Innovation | Innovation Source | Preceding sentence one. Preceding sentence two.
"Original quote here."
Following sentence one. | • 6 | The innovation source was facilitating. |
| Innovation | B. Evidence-Base | A single-line quote. | • 3 | Another explanation. |
"""


def test_stage3_multiline_quote_cell_rejoined():
    """Quote cells split across multiple lines by embedded newlines must be parsed."""
    result = parse_markdown_tables(STAGE3_MULTILINE_CELL_SAMPLE)
    assert "Innovation" in result
    rows = result["Innovation"]
    assert len(rows) == 2
    quote = rows[0]["Quote"]
    assert "Preceding sentence one" in quote
    assert "Original quote here" in quote
    assert "Following sentence one" in quote
    assert rows[0]["Page Number"] == "• 6"
