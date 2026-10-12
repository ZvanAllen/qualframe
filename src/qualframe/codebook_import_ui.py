# ruff: noqa: E501
"""Server-rendered workbook mapping and review views."""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from qualframe.codebook_excel import FIELDS, REQUIRED, columns, read_excel
from qualframe.excel_import_workflow import ExcelImportWorkflow


def hidden(values: dict[str, str]) -> str:
    return "".join(
        f'<input type="hidden" name="{escape(k)}" value="{escape(v, quote=True)}">'
        for k, v in values.items()
    )


def mapping_view(workflow: ExcelImportWorkflow, options: dict[str, str]) -> str:
    token = options.get("token", "")
    content, metadata = workflow.load(token)
    sheets = read_excel(content)
    sheet = next((s for s in sheets if s.name == options.get("sheet")), sheets[0])
    header_row = int(options.get("header_row", "1"))
    available = columns(sheet, header_row)
    sheet_options = "".join(
        f'<option value="{escape(s.name)}"{" selected" if s.name == sheet.name else ""}>{escape(s.name)}</option>'
        for s in sheets
    )
    controls = []
    for field, label in FIELDS.items():
        alias = {
            "id": ["id", "code id", "code number", "code no", "code no."],
            "label": ["label", "code", "name", "code label", "code name", "construct", "category", "theme"],
            "definition": ["definition", "description", "code definition", "meaning"],
            "parent_id": ["parent id", "parent code id", "parent", "parent code", "domain id"],
            "active": ["active"],
            "examples": ["examples", "example", "example quotes", "anchor examples"],
            "inclusion_guidance": ["inclusion", "include when", "include", "inclusion criteria", "when to use"],
            "exclusion_guidance": ["exclusion", "exclude when", "exclude", "exclusion criteria", "when not to use"],
        }[field]
        selected = next(
            (
                col
                for col, text in zip(available, sheet.rows[header_row - 1], strict=True)
                if text.casefold().replace("_", " ") in alias
            ),
            "",
        )
        selected = options.get(field, selected)
        choices = '<option value="">Choose a column</option>' + "".join(
            f'<option value="{col}"{" selected" if col == selected else ""}>{escape(label_text)}</option>'
            for col, label_text in available.items()
        )
        controls.append(
            f'<label>{label}{" *" if field in REQUIRED else ""}<select name="{field}"{" required" if field in REQUIRED else ""}>{choices}</select></label>'
        )
    header = "".join(f"<th>{escape(label)}</th>" for label in available.values())
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(value[:200])}</td>" for value in row) + "</tr>"
        for row in sheet.rows[header_row : header_row + 5]
    )
    return f'''<section><h2>1. Choose the table</h2><p>{escape(metadata["filename"])}. Your active codebook has not changed.</p>
<form action="/codebook/excel" method="get" class="grid">{hidden({"token": token})}
<label>Worksheet<select name="sheet">{sheet_options}</select></label>
<label>Header row<input name="header_row" type="number" min="1" max="100" value="{header_row}" required></label>
<button>Show selected table</button></form>
<p>First five data rows. Preview cells are limited to 200 characters; full values are preserved on import. Store IDs as text in Excel to preserve leading zeros.</p>
<div style="overflow-x:auto"><table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table></div></section>
<section><h2>2. Map your columns</h2><p>Required fields are marked *. Each code needs a stable ID, label, and definition. Use parent IDs for a hierarchy; leave that mapping blank for a flat codebook. Examples use one entry per line. Active accepts yes/no, true/false, or 1/0; leave the cell or mapping blank to make codes active. Inactive codes can group child codes in a hierarchy but are excluded from model coding options.</p>
<form method="post" action="/codebook/preview" class="grid">
{hidden({"token": token, "sheet": sheet.name, "header_row": str(header_row)})}
<label>Codebook name<input name="name" value="{escape(metadata["filename"].rsplit(".", 1)[0])}" required></label>
<label>Codebook ID<input name="codebook_id" value="imported-codebook" required></label>
<label>Version<input name="version" value="1.0.0" required></label>
{"".join(controls)}<button>Validate and preview codes</button></form></section>'''


def confirmation_view(workflow: ExcelImportWorkflow, options: dict[str, str]) -> str:
    codebook, _, _ = workflow.convert(options.get("token", ""), options)
    rows = "".join(
        f"<tr><td>{escape(c.id)}</td><td>{escape(c.label)}</td><td>{escape(c.parent_id or '—')}</td><td>{escape(c.definition)}</td><td>{'Yes' if c.active else 'No'}</td></tr>"
        for c in codebook.codes[:50]
    )
    active_count = sum(c.active for c in codebook.codes)
    back = "/codebook/excel?" + urlencode({k: options[k] for k in ("token", "sheet", "header_row")})
    return f'''<section><h2>3. Confirm codebook import</h2><p><strong>{escape(codebook.name)}</strong>: {len(codebook.codes)} validated codes. {active_count} active; {len(codebook.codes) - active_count} inactive. Showing up to 50 codes. All codes were checked.</p>
<div style="overflow-x:auto"><table><thead><tr><th>ID</th><th>Code</th><th>Parent ID</th><th>Definition</th><th>Active</th></tr></thead><tbody>{rows}</tbody></table></div>
<p>Import creates a new active codebook version and preserves the original workbook, column mapping, and previous versions. Completed runs are unchanged.</p>
<form action="/codebook/commit" method="post">{hidden(options)}<button>Import this codebook version</button></form>
<p><a href="{escape(back)}">Back to column mapping</a></p></section>'''
