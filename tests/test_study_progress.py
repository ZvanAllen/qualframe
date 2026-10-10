import json
from qualframe.study_progress import transcript_progress
from qualframe.evidence_review import write_evidence_review_index, load_evidence_review_records, append_evidence_review_action
from test_evidence_review import _completed_synthetic_run


def test_progress_counts_latest_actions_and_keeps_empty_outputs_unreviewed(tmp_path):
    project, run_id, root, review = _completed_synthetic_run(tmp_path)
    index = write_evidence_review_index(project_manifest_path=project, run_id=run_id)
    rows = transcript_progress(root, review, [], project.parents[2])
    assert len(rows) == 2
    assert all(r['completed'] and not r['reviewed'] for r in rows)
    assert sum(r['remaining'] for r in rows) == 4
    records = load_evidence_review_records(index)
    for decision in ['defer', 'accept']:
        append_evidence_review_action(record=records[0], source_path=project.parents[2]/records[0].source_path,
            review_dir=review, artifact_root=root, decision=decision, reviewer='Test', rationale='Test')
    rows = transcript_progress(root, review, [], project.parents[2])
    assert sum(r['remaining'] for r in rows) == 3
    assert sum(r['counts'].get('defer', 0) for r in rows) == 0
    payload = json.loads(index.read_text(encoding='utf-8'))
    # Preserve coding artifacts while simulating a prepared index with no records.
    from pathlib import Path
    empty_root = tmp_path/'empty'; empty_root.mkdir()
    import shutil
    shutil.copytree(root, empty_root/'run')
    (empty_root/'run/evidence_review/index.json').unlink()
    rows = transcript_progress(empty_root/'run', empty_root/'reviews', [], project.parents[2])
    assert all(r['completed'] and not r['reviewed'] for r in rows)


def test_progress_requires_all_domains_and_separates_run_scope(tmp_path):
    root = tmp_path/'run'; root.mkdir()
    source = {'path':'inputs/a.txt', 'kind':'transcript', 'sha256':'hash'}
    plan = {'discovered_inputs':[source], 'planned_stage_runs':[
        {'stage_id':'coding','input_path':'inputs/a.txt','domain':d} for d in ['A','B']]}
    (root/'run_plan.json').write_text(json.dumps(plan))
    (root/'run_manifest.json').write_text(json.dumps({'artifact_paths':['a.json']}))
    artifact = {'stage_id':'coding','input_path':'inputs/a.txt','input_sha256':'hash','parsed_output':{'A':[]}}
    (root/'a.json').write_text(json.dumps(artifact))
    other = {'path':'inputs/b.txt','kind':'transcript','sha256':'other'}
    rows = transcript_progress(root, tmp_path/'review', [source,other])
    assert not rows[0]['completed']
    assert rows[1]['coding'] == 'Outside selected run'
    artifact['parsed_output']['B'] = []
    (root/'a.json').write_text(json.dumps(artifact))
    rows = transcript_progress(root, tmp_path/'review', [source,other])
    # Empty dictionary entries alone do not prove that a response parsed.
    assert not rows[0]['completed'] and not rows[0]['reviewed']
