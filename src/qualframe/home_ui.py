"""The application home: open the demo, start a study, or reopen one."""
from __future__ import annotations

from qualframe.app_workspace import list_study_manifests, researcher_name
from qualframe.config import load_project_manifest
from qualframe.ui_kit import e, friendly_time, notices, plural

# A few lines from the bundled demo interview, marked up the way the review screen marks evidence.
_HERO = (
    '<div class="sheet hero-sheet" aria-hidden="true">'
    '<div class="tagrow" style="top:30px">Consent and comfort</div>'
    '<div class="tagrow" style="top:124px">Patient experience of care</div>'
    '<div class="tagrow" style="top:218px">Leadership and decision-making</div>'
    '<pre class="sheet-text"><span class="speaker">Participant:</span> <span class="hl">The first time, I didn\'t really '
    'understand what I was agreeing to.</span> She said something like, "Is it okay if I use a tool that helps me '
    'write my notes?"\n\n<span class="speaker">Participant:</span> <span class="hl hl-2">She looked at me the whole '
    'time. I felt like she was really hearing me, instead of half-listening while she typed.</span>\n\n'
    '<span class="speaker">Participant:</span> Not formally, which is the strange part. <span class="hl hl-4">We meet '
    'every two months, and nobody brought it to us before it started.</span></pre></div>'
)


def render_home(app, message: str = "", error: str = "") -> str:
    manifests = list_study_manifests(app.repo_root)
    rows = []
    for path in manifests:
        try:
            project = load_project_manifest(path)
        except (ValueError, OSError):
            continue
        transcripts = path.parent / "data/raw/transcripts"
        count = sum(1 for p in transcripts.rglob("*") if p.suffix.lower() in {".txt", ".docx"}) if transcripts.exists() else 0
        current = app.runner is not None and path.resolve() == app.runner.project_manifest_path
        details = [plural(count, "transcript")]
        if project.created_at_utc:
            details.append(f"created {friendly_time(project.created_at_utc)}")
        if project.data_classification == "synthetic":
            details.append("synthetic data")
        action = (
            '<a class="button secondary" href="/">Continue</a>' if current else
            f'<form method="post" action="/study/open"><input type="hidden" name="study_id" value="{e(path.parent.name)}">'
            '<button class="secondary">Open</button></form>'
        )
        rows.append(
            f'<li><div><form method="post" action="/study/open" class="inline-link"><input type="hidden" name="study_id" value="{e(path.parent.name)}">'
            f'<button class="study-link quiet" type="submit">{e(project.title or project.project_id)}</button></form>'
            f'<small>{e(", ".join(details))}</small></div>{action}</li>'
        )
    studies = (
        f'<ul class="study-list">{"".join(rows)}</ul>' if rows else
        '<div class="study-list empty">No studies yet. Open the demo to look around, or start your own.</div>'
    )
    name = researcher_name(app.repo_root)
    who = (
        f'<p class="muted">Decisions are recorded as <strong>{e(name)}</strong>. '
        '<a href="#name-form" onclick="document.getElementById(\'name-form\').hidden=false">Change name</a></p>'
        if name else '<p class="muted">Add your name so it can be recorded with your coding decisions.</p>'
    )
    name_form = (
        f'<form id="name-form" method="post" action="/settings/name" class="inline name-form"{" hidden" if name else ""}>'
        f'<label>Your name<input name="researcher_name" value="{e(name)}" required autocomplete="name"></label>'
        '<button class="secondary">Save name</button></form>'
    )
    body = f'''<div class="home">{notices(message, error)}
<section class="plain home-hero"><div>
<h1>AI-assisted coding you can check</h1>
<p>QualFrame applies your codebook to interview transcripts with a language model, then shows every proposed code beside the exact passage so you can accept, change, or reject it.</p>
<p>Your studies stay on this computer, with a record of what the model proposed and what you decided.</p>
<div class="actions"><form method="post" action="/demo"><button class="big">Open the demo study</button></form>
<a class="button secondary big" href="/setup">Start a new study</a></div>
</div>{_HERO}</section>
<section class="plain"><div class="section-head"><h2>Your studies</h2></div>{studies}
<div class="home-foot">{who}{name_form}<p class="muted">Studies are saved in <code>{e(str(app.repo_root / "studies"))}</code></p></div></section>
</div>'''
    return app._render_workspace_page(title="", intro="", body=body, active="home", page_title="QualFrame")
