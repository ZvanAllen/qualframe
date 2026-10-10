import json
import pytest
from test_evidence_review import _completed_synthetic_run
from qualframe.evidence_review import write_evidence_review_index, load_evidence_review_records, append_evidence_review_action
from qualframe.reviewed_analysis import freeze_reviewed_snapshot, load_snapshot, snapshot_freshness, evidence_matrix
from qualframe.dashboard import DashboardApp
from qualframe.pipeline.project_runner import ProjectRunner
from qualframe.analysis_ui import render_analysis


def prepared(tmp_path):
    project, run_id, root, review = _completed_synthetic_run(tmp_path)
    index = write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    records = load_evidence_review_records(index)
    return project, run_id, root, review, records


def decide(project, root, review, record, decision='accept', **kwargs):
    return append_evidence_review_action(record=record, source_path=project.parents[2]/record.source_path,
        review_dir=review, artifact_root=root, reviewer='Researcher', rationale='Synthetic test', decision=decision, **kwargs)


def test_freeze_requires_full_review_and_preserves_edits_rejections(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    with pytest.raises(ValueError, match='Complete coding and review'):
        freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher')
    for record in records:
        decide(project, root, review, record)
    decide(project, root, review, records[0], 'reject')
    original = records[1]
    decide(project, root, review, original, 'edit', edited_start=0, edited_end=5,
        edited_code_id=original.assignment.code_id)
    target = freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher', dry_run=True)
    assert not target.exists()
    path = freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher')
    saved = path.read_bytes()
    assert freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher') == path
    assert path.read_bytes() == saved
    snapshot = load_snapshot(path)
    assert len(snapshot['payload']['evidence']) == 3
    assert len(snapshot['payload']['rejected']) == 1
    item = next(e for e in snapshot['payload']['evidence'] if e['record_id'] == original.record_id)
    assert item['span']['start_offset'] == 0 and item['span']['end_offset'] == 5
    assert item['derived_sha256']
    assert snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    assert sum(map(len, evidence_matrix(snapshot['payload']).values())) == 3
    app = DashboardApp(ProjectRunner(project))
    page = render_analysis(app, run_id)
    assert 'Codes by transcript' in page and 'Current snapshot' in page
    detail = render_analysis(app, run_id, snapshot['snapshot_id'], item['code_id'], item['source_path'].replace('\\','/'))
    assert 'id="passages"' in detail and 'Open in review' in detail
    decide(project, root, review, records[2], 'defer')
    assert not snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    assert path.read_bytes() == saved
    assert 'changes detected' in render_analysis(app, run_id)


def test_snapshot_detects_changed_source_artifact_and_snapshot(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    for record in records:
        decide(project, root, review, record)
    path = freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher')
    snapshot = load_snapshot(path)
    artifact = root / records[0].artifact_path
    original = artifact.read_bytes()
    artifact.write_bytes(original + b' ')
    assert not snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    artifact.write_bytes(original)
    source = project.parents[2]/records[0].source_path
    source.write_text('Changed fixture', encoding='utf-8')
    assert not snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    snapshot['payload']['evidence'] = []
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(ValueError, match='Snapshot content has changed'):
        load_snapshot(path)


def test_snapshot_action_rejects_wrong_study_and_matrix_keeps_sources_separate(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    app = DashboardApp(ProjectRunner(project))
    with pytest.raises(ValueError, match='another study'):
        app.handle_action('/analysis/freeze', {'run_id':[run_id], 'reviewer':['Researcher'], 'study_identity':['other']})
    for record in records:
        decide(project, root, review, record)
    app.handle_action('/analysis/freeze', {'run_id':[run_id], 'reviewer':['Researcher'], 'study_identity':[app.runner.project.project_id], 'source':[records[0].source_path, records[-1].source_path]})
    snapshot = load_snapshot(next((root/'analysis').glob('snapshot-*.json')))
    assert len({source for code,source in evidence_matrix(snapshot['payload'])}) == 2

def test_absence_decisions_are_separate_from_evidence(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    index = root/'evidence_review/index.json'
    payload = json.loads(index.read_text(encoding='utf-8'))
    changed = records[0].model_copy(update={'record_kind':'absence', 'evidence_span':None,
        'assignment':None, 'proposed_code_id':records[0].assignment.code_id,
        'proposed_exact_text':'No relevant quote found', 'anchoring_method':'no_evidence'})
    # Modify only the disposable fixture before any adjudication.
    key = next(k for k,v in payload.items() if isinstance(v,list) and v and isinstance(v[0],dict) and 'record_id' in v[0])
    payload[key][0] = changed.model_dump(mode='json')
    index.write_text(json.dumps(payload), encoding='utf-8')
    records[0] = changed
    for record in records:
        decide(project, root, review, record)
    snap = load_snapshot(freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher'))
    assert len(snap['payload']['absences']) == 1
    assert len(snap['payload']['evidence']) == 3
    assert 'span' not in snap['payload']['absences'][0]

def test_subset_freezes_only_reviewed_sources_and_ignores_other_review_changes(tmp_path):
    project, run_id, root, review, records = prepared(tmp_path)
    selected = records[0].source_path
    for record in records:
        if record.source_path == selected:
            decide(project, root, review, record)
    path = freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher', selected_sources=[selected])
    snapshot = load_snapshot(path)
    assert len(snapshot['payload']['source_paths']) == 1
    assert len(snapshot['payload']['excluded_source_paths']) == 1
    other = next(r for r in records if r.source_path != selected)
    decide(project, root, review, other)
    assert snapshot_freshness(snapshot, project.parents[2], root, review)[0]
    with pytest.raises(ValueError, match='Select at least one'):
        freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher', selected_sources=[])
    with pytest.raises(ValueError, match='Complete coding and review'):
        freeze_reviewed_snapshot(project.parents[2], root, review, 'Researcher', selected_sources=[other.source_path])
