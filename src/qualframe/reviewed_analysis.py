"""Immutable, source-validated reviewed inputs for downstream analysis."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from qualframe.directed_analysis import validate_evidence_span_against_source
from qualframe.evidence_review import load_evidence_review_records, latest_evidence_action_by_record, blocking_review_issues
from qualframe.io.files import sha256_for_file, sha256_for_text
from qualframe.io.transcript_io import transcript_to_text
from qualframe.models import EvidenceSpan, CodeAssignment
from qualframe.study_progress import transcript_progress
from qualframe.empty_output_review import load_empty_output_actions


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _within(root: Path, relative: str) -> Path:
    path = (root / relative.replace('\\', '/')).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Analysis input path leaves its study boundary.')
    return path


def reviewed_snapshot_payload(repo_root: Path, run_root: Path, review_root: Path, selected_sources: list[str] | None = None) -> dict:
    """Build without writing or provider calls; also used to detect stale snapshots."""
    index = run_root / 'evidence_review/index.json'
    if not index.exists():
        raise ValueError('Prepare evidence review before freezing analysis inputs.')
    progress = transcript_progress(run_root, review_root, [], repo_root)
    all_sources = [row['path'] for row in progress]
    if selected_sources is not None:
        chosen = {p.replace('\\','/') for p in selected_sources}
        if not chosen or not chosen <= set(all_sources):
            raise ValueError('Select at least one transcript from the frozen run cohort.')
        progress = [row for row in progress if row['path'] in chosen]
    if not progress or any(not row['reviewed'] for row in progress):
        raise ValueError('Complete coding and review for the selected transcripts before freezing. Confirm any validated empty outputs separately.')
    manifest = _json(run_root / 'run_manifest.json')
    catalog = _json(index).get('codebook', {})
    codes = {code['id']: code for code in catalog.get('codes', [])}
    records = load_evidence_review_records(index)
    actions = latest_evidence_action_by_record(review_root)
    evidence, absences, rejected, lineage = [], [], [], []
    checked_sources, checked_artifacts, source_hashes = {}, {}, {}
    for record in records:
        if record.source_path.replace('\\','/') not in {row['path'] for row in progress}:
            continue
        action = actions.get(record.record_id)
        if not action or action.decision == 'defer':
            raise ValueError('All proposals must be resolved before freezing.')
        if action.record_sha256 != sha256_for_text(record.model_dump_json()):
            raise ValueError('A reviewed proposal changed after its decision.')
        source = _within(repo_root, record.source_path)
        if record.source_path not in checked_sources:
            source_hashes[record.source_path] = sha256_for_file(source)
            if source_hashes[record.source_path] != record.source_sha256:
                raise ValueError('A source changed after coding; restore the original or rerun it.')
            checked_sources[record.source_path] = transcript_to_text(source)
        if source_hashes[record.source_path] != record.source_sha256:
            raise ValueError('Conflicting source hashes in review records.')
        artifact = _within(run_root, record.artifact_path)
        if record.artifact_path not in checked_artifacts:
            checked_artifacts[record.artifact_path] = sha256_for_file(artifact)
        if checked_artifacts[record.artifact_path] != record.artifact_sha256:
            raise ValueError('A model artifact changed after review preparation.')
        text = checked_sources[record.source_path]
        lineage.append(action.model_dump(mode='json'))
        base = dict(record_id=record.record_id, action_id=action.action_id,
            source_path=record.source_path, source_sha256=record.source_sha256,
            artifact_path=record.artifact_path, artifact_sha256=record.artifact_sha256,
            prompt_sha256=record.prompt_sha256, provider=record.provider, model=record.model)
        if action.decision == 'reject':
            rejected.append(base)
            continue
        span, assignment = record.evidence_span, record.assignment
        derived_hash = None
        if action.derived_artifact_path:
            derived_path = _within(run_root, action.derived_artifact_path)
            derived = _json(derived_path)
            if derived.get('record_id') != record.record_id or derived.get('record_sha256') != action.record_sha256:
                raise ValueError('Edited evidence does not match its reviewed proposal.')
            span = EvidenceSpan.model_validate(derived['evidence_span'])
            assignment = CodeAssignment.model_validate(derived['assignment'])
            derived_hash = sha256_for_file(derived_path)
        elif blocking_review_issues(record, text):
            raise ValueError('An accepted proposal still has unresolved validation issues.')
        code_id = assignment.code_id if assignment else record.proposed_code_id
        if code_id not in codes:
            raise ValueError('A reviewed code is absent from the frozen codebook.')
        base.update(code_id=code_id, code_label=codes[code_id]['label'], derived_sha256=derived_hash)
        if record.record_kind == 'absence' and not action.derived_artifact_path:
            absences.append(base)
            continue
        if span is None or assignment is None:
            raise ValueError('Accepted evidence needs a source span and code assignment.')
        validate_evidence_span_against_source(span, text)
        if assignment.evidence_span_id != span.id:
            raise ValueError('Code assignment does not refer to its reviewed span.')
        base.update(span=span.model_dump(mode='json'), assignment=assignment.model_dump(mode='json'))
        evidence.append(base)
    payload = dict(kind='qualframe_reviewed_snapshot_v1', project_id=manifest['project_id'],
        run_id=manifest['run_id'], configuration_fingerprint=manifest.get('configuration_fingerprint'),
        index_sha256=sha256_for_file(index), codebook=catalog,
        source_paths=[row['path'] for row in progress],
        evidence=evidence, absences=absences, rejected=rejected, review_actions=lineage)
    empty_rows = [row for row in progress if row.get('empty_state') == 'confirm_empty']
    if empty_rows:
        payload['empty_output_decisions'] = [row['empty_action'] for row in empty_rows]
        included_empty = {row['path'] for row in empty_rows}
        payload['empty_output_history'] = [action for action in load_empty_output_actions(review_root)
                                           if action['source_path'] in included_empty]
    if selected_sources is not None:
        payload['excluded_source_paths'] = sorted(set(all_sources) - set(payload['source_paths']))
    return payload


def snapshot_identity(payload: dict) -> str:
    return sha256_for_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def freeze_reviewed_snapshot(repo_root: Path, run_root: Path, review_root: Path, reviewer: str, *, dry_run: bool = False, selected_sources: list[str] | None = None) -> Path:
    if not reviewer.strip():
        raise ValueError('Enter the researcher name for this snapshot.')
    payload = reviewed_snapshot_payload(repo_root, run_root, review_root, selected_sources)
    identity = snapshot_identity(payload)
    path = run_root / 'analysis' / f'snapshot-{identity}.json'
    if dry_run:
        return path
    if path.exists():
        load_snapshot(path)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = dict(snapshot_id=identity, created_at_utc=datetime.now(timezone.utc).isoformat(),
        created_by=reviewer.strip(), payload=payload)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(envelope, handle, ensure_ascii=False, indent=2)
    return path


def load_snapshot(path: Path) -> dict:
    snapshot = _json(path)
    if snapshot.get('snapshot_id') != snapshot_identity(snapshot['payload']):
        raise ValueError('Snapshot content has changed; it cannot be used for analysis.')
    return snapshot


def snapshot_freshness(snapshot: dict, repo_root: Path, run_root: Path, review_root: Path) -> tuple[bool, str]:
    try:
        current = reviewed_snapshot_payload(repo_root, run_root, review_root, snapshot['payload']['source_paths'] if 'excluded_source_paths' in snapshot['payload'] else None)
    except (ValueError, OSError) as exc:
        return False, str(exc)
    if snapshot_identity(current) != snapshot['snapshot_id']:
        return False, 'Review decisions or analysis inputs changed after this snapshot.'
    return True, 'Matches the current reviewed evidence.'


def evidence_matrix(payload: dict) -> dict[tuple[str, str], list[dict]]:
    """Cells contain retained proposals; UI reports distinct source spans per code."""
    cells: dict[tuple[str, str], list[dict]] = {}
    for item in payload['evidence']:
        source = item['source_path'].replace('\\', '/')
        cells.setdefault((item['code_id'], source), []).append(item)
    return cells
