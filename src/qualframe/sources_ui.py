"""Sources (transcripts and participant information) and the codebook pages."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from qualframe.app_workspace import researcher_name
from qualframe.config import resolve_repo_path
from qualframe.io.transcript_io import transcript_to_text
from qualframe.ui_kit import e, friendly_time, identity_fields, notices, plural

_HIGHLIGHTS = 6

_UPLOAD_SCRIPT = """<script>(()=>{
const zone=document.getElementById('dropzone');if(!zone)return;
const form=zone.closest('form'),input=zone.querySelector('input[type=file]'),list=document.getElementById('upload-list');
function pick(files){const dt=new DataTransfer();for(const f of files)dt.items.add(f);input.files=dt.files;show();}
function show(){list.innerHTML='';for(const f of input.files){const li=document.createElement('li');li.textContent=f.name;list.appendChild(li);}
 document.getElementById('upload-button').textContent=input.files.length>1?`Add ${input.files.length} transcripts`:'Add transcript';}
['dragenter','dragover'].forEach(t=>zone.addEventListener(t,ev=>{ev.preventDefault();zone.classList.add('dragging');}));
['dragleave','drop'].forEach(t=>zone.addEventListener(t,ev=>{ev.preventDefault();zone.classList.remove('dragging');}));
zone.addEventListener('drop',ev=>pick(ev.dataTransfer.files));input.addEventListener('change',show);
form.addEventListener('submit',async ev=>{if(!window.fetch||input.files.length<2)return;ev.preventDefault();
 const items=[...list.children];let ok=0,errors=[];
 for(const [i,f] of [...input.files].entries()){const data=new FormData(form);data.delete('upload');data.append('upload',f);
  items[i].textContent=f.name+' — adding…';
  const r=await fetch(form.action,{method:'POST',body:data,headers:{'X-Requested-With':'fetch'}});
  const t=await r.text();if(r.ok&&!t.startsWith('ERROR')){ok++;items[i].textContent=f.name+' — added';}else{errors.push(f.name+': '+t.replace('ERROR ',''));items[i].textContent=f.name+' — not added';}}
 const q=new URLSearchParams();if(ok)q.set('message',`Added ${ok} transcript${ok==1?'':'s'}.`);if(errors.length)q.set('error',errors.join(' '));
 location.href='/imports?'+q.toString();});
const search=document.getElementById('source-search');if(search)search.addEventListener('input',ev=>{for(const row of document.querySelectorAll('.source-row'))row.hidden=!row.textContent.toLowerCase().includes(ev.target.value.toLowerCase());});
})();</script>"""


def _metadata_summary(app) -> str:
    path = app.runner.project.metadata_file
    if not path:
        return '<p class="muted">No participant information yet.</p>'
    try:
        text = resolve_repo_path(app.repo_root, path).read_text(encoding="utf-8")
    except OSError:
        return '<p class="error">The participant information file could not be read.</p>'
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    fields = [f for f in (reader.fieldnames or []) if f != "source_filename"]
    return (f'<p>{plural(len(rows), "transcript")} described by '
            f'{", ".join(e(f) for f in fields) or "no fields"}. Use these fields to group results.</p>')


def render_sources(app, message: str = "", error: str = "") -> str:
    files = app.runner._transcript_files()
    records = {r.original_filename: r for r in app.study_workspace.source_records(app._managed_project_path())
               if r.source_kind == "transcript"} if app.runner else {}
    rows = []
    for source in files:
        text = transcript_to_text(source)
        record = records.get(source.name)
        added = friendly_time(record.imported_at_utc) if record else ""
        group = source.parent.name
        rows.append(
            f'<tr class="source-row"><td><details><summary>{e(source.name)}</summary>'
            f'<pre class="source-preview">{e(text)}</pre></details></td>'
            f'<td>{e(group if group != "transcripts" else "")}</td><td>{len(text.split()):,}</td><td>{e(added)}</td></tr>'
        )
    search = ('<label class="table-search">Find a transcript<input type="search" id="source-search"></label>'
              if len(files) > 8 else "")
    listing = (
        f'{search}<div class="progress-table"><table><thead><tr><th>Transcript</th><th>Group</th><th>Words</th><th>Added</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        if rows else '<p class="muted">No transcripts yet. Add Word (.docx) or plain-text (.txt) files below.</p>'
    )
    name = researcher_name(app.repo_root)
    body = f'''{notices(message, error)}
<section><div class="section-head"><h2>Transcripts</h2><span class="muted">{plural(len(files), "transcript")}</span></div>{listing}</section>
<section><h2>Add transcripts</h2>
<form method="post" action="/import/transcript" enctype="multipart/form-data">
<label class="dropzone" id="dropzone"><strong>Drop transcripts here, or choose files</strong>
<span class="muted">Word (.docx) or plain text (.txt), up to 25 MB each. Originals are copied and never changed.</span>
<input type="file" name="upload" accept=".txt,.docx" multiple required></label>
<ul id="upload-list" class="upload-list"></ul>
<div class="grid"><label>Site or group <small>Optional. Used to compare results between groups.</small><input name="group_label" maxlength="80" placeholder="For example: Clinic A"></label></div>
{identity_fields(name, note_label="Add a note about these files")}
<div class="actions"><button id="upload-button">Add transcript</button></div></form></section>
<section><h2>Participant information <span class="muted">(optional)</span></h2>{_metadata_summary(app)}
<details><summary>Import a spreadsheet of participant information</summary>
<p>Use a UTF-8 CSV file with one row per transcript and a <code>source_filename</code> column matching each transcript's file name. Other columns, such as site or role, become groups you can compare.</p>
<form method="post" action="/import/metadata" enctype="multipart/form-data"><label>CSV file<input type="file" name="upload" accept=".csv" required></label>
{identity_fields(name)}<button class="secondary">Import participant information</button></form></details></section>
{_UPLOAD_SCRIPT}'''
    return app._render_workspace_page(
        title="Sources", intro="The interview transcripts you will code.", body=body, active="imports")


def _code_tree(codes: list[dict]) -> str:
    children: dict[str | None, list[dict]] = {}
    for code in codes:
        children.setdefault(code.get("parent_id"), []).append(code)
    roots = [c for c in codes if not c.get("parent_id") or c.get("parent_id") not in {x["id"] for x in codes}]
    palette = {}
    for index, root in enumerate(roots):
        palette[root["id"]] = index % _HIGHLIGHTS + 1

    def branch(items: list[dict], color: int | None) -> str:
        out = []
        for code in items:
            swatch = palette.get(code["id"], color or 1)
            kids = children.get(code["id"], [])
            guidance = ""
            if code.get("inclusion_guidance"):
                guidance += f'<span class="code-def"><strong>Include:</strong> {e(code["inclusion_guidance"])}</span>'
            if code.get("exclusion_guidance"):
                guidance += f'<span class="code-def"><strong>Exclude:</strong> {e(code["exclusion_guidance"])}</span>'
            out.append(
                f'<li class="code-item"><span class="swatch hl hl-{swatch}"></span><span class="code-name">{e(code["label"])}</span> '
                f'<span class="muted code-id">{e(code["id"])}</span>'
                f'<span class="code-def">{e(code.get("definition", ""))}</span>{guidance}'
                f'{f"<ul>{branch(kids, swatch)}</ul>" if kids else ""}</li>'
            )
        return "".join(out)

    return f'<ul class="code-tree">{branch(roots, None)}</ul>'


def render_codebook(app, message: str = "", error: str = "") -> str:
    name = researcher_name(app.repo_root)
    cfir = any(stage.domain_iterations for stage in app.runner.pipeline.stages)
    codebook = app.runner.codebook
    if codebook is not None:
        codes = [c.model_dump() for c in codebook.codes]
        current = (
            f'<section><div class="section-head"><h2>{e(codebook.name)}</h2>'
            f'<span class="muted">Version {e(codebook.version)}, {plural(len(codes), "code")}</span></div>'
            '<label class="table-search">Find a code<input type="search" id="code-search" placeholder="Search names and definitions"></label>'
            f'{_code_tree(codes)}</section>'
        )
    elif cfir:
        from qualframe.cfir_review import reference_codes

        reference = resolve_repo_path(app.repo_root, app.runner.project.paths["reference"]) / "codebook.xlsx"
        codes = reference_codes(reference) if reference.exists() else []
        current = (
            f'<section><h2>CFIR reference workbook</h2><p>{plural(len(codes), "construct")} loaded.</p>'
            f'{_code_tree(codes) if codes else ""}</section>'
        )
    else:
        current = ('<section class="empty-state"><h2>No codebook yet</h2>'
                   '<p>Import the codes you want to apply. Most people start from an Excel sheet with a column each for the code name, '
                   'its definition, and (optionally) a parent code.</p>'
                   '<p><a href="/download/example-codebook.xlsx">Download an example codebook (Excel)</a></p></section>')
    if cfir:
        imports = f'''<section><h2>Import the CFIR reference workbook</h2><p>Use the two-column CFIR workbook with its domain sections. Earlier versions are kept.</p>
<form method="post" action="/import/cfir" enctype="multipart/form-data"><label>CFIR workbook<input type="file" name="upload" accept=".xlsx" required></label>
{identity_fields(name)}<button>Import workbook</button></form></section>'''
    else:
        verb = "Replace with a new version" if codebook is not None else "Import from Excel"
        imports = f'''<section><h2>{verb}</h2>
<p>Choose an Excel workbook. You'll pick the sheet, match its columns to code name, definition and parent code, and check the codes before anything changes. Earlier versions are kept, and runs already done keep the version they used.</p>
<form method="post" action="/import/excel" enctype="multipart/form-data"><label>Excel codebook (.xlsx)<input type="file" name="upload" accept=".xlsx" required></label>
{identity_fields(name)}<button{' class="secondary"' if codebook is not None else ''}>Continue to column matching</button></form>
<details><summary>Import a QualFrame codebook file (.yaml) instead</summary>
<form method="post" action="/import/codebook" enctype="multipart/form-data"><label>Codebook file<input type="file" name="upload" accept=".yaml,.yml" required></label>
{identity_fields(name)}<button class="secondary">Import codebook file</button></form></details></section>'''
    script = """<script>(()=>{const s=document.getElementById('code-search');if(!s)return;s.addEventListener('input',ev=>{const q=ev.target.value.toLowerCase();
for(const li of document.querySelectorAll('.code-item'))li.hidden=q&&!li.textContent.toLowerCase().includes(q);});})();</script>"""
    return app._render_workspace_page(
        title="Codebook", intro="The codes, definitions and guidance the model applies.",
        body=notices(message, error) + current + imports + script, active="codebook")
