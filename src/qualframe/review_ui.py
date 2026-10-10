"""One-proposal-at-a-time review, backed by saved review actions."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from qualframe.config import resolve_repo_path
from qualframe.evidence_review import load_evidence_review_records, latest_evidence_action_by_record, blocking_review_issues
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import EvidenceSpan, CodeAssignment
from qualframe.ui_kit import provider_display

e = html.escape
_SPEAKER = re.compile(r"(?m)^([A-Z][A-Za-z .'-]{0,40}:)(?=\s)")
_DECISION_WORDS = {"accept": "Accepted", "edit": "Changed", "reject": "Rejected", "defer": "Later", "unreviewed": "To do"}


def _mark_speakers(escaped: str) -> str:
    """Style speaker labels without changing the text the browser reports for selections."""
    return _SPEAKER.sub(r'<span class="speaker">\1</span>', escaped)


def _code_path(codes: list[dict], code_id: str) -> list[dict]:
    by_id = {c["id"]: c for c in codes}
    path, seen = [], set()
    current = by_id.get(code_id)
    while current is not None and current["id"] not in seen:
        seen.add(current["id"])
        path.insert(0, current)
        current = by_id.get(current.get("parent_id") or "")
    return path


def _code_options(codes: list[dict], selected: str) -> str:
    ids = {c["id"] for c in codes}
    children: dict[str | None, list[dict]] = {}
    for code in codes:
        parent = code.get("parent_id") if code.get("parent_id") in ids else None
        children.setdefault(parent, []).append(code)
    out = []

    def add(items: list[dict], depth: int) -> None:
        for code in items:
            pad = " " * depth
            out.append(f'<option value="{e(code["id"])}"{" selected" if code["id"] == selected else ""}>{pad}{e(code["label"])}</option>')
            add(children.get(code["id"], []), depth + 1)

    add(children.get(None, []), 0)
    return "".join(out)


def render_review(app, *, run_id: str, item_id: str = '', message: str = '', error: str = '') -> str:
    app._managed_project_path()
    app._selected_run = run_id
    root = app._run_root(app.artifacts_dir, run_id)
    index = root / 'evidence_review/index.json'
    if not index.exists():
        raise FileNotFoundError('This run has no proposals prepared for review yet. Open the run details to prepare them.')
    payload = json.loads(index.read_text(encoding='utf-8'))
    records = load_evidence_review_records(index)
    actions = latest_evidence_action_by_record(app.review_dir / run_id)
    if not records:
        return app._render_workspace_page(
            title='Review', intro='This run returned no coding proposals.',
            body='<section><p>The model did not propose any codes for these transcripts. Check the run details, or try another model.</p></section>',
            active='evidence')
    pending = [r for r in records if r.record_id not in actions or actions[r.record_id].decision == 'defer']
    record = next((r for r in records if r.record_id == item_id), (pending or records)[0])
    position = records.index(record)
    action = actions.get(record.record_id)
    span, assignment = record.evidence_span, record.assignment
    if action and action.derived_artifact_path:
        derived = json.loads((root / action.derived_artifact_path).read_text(encoding='utf-8'))
        span, assignment = EvidenceSpan.model_validate(derived['evidence_span']), CodeAssignment.model_validate(derived['assignment'])
    source = transcript_to_text(resolve_repo_path(app.repo_root, record.source_path))
    start, end = (span.start_offset, span.end_offset) if span else (-1, -1)
    if span:
        source_html = (_mark_speakers(e(source[:start])) + '<mark id="current-span">' + e(source[start:end])
                       + '</mark>' + _mark_speakers(e(source[end:])))
    else:
        source_html = _mark_speakers(e(source))
    codes = payload.get('codebook', {}).get('codes') or ([c.model_dump() for c in app.runner.codebook.codes] if app.runner.codebook else [])
    code_id = assignment.code_id if assignment else record.proposed_code_id or ''
    path = _code_path(codes, code_id)
    chosen = path[-1] if path else {}
    code_label = chosen.get('label', record.code_label or 'Unknown code')
    definition = chosen.get('definition', record.code_definition or '')
    parents = ' / '.join(c['label'] for c in path[:-1])
    guidance = ''
    if chosen.get('inclusion_guidance'):
        guidance += f'<p class="guidance"><strong>Include:</strong> {e(chosen["inclusion_guidance"])}</p>'
    if chosen.get('exclusion_guidance'):
        guidance += f'<p class="guidance"><strong>Exclude:</strong> {e(chosen["exclusion_guidance"])}</p>'
    resolved = len(records) - len(pending)
    reviewer = app.researcher
    if not reviewer:
        profile = app.review_dir / 'reviewer.json'
        reviewer = json.loads(profile.read_text(encoding='utf-8')).get('name', '') if profile.exists() else ''
    issues = blocking_review_issues(record, source)
    needs_edit = bool(issues) and not (action and action.decision == 'edit')
    accept_disabled = ' disabled' if needs_edit or (not span and record.record_kind != 'absence') else ''
    warning = ''
    if needs_edit:
        warning = ('<div class="review-guidance"><strong>Needs your help locating the passage.</strong><ul>'
                   + ''.join(f'<li>{e(issue)}</li>' for issue in issues)
                   + '</ul><p>Select the right passage in the transcript, then use <em>Change code or passage</em>, or reject the proposal.</p></div>')
    if record.record_kind == 'absence':
        warning += '<p class="review-guidance">The model proposes that there is no evidence for this code. Check the transcript before accepting.</p>'
    if reviewer:
        who = (f'<input type="hidden" name="reviewer" value="{e(reviewer)}">'
               f'<p class="reviewer-line">Recording decisions as {e(reviewer)}. <a href="/home#name-form">Change</a></p>')
    else:
        who = ''
    url = lambda r: '/evidence?' + urlencode({'run_id': run_id, 'item': r.record_id})
    prev_link = f'<a id="prev-link" href="{e(url(records[position-1]))}">Previous</a>' if position else '<span class="muted">Previous</span>'
    next_link = f'<a id="next-link" href="{e(url(records[position+1]))}">Next</a>' if position + 1 < len(records) else '<span class="muted">Next</span>'
    queue = []
    for i, r in enumerate(records):
        decision = actions[r.record_id].decision if r.record_id in actions else 'unreviewed'
        current = ' aria-current="true"' if r.record_id == record.record_id else ''
        queue.append(
            f'<li data-status="{e(decision)}"><a href="{e(url(r))}"{current}>{i+1}. {e(r.code_label or "Unknown code")}'
            f'<br><span class="status {e(decision)}">{_DECISION_WORDS.get(decision, decision)}</span> '
            f'<span class="muted">{e(Path(r.source_path).stem)}</span></a></li>')
    history = (f'<p>Last decision: <strong>{e(_DECISION_WORDS.get(action.decision, action.decision))}</strong> by {e(action.reviewer)}. {e(action.rationale)}</p>'
               if action else '<p>No decision yet.</p>')
    done = ''
    if not pending:
        links = ''.join(app._file_link(p, p.name) + ' ' for p in sorted((app.exports_dir / run_id).glob('reviewed_evidence_package.*')))
        done = (f'<div class="next-up"><div><h2>Every proposal has a decision</h2><p>Export the reviewed coding, or explore it by code and transcript. '
                f'You can still revisit any decision. {links}</p></div><div class="actions">'
                f'<form method="post" action="/export-evidence"><input type="hidden" name="run_id" value="{e(run_id)}"><button class="secondary">Export to Excel</button></form>'
                f'<a class="button" href="/analysis?{e(urlencode({"run_id": run_id}))}">See results</a></div></div>')
    notices = (f'<div role="status" class="message">{e(message)}</div>' if message and not message.startswith('Recorded evidence decision') else '') \
        + (f'<div role="alert" class="error">{e(error)}</div>' if error else '')
    model_reason = record.proposed_rationale or (record.assignment.rationale if record.assignment else '') or ''
    codebook = ''.join(
        f'<details class="code-entry"><summary>{e(c["label"])}</summary><p>{e(c.get("definition", ""))}</p></details>' for c in codes)
    script = (Path(__file__).parent / 'static/review.js').read_text(encoding='utf-8')
    accept_label = 'Accept: no evidence' if record.record_kind == 'absence' else 'Accept'
    body = f'''{notices}{done}
<div class="review-top"><div class="record-navigation">{prev_link}<strong>Proposal {position+1} of {len(records)}</strong>{next_link}</div>
<div class="review-meter"><label for="review-progress">{resolved} of {len(records)} decided</label><progress id="review-progress" value="{resolved}" max="{len(records)}"></progress></div></div>
<div class="review-grid">
<nav class="proposal-rail" aria-label="All proposals"><h2>Proposals</h2>
<label>Search<input type="search" id="queue-search" placeholder="Code or transcript"></label>
<label>Show<select id="queue-filter"><option value="all">All</option><option value="unreviewed">To do</option><option value="defer">Later</option><option value="accept">Accepted</option><option value="edit">Changed</option><option value="reject">Rejected</option></select></label>
<ul id="proposal-list">{"".join(queue)}</ul></nav>
<div class="transcript-col"><div class="sheet">
<div class="sheet-head"><span>{e(Path(record.source_path).name)}</span><span>{e(Path(record.source_path).parent.name)}</span></div>
<pre id="review-source" class="sheet-text" tabindex="0">{source_html}</pre>
<div class="select-hint"><button type="button" id="use-selection" class="secondary">Use selected passage</button><span id="selection-feedback" role="status">To change the passage, select text in the transcript, then press <kbd>U</kbd>.</span></div>
</div></div>
<div class="decision-panel"><section>
<p class="code-path">{e(parents) if parents else "Proposed code"}</p><h2>{e(code_label)}</h2><p>{e(definition)}</p>{guidance}{warning}
<details{" open" if model_reason else ""}><summary>Why the model proposed this</summary><p>{e(model_reason) or "No reason given."}</p></details>
<form id="decision-form" method="post" action="/evidence-action"><input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="item" value="{e(record.record_id)}"><input type="hidden" name="advance" value="yes"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">
{who}
<div class="decision-buttons"><button name="decision" formnovalidate value="accept" id="accept-button"{accept_disabled}>{accept_label} <kbd>A</kbd></button>
<button name="decision" formnovalidate value="reject" class="secondary" id="reject-button">Reject <kbd>R</kbd></button>
<button name="decision" formnovalidate value="defer" class="secondary" id="defer-button">Later <kbd>L</kbd></button></div>
<details id="edit-controls"{" open" if needs_edit else ""}><summary>Change code or passage <kbd>C</kbd></summary>
<label>Code<select name="edited_code_id" id="code-select">{_code_options(codes, code_id)}</select></label>
<p class="muted">To change the passage, select it in the transcript and press <strong>Use selected passage</strong>.</p>
<details><summary>Type character positions instead</summary><div class="grid"><label>Start<input name="edited_start" type="number" min="0" value="{start}"></label><label>End<input name="edited_end" type="number" min="1" value="{end}"></label></div></details>
<button name="decision" value="edit" id="save-edit">Save change and continue</button></details>
<details class="note-field"><summary>Add a note</summary><label>Note<textarea name="rationale" rows="2" placeholder="Optional. Saved with this decision."></textarea></label></details>
</form>
<p class="shortcut-help"><kbd>A</kbd> accept, <kbd>R</kbd> reject, <kbd>L</kbd> later, <kbd>C</kbd> change, <kbd>J</kbd>/<kbd>K</kbd> next and previous</p>
</section>
<section><h2>Codebook</h2><label>Search<input type="search" id="book-search" placeholder="Find a code or definition"></label><div class="codebook-panel">{codebook}</div></section>
<details class="review-details"><summary>Record details</summary>{history}<dl><dt>Model</dt><dd>{e(provider_display(record.provider, record.model))}</dd><dt>Located by</dt><dd>{e(record.anchoring_method.replace("_", " "))}</dd><dt>Source file hash</dt><dd><code>{e(record.source_sha256)}</code></dd><dt>Run</dt><dd>{e(run_id)}</dd></dl></details>
</div></div><script>{script}</script>'''
    return app._render_workspace_page(title='Review', intro='', body=body, active='evidence', wide=True)
