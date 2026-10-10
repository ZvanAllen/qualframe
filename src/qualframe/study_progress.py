"""Read-only transcript progress for one explicitly selected run."""
from __future__ import annotations

from collections import Counter
import html
import json
from pathlib import Path
from urllib.parse import urlencode

from qualframe.evidence_review import load_evidence_review_records, latest_evidence_action_by_record
from qualframe.empty_output_review import empty_table_issue, empty_output_binding, latest_empty_output_action, _digest


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def _key(path: str) -> str:
    return path.replace('\\', '/')


def transcript_progress(run_root: Path, review_root: Path, current_inputs: list[dict], repo_root: Path | None = None) -> list[dict]:
    """Use frozen plan identities and successful artifacts, never proposal counts, for coding."""
    plan = _read(run_root / 'run_plan.json')
    manifest = _read(run_root / 'run_manifest.json')
    frozen = {_key(i['path']): i for i in plan.get('discovered_inputs', []) if i['kind'] == 'transcript'}
    current = {_key(i['path']): i for i in current_inputs if i['kind'] == 'transcript'}
    artifacts = [dict(_read(run_root / rel), artifact_rel=_key(rel)) for rel in manifest.get('artifact_paths', [])]
    index = run_root / 'evidence_review/index.json'
    records = load_evidence_review_records(index) if index.exists() else []
    actions = latest_evidence_action_by_record(review_root)
    rows = []
    for path in sorted(frozen.keys() | current.keys()):
        source = frozen.get(path, current.get(path))
        calls = [c for c in plan.get('planned_stage_runs', []) if _key(c.get('input_path', '')) == path]
        stage = calls[0]['stage_id'] if calls else None
        calls = [c for c in calls if c['stage_id'] == stage]
        hashes = {source['sha256']}
        if repo_root:
            from qualframe.io.files import sha256_for_file, sha256_for_text
            from qualframe.io.transcript_io import transcript_to_text
            file = repo_root / path
            if file.exists() and sha256_for_file(file) == source['sha256']:
                hashes.add(sha256_for_text(transcript_to_text(file)))
        outputs = [a for a in artifacts if a.get('stage_id') == stage and _key(a.get('input_path', '')) == path and a.get('input_sha256') in hashes]
        domains = {c['domain'] for c in calls if c.get('domain')}
        completed = bool(outputs) and all(a.get('parsed_output') is not None and a.get('structured_output_valid') is not False for a in outputs)
        if domains and not (len(calls) == 1 and plan.get('codebook_id')):
            completed = completed and all(
                any(any(d == c['domain'] or d.startswith(c['domain'] + ': ') for d in (a.get('parsed_output') or {})) or
                    _key(c.get('output_hint', '')).endswith('/' + a['artifact_rel'])
                    for a in outputs) for c in calls if c.get('domain'))
        elif len(calls) > 1:
            completed = completed and len(outputs) >= len(calls)
        empty_issue = empty_table_issue(repo_root, run_root, calls, outputs) if calls and outputs else ''
        if empty_issue:
            completed = False
        if not calls:
            coding = 'Outside selected run' if plan else 'Not started'
        elif completed:
            coding = 'Coding complete'
        elif outputs:
            coding = 'Incomplete / validation needed'
        else:
            coding = 'No completed coding artifact'
        own = [r for r in records if _key(r.source_path) == path and r.source_sha256 == source['sha256'] and r.stage_id == stage]
        counts = Counter(actions[r.record_id].decision if r.record_id in actions else 'unreviewed' for r in own)
        remaining = counts['unreviewed'] + counts['defer']
        reviewed = completed and bool(own) and remaining == 0
        empty_binding = None
        empty_eligible = False
        empty_action = latest_empty_output_action(review_root, path)
        empty_state = 'not_applicable'
        zero_rows = bool(outputs) and all(a.get('parsed_output') and not any(a['parsed_output'].values()) for a in outputs)
        if zero_rows and not own:
            empty_state = 'blocked'
            if completed and index.exists() and repo_root:
                try:
                    empty_binding = empty_output_binding(repo_root, run_root, source, stage, outputs)
                    empty_eligible = True
                    empty_state = 'pending'
                    if empty_action:
                        if empty_action.get('binding_sha256') == _digest(empty_binding) and _digest(empty_action.get('binding', {})) == _digest(empty_binding):
                            empty_state = empty_action['decision']
                            reviewed = empty_state == 'confirm_empty'
                        else:
                            empty_state = 'stale'
                except (ValueError, OSError, KeyError) as exc:
                    empty_issue = str(exc)
            elif not index.exists():
                empty_issue = empty_issue or 'Prepare the evidence index before confirming an empty output.'
        elif completed and not own:
            empty_issue = 'Coding rows exist but no review proposals were prepared; inspect validation and prepare review.'
        pending = next((r for r in own if r.record_id not in actions or actions[r.record_id].decision == 'defer'), None)
        rows.append(dict(path=path, coding=coding, completed=completed, reviewed=reviewed,
            total=len(own), remaining=remaining, counts=dict(counts), empty_eligible=empty_eligible,
            empty_binding=empty_binding, empty_state=empty_state, empty_action=empty_action, empty_issue=empty_issue, item=(pending or (own[0] if own else None)).record_id if own else None,
            changed=path in current and path in frozen and current[path]['sha256'] != frozen[path]['sha256']))
    return rows


