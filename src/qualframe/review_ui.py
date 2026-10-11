"""One-proposal-at-a-time review, backed by saved review actions."""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from qualframe.config import resolve_repo_path
from qualframe.evidence_review import load_run_records, latest_evidence_action_by_record, blocking_review_issues, is_researcher_addition
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import EvidenceSpan, CodeAssignment
from qualframe.ui_kit import provider_display

e = html.escape
_SPEAKER = re.compile(r"(?m)^([A-Z][A-Za-z .'-]{0,40}:)(?=\s)")
_DECISION_WORDS = {"accept": "Accepted", "edit": "Changed", "reject": "Rejected", "defer": "Later", "unreviewed": "To do",
                   "added": "Added by you", "removed": "Removed"}


def _mark_speakers(escaped: str) -> str:
    """Style speaker labels without changing the text the browser reports for selections."""
    return _SPEAKER.sub(r'<span class="speaker">\1</span>', escaped)


def _segment(source: str, left: int, right: int) -> str:
    """Escape a slice of the transcript, styling speaker labels only where a line really starts."""
    text = source[left:right]
    if left == 0 or source[left - 1] == "\n":
        return _mark_speakers(e(text))
    head, newline, tail = text.partition("\n")
    return e(head) + (newline + _mark_speakers(e(tail)) if newline else "")


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
    records = load_run_records(index, app.review_dir / run_id)
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
        # The text kept with the passage (its context) is shaded around the highlight.
        before = span.context_start_offset if span.context_start_offset is not None else start
        after = span.context_end_offset if span.context_end_offset is not None else end
        before, after = min(before, start), max(after, end)
        context = (f'<span class="kept-context" title="Saved with this code">{_segment(source, before, start)}' if before < start
                   else '<span class="kept-context">')
        source_html = (_segment(source, 0, before) + context + '<mark id="current-span">' + e(source[start:end])
                       + '</mark>' + _segment(source, end, after) + '</span>' + _segment(source, after, len(source)))
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
    proposals = [r for r in records if not is_researcher_addition(r)]
    resolved = sum(1 for r in proposals if r.record_id in actions and actions[r.record_id].decision != 'defer')
    added_count = len(records) - len(proposals)
    is_added = is_researcher_addition(record)
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
    if record.anchoring_method == 'normalized_quote_candidate' and not needs_edit:
        warning += ('<p class="review-guidance">The model\'s quotation differs from the transcript only in punctuation or spacing. '
                    'The highlighted passage is the transcript\'s own text.</p>')
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
        if is_researcher_addition(r):
            decision = 'removed' if decision == 'reject' else 'added'
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
    accept_label = 'Accept: no evidence' if record.record_kind == 'absence' else 'Accept'
    position_label = (f'Your addition {position - len(proposals) + 1} of {added_count}' if is_added
                      else f'Proposal {position + 1} of {len(proposals)}')
    who_hidden = f'<input type="hidden" name="reviewer" value="{e(reviewer)}">' if reviewer else ''
    if is_added:
        origin_note = (f'<p class="origin-note">Added by {e(action.reviewer if action else "a researcher")} during review'
                       + (f': {e(record.proposed_rationale)}' if record.proposed_rationale else '.') + '</p>')
        decision_buttons = ('<div class="decision-buttons"><button name="decision" formnovalidate value="reject" class="secondary" id="reject-button">'
                            'Remove this code <kbd>R</kbd></button></div>')
    else:
        origin_note = (f'<details{" open" if model_reason else ""}><summary>Why the model proposed this</summary>'
                       f'<p>{e(model_reason) or "No reason given."}</p></details>')
        decision_buttons = (f'<div class="decision-buttons"><button name="decision" formnovalidate value="accept" id="accept-button"{accept_disabled}>{accept_label} <kbd>A</kbd></button>\n'
                            '<button name="decision" formnovalidate value="reject" class="secondary" id="reject-button">Reject <kbd>R</kbd></button>\n'
                            '<button name="decision" formnovalidate value="defer" class="secondary" id="defer-button">Later <kbd>L</kbd></button></div>')
    script = (Path(__file__).parent / 'static/review.js').read_text(encoding='utf-8')
    body = f'''{notices}{done}
<div class="review-top"><div class="record-navigation">{prev_link}<strong>{position_label}</strong>{next_link}</div>
<div class="review-meter"><label for="review-progress">{resolved} of {len(proposals)} decided{f", {added_count} added" if added_count else ""}</label><progress id="review-progress" value="{resolved}" max="{len(proposals)}"></progress></div></div>
<div class="review-grid">
<nav class="proposal-rail" aria-label="All proposals"><h2>Proposals</h2>
<label>Search<input type="search" id="queue-search" placeholder="Code or transcript"></label>
<label>Show<select id="queue-filter"><option value="all">All</option><option value="unreviewed">To do</option><option value="defer">Later</option><option value="accept">Accepted</option><option value="edit">Changed</option><option value="reject">Rejected</option><option value="added">Added by you</option></select></label>
<ul id="proposal-list">{"".join(queue)}</ul></nav>
<div class="transcript-col"><div class="sheet">
<div class="sheet-head"><span>{e(Path(record.source_path).name)}</span><span>{e(Path(record.source_path).parent.name)}</span></div>
<pre id="review-source" class="sheet-text" tabindex="0">{source_html}</pre>
<div class="select-hint"><button type="button" id="use-selection" class="secondary">Use selected passage</button><span id="selection-feedback" role="status">To change the passage, select text in the transcript, then press <kbd>U</kbd>.</span></div>
</div></div>
<div class="decision-panel"><section>
<p class="code-path">{e(parents) if parents else ("Added code" if is_added else "Proposed code")}</p><h2>{e(code_label)}</h2><p>{e(definition)}</p>{guidance}{warning}
{origin_note}
<form id="decision-form" method="post" action="/evidence-action"><input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="item" value="{e(record.record_id)}"><input type="hidden" name="advance" value="yes"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}">
{who}
<input type="hidden" name="seconds_on_item" id="seconds-on-item" value="">
{decision_buttons}
<details id="edit-controls"{" open" if needs_edit else ""}><summary>Change code or passage <kbd>C</kbd></summary>
<label>Code<select name="edited_code_id" id="code-select">{_code_options(codes, code_id)}</select></label>
<p class="muted">To change the passage, select it in the transcript and press <strong>Use selected passage</strong>.</p>
<details><summary>Type character positions instead</summary><div class="grid"><label>Start<input name="edited_start" type="number" min="0" value="{start}"></label><label>End<input name="edited_end" type="number" min="1" value="{end}"></label></div></details>
<button name="decision" value="edit" id="save-edit">Save change and continue</button></details>
<details class="note-field"><summary>Add a note</summary><label>Note<textarea name="rationale" rows="2" placeholder="Optional. Saved with this decision."></textarea></label></details>
</form>
<p class="shortcut-help"><kbd>A</kbd> accept, <kbd>R</kbd> reject, <kbd>L</kbd> later, <kbd>C</kbd> change, <kbd>N</kbd> add a missed code, <kbd>J</kbd>/<kbd>K</kbd> next and previous</p>
</section>
<section class="add-code"><details id="add-controls"><summary>Add a code the model missed <kbd>N</kbd></summary>
<form id="add-form" method="post" action="/evidence-add"><input type="hidden" name="run_id" value="{e(run_id)}"><input type="hidden" name="item" value="{e(record.record_id)}"><input type="hidden" name="study_identity" value="{e(app.runner.project.project_id)}"><input type="hidden" name="source_path" value="{e(record.source_path)}">{who_hidden}
<input type="hidden" name="added_start" value=""><input type="hidden" name="added_end" value="">
<p class="muted" id="add-feedback">Select a passage in this transcript, then choose its code.</p>
<blockquote id="add-preview" hidden></blockquote>
<label>Code<select name="added_code_id" id="add-code-select" required><option value="">Choose a code</option>{_code_options(codes, "")}</select></label>
<label>Note<textarea name="rationale" rows="2" placeholder="Optional. Why this passage fits the code."></textarea></label>
<button id="add-button">Add code</button></form></details></section>
<section><h2>Codebook</h2><label>Search<input type="search" id="book-search" placeholder="Find a code or definition"></label><div class="codebook-panel">{codebook}</div></section>
<details class="review-details"><summary>Record details</summary>{history}<dl><dt>{"Origin" if is_added else "Model"}</dt><dd>{"Added by a researcher during review" if is_added else e(provider_display(record.provider, record.model))}</dd><dt>Located by</dt><dd>{e(record.anchoring_method.replace("_", " "))}</dd><dt>Source file hash</dt><dd><code>{e(record.source_sha256)}</code></dd><dt>Run</dt><dd>{e(run_id)}</dd></dl></details>
</div></div><script>{script}</script>'''
    return app._render_workspace_page(title='Review', intro='', body=body, active='evidence', wide=True)
