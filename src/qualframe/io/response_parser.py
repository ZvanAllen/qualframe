from __future__ import annotations

import re


# Matches headings like:
#   ## Sheet: Innovation Domain
#   ## Sheet: Innovation
#   ## Worksheet 1: Innovation
#   ## Innovation          (bare heading followed by a pipe table)
_SHEET_HEADING = re.compile(
    r"^##\s+(?:Sheet:|Worksheet\s+\d+:)?\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# A pipe-table row: starts and ends with |
_TABLE_ROW = re.compile(r"^\|(.+)\|$")

# Separator row: only |, -, :, and whitespace
_SEPARATOR_ROW = re.compile(r"^\|[\s\-:|]+\|$")


def _parse_row(line: str) -> list[str]:
    """Split a pipe-table row into cell strings."""
    return [cell.replace("\\|", "|").strip() for cell in line.strip().strip("|").split("|")]


def _merge_continuation_rows(rows: list[list[str]]) -> list[list[str]]:
    """Merge rows where the first cell is empty into the previous row's cells.

    Stage 2 responses use empty-first-column rows to continue long quote lists
    within a cell.  We append the non-empty continuation cell values to the
    matching column of the last substantive row.
    """
    merged: list[list[str]] = []
    for row in rows:
        if row and row[0] == "" and merged:
            prev = merged[-1]
            for i, cell in enumerate(row):
                if i < len(prev) and cell:
                    prev[i] = (prev[i] + "\n" + cell).strip() if prev[i] else cell
        else:
            merged.append(list(row))
    return merged


def parse_markdown_tables(text: str) -> dict[str, list[dict[str, str]]]:
    """Extract every markdown table from an LLM response into structured row dicts.

    Returns a mapping of sheet_name → list of row dicts (column → value).
    Only sections that contain a pipe table are included; narrative-only sections
    are skipped silently.
    """
    # Find all heading positions
    headings: list[tuple[int, str]] = [
        (m.start(), m.group(1).strip()) for m in _SHEET_HEADING.finditer(text)
    ]

    if not headings:
        # No sheet headings — try parsing the whole text as one table
        rows = _extract_table_rows(text)
        if rows:
            return {"output": rows}
        return {}

    result: dict[str, list[dict[str, str]]] = {}

    for idx, (pos, sheet_name) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(text)
        section = text[pos:end]
        rows = _extract_table_rows(section)
        if rows:
            # Normalise sheet name: strip leading "Sheet N:" artefacts if any
            clean = re.sub(r"^(?:Sheet|Worksheet)\s*\d*\s*:?\s*", "", sheet_name, flags=re.IGNORECASE).strip()
            result[clean or sheet_name] = rows

    return result


def _rejoin_multiline_rows(lines: list[str]) -> list[str]:
    """Rejoin pipe-table rows that were split across multiple lines by embedded newlines.

    A row that starts with ``|`` but does not end with ``|`` is treated as the
    beginning of a multi-line cell; subsequent lines are appended (space-separated)
    until a line that ends with ``|`` is encountered, completing the row.
    """
    result: list[str] = []
    pending: str | None = None

    for line in lines:
        stripped = line.strip()
        if pending is not None:
            pending = pending + " " + stripped
            if stripped.endswith("|"):
                result.append(pending)
                pending = None
        elif stripped.startswith("|") and not stripped.endswith("|"):
            pending = stripped
        else:
            result.append(stripped)

    if pending is not None:
        result.append(pending)

    return result


def _extract_table_rows(section: str) -> list[dict[str, str]]:
    """Parse the first complete pipe table found in *section*.

    Returns a list of row dicts, or an empty list if no valid table is found.
    """
    lines = _rejoin_multiline_rows(section.splitlines())
    table_lines: list[str] = []
    in_table = False

    for line in lines:
        if _TABLE_ROW.match(line.strip()):
            in_table = True
            table_lines.append(line.strip())
        elif in_table:
            # Stop at the first non-table line after the table started
            break

    if len(table_lines) < 2:  # need at least header + separator
        return []

    # First row = headers, second row = separator (skip), rest = data
    headers = _parse_row(table_lines[0])
    data_rows = [_parse_row(r) for r in table_lines[2:] if not _SEPARATOR_ROW.match(r)]
    data_rows = _merge_continuation_rows(data_rows)

    rows: list[dict[str, str]] = []
    for raw in data_rows:
        # Pad or trim to match header length
        padded = raw + [""] * max(0, len(headers) - len(raw))
        row = {h: padded[i] for i, h in enumerate(headers) if h}
        # Skip entirely empty rows
        if any(v for v in row.values()):
            rows.append(row)

    return rows