def render_study_progress(app, run_id: str | None) -> str:
    e = html.escape
    current = [i.model_dump() for i in app.runner.build_run_plan().discovered_inputs]
    root = app.artifacts_dir / run_id if run_id else app.artifacts_dir / '__no_selected_run__'
    review = app.review_dir / run_id if run_id else app.review_dir / '__no_selected_run__'
    rows = transcript_progress(root, review, current, app.repo_root)
    counts = Counter()
    for row in rows:
        counts.update(row['counts'])
    completed = sum(r['completed'] for r in rows)
    reviewed = sum(r['reviewed'] for r in rows)
    total = sum(r['total'] for r in rows)
    remaining = sum(r['remaining'] for r in rows)
    table = ''
    for row in rows:
        state = f"{row['total'] - row['remaining']} / {row['total']} resolved" if row['total'] else ('Review not prepared / no proposals to confirm' if row['completed'] else 'Awaiting coding')
        if row['empty_state'] != 'not_applicable':
            state = {'confirm_empty':'Zero proposals reviewed and confirmed', 'pending':'Confirm zero-proposal output',
                     'needs_recoding':'Researcher requested new coding', 'defer':'Zero-proposal review deferred',
                     'stale':'Earlier empty-output decision is out of date', 'blocked':'Empty output needs validation'}.get(row['empty_state'], state)
        if row['changed']:
            state += ' · Source changed since this run'
        action = ''
        if row['item'] and run_id:
            url = '/evidence?' + urlencode({'run_id': run_id, 'item': row['item']})
            action = f'<a href="{e(url)}">{"Revisit review" if row["reviewed"] else "Resume review"}</a>'
        if row['empty_eligible'] and run_id:
            url = '/empty-output?' + urlencode({'run_id': run_id, 'source': row['path']})
            action = f'<a href="{e(url)}">{"Revisit empty-output review" if row["reviewed"] else "Review empty output"}</a>'
        table += f'<tr><td>{e(Path(row["path"]).name)}<small class="muted">{e(Path(row["path"]).parent.name)}</small></td><td>{e(row["coding"])}</td><td>{e(state)}</td><td>{action}</td></tr>'
    scope = f'Counts cover this run only.' if run_id else 'No run selected. Start with a coding plan.'
    return f'''<section class="study-progress"><h2>Transcripts in this run</h2><p class="muted">{scope}</p>
<div class="cards"><div class="card"><div class="label">Transcripts</div><div class="value">{len(rows)}</div></div><div class="card"><div class="label">Coded</div><div class="value">{completed}</div></div><div class="card"><div class="label">Fully reviewed</div><div class="value">{reviewed}</div></div><div class="card"><div class="label">Proposals left to decide</div><div class="value">{remaining}</div></div></div>
<label for="study-review-progress">{total - remaining} of {total} proposals decided: {counts['accept']} accepted, {counts['edit']} changed, {counts['reject']} rejected, {counts['defer']} later, {counts['unreviewed']} not yet seen</label><progress id="study-review-progress" max="{max(total, 1)}" value="{total - remaining}"></progress>
<div class="progress-table"><table><thead><tr><th>Transcript</th><th>Coding</th><th>Review</th><th></th></tr></thead><tbody>{table or '<tr><td colspan="4">Import a transcript to begin.</td></tr>'}</tbody></table></div></section>'''
