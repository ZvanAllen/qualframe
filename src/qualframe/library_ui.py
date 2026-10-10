"""Local source and codebook previews using the current study inventory."""
from html import escape
from qualframe.io.transcript_io import transcript_to_text
from qualframe.config import resolve_repo_path
from qualframe.cfir_review import reference_codes


def library_view(app) -> str:
    files = app.runner._transcript_files()
    rows = []
    for source in files:
        rows.append(f'<details class="source-entry"><summary>{escape(source.name)} · {escape(source.parent.name)}</summary><pre class="source-preview">{escape(transcript_to_text(source))}</pre></details>')
    codes = [c.model_dump() for c in app.runner.codebook.codes] if app.runner.codebook else reference_codes(resolve_repo_path(app.repo_root, app.runner.project.paths['reference']) / 'codebook.xlsx')
    entries = ''.join(f'<details class="library-code"><summary>{escape(c["label"])}</summary><p>{escape(c.get("definition", ""))}</p></details>' for c in codes)
    version = app.runner.codebook.version if app.runner.codebook else 'CFIR reference workbook'
    cfir_form = '''<section><h2>Import CFIR reference workbook</h2><p>Use the two-column CFIR workbook with its domain sections. The original workbook is preserved in a new version.</p><form method="post" action="/import/cfir" enctype="multipart/form-data"><label>CFIR workbook<input type="file" name="upload" accept=".xlsx" required></label><label>Researcher name<input name="actor" required></label><label>Reason for import<input name="rationale" required></label><button>Import CFIR reference version</button></form></section>''' if any(s.domain_iterations for s in app.runner.pipeline.stages) else ''
    return f'''<section><h2>Source library</h2><p>{len(files)} transcripts available for coding. Expand a source to inspect the extracted text.</p><label>Find a source<input type="search" id="source-search"></label>{''.join(rows) or '<p>Import a transcript below to begin.</p>'}</section>
<section id="codebook-library"><h2>Active codebook</h2><p>{escape(version)} · {len(codes)} entries</p><label>Find a code or definition<input type="search" id="library-code-search"></label><div class="codebook-panel">{entries or '<p>Import a codebook below.</p>'}</div></section>{cfir_form}
<script>for(const [id,selector] of [['source-search','.source-entry'],['library-code-search','.library-code']])document.getElementById(id).addEventListener('input',event=>{{for(const row of document.querySelectorAll(selector))row.hidden=!row.textContent.toLowerCase().includes(event.target.value.toLowerCase())}});</script>'''
