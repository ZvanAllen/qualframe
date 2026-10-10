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
        if rows or strict_empty_tables(text):
            return {"output": rows}
        return {}

    result: dict[str, list[dict[str, str]]] = {}

    for idx, (pos, sheet_name) in enumerate(headings):
        end = headings[idx + 1][0] if idx + 1 < len(headings) else len(text)
        section = text[pos:end]
        rows = _extract_table_rows(section)
        if rows or strict_empty_tables(section):
            # Normalise sheet name: strip leading "Sheet N:" artefacts if any
            clean = re.sub(
                r"^(?:Sheet|Worksheet)\s*\d*\s*:?\s*", "", sheet_name, flags=re.IGNORECASE
            ).strip()
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


def strict_empty_tables(text: str) -> list[dict[str, object]]:
    """Recognize explicit header-only tables, never arbitrary missing output.

    Every nonblank line must be a heading, code fence, or one of exactly two
    table lines. A malformed separator, empty data row, prose, missing header,
    truncated row, or populated table makes this conservative recognizer fail.
    Headers are retained so callers can validate a frozen output contract.
    """
    tables: list[dict[str, object]] = []
    lines = text.splitlines()
    heading = "output"
    fence_open = False
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line in {"```", "```markdown", "```md"}:
            if fence_open and line != "```":
                return []
            fence_open = not fence_open
            continue
        match = _SHEET_HEADING.fullmatch(line)
        if match:
            heading = re.sub(
                r"^(?:Sheet|Worksheet)\s*\d*\s*:?\s*", "", match.group(1), flags=re.IGNORECASE
            ).strip()
            continue
        if not _TABLE_ROW.fullmatch(line) or i >= len(lines):
            return []
        headers = _parse_row(line)
        separator = lines[i].strip()
        i += 1
        if not _SEPARATOR_ROW.fullmatch(separator):
            return []
        dividers = _parse_row(separator)
        if (
            not headers
            or any(not h for h in headers)
            or len(headers) != len(set(headers))
            or len(dividers) != len(headers)
            or any(re.fullmatch(r":?-{3,}:?", d) is None for d in dividers)
        ):
            return []
        tables.append({"sheet": heading, "headers": headers})
    return [] if fence_open else tables


# --- JSON coding output (directed coding prompt v3) -------------------------------

_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
CODING_COLUMNS = ("Meaning Unit ID", "Evidence Start", "Evidence End", "Exact Evidence", "Code ID", "Rationale")


def _json_candidate(text: str) -> str | None:
    stripped = text.strip()
    fenced = _JSON_FENCE.match(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    if stripped.startswith("{"):
        return stripped
    start, end = stripped.find("{"), stripped.rfind("}")
    if start >= 0 and end > start and '"codings"' in stripped[start:end]:
        return stripped[start:end + 1]
    return None


def parse_coding_json(text: str) -> dict[str, list[dict[str, str]]] | None:
    """Convert a ``{"codings": [...]}`` response into the coding table the review uses.

    Returns None when the text is not a codings object, so callers can fall back to
    markdown tables. Quotations keep their exact characters: the review step reverses
    the ``&`` escaping applied here and then searches the transcript for the quotation.
    """
    import json

    candidate = _json_candidate(text)
    if candidate is None:
        return None
    try:
        payload = json.loads(candidate)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("codings"), list):
        return None
    rows: list[dict[str, str]] = []
    for index, item in enumerate(payload["codings"], start=1):
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", ""))
        rows.append({
            "Meaning Unit ID": str(item.get("meaning_unit") or f"mu-{index}").strip(),
            "Evidence Start": "auto",
            "Evidence End": "auto",
            "Exact Evidence": quote.replace("&", "&amp;"),
            "Code ID": str(item.get("code_id", "")).strip(),
            "Rationale": str(item.get("rationale", "")).strip(),
        })
    return {"Directed Coding": rows}


def parse_model_output(text: str) -> dict[str, list[dict[str, str]]]:
    """Parse JSON coding output when present, otherwise markdown tables."""
    parsed = parse_coding_json(text)
    return parsed if parsed is not None else parse_markdown_tables(text)


def coding_response_schema(code_ids: list[str]) -> dict:
    """Strict JSON schema for coding responses; code IDs are limited to the active codebook."""
    code_field: dict = {"type": "string"}
    if code_ids:
        code_field["enum"] = sorted(set(code_ids))
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["meaning_unit", "quote", "code_id", "rationale"],
        "properties": {
            "meaning_unit": {"type": "string"},
            "quote": {"type": "string"},
            "code_id": code_field,
            "rationale": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["codings"],
        "properties": {"codings": {"type": "array", "items": item}},
    }
