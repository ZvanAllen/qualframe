from copy import deepcopy
from types import SimpleNamespace

from qualframe.qualbench import build_qualbench, present_units, write_qualbench
from qualframe.qualbench_ui import _report_html
from test_qualbench import _set


def test_inactive_parents_are_not_presence_units_but_keep_child_projection(tmp_path):
    left = _set('left', [('t/one.txt', 'c', 0, 4), ('t/two.txt', 'p', 0, 4)])
    right = _set('right', [('t/one.txt', 'c', 0, 4)])
    for coding in (left, right):
        coding['codebook']['codes'][0]['active'] = False
    report = build_qualbench([left, right], stability_groups=[['left', 'right']])
    assert report['codes'] == 2 and report['codebook_codes'] == 3 and report['inactive_codes'] == 1
    assert report['code_universes'] == {'code': 2, 'parent code': 2}
    assert set(present_units(left)) == {('t/one.txt', 'c')}
    pooled = {r['level']: r for r in report['presence'] if r['scope_kind'] == 'all'}
    assert pooled['code']['n_units'] == pooled['parent code']['n_units'] == 4
    assert pooled['parent code']['both'] == 1 and pooled['parent code']['left_only'] == 0
    assert len(report['units']) == 8 and {u['code_id'] for u in report['units']} == {'c','q'}
    assert next(u for u in report['units'] if u['code_id'] == 'c')['parent_code_id'] == 'p'
    assert all(s['n_codes'] == 2 and s['n_units'] == 4 for s in report['stability'])
    assert report['coding_sets'][0]['active_codes'] == 2 and report['coding_sets'][0]['inactive_codes'] == 1
    folder = write_qualbench(report, tmp_path/'report')
    readme = (folder/'README.md').read_text(encoding='utf-8')
    assert '2 active codes' in readme and 'parent code: 2 codes' in readme
    page = _report_html(SimpleNamespace(_file_link=lambda path,label: label), folder)
    assert 'Presence universes: 2 active codes; 2 parent codes' in page


def test_94_techniques_and_16_inactive_groups_have_separate_denominators():
    left,right = _set('left',[]),_set('right',[])
    codes = [dict(id=f'G{i}',label=f'Group {i}',active=False) for i in range(1,17)]
    codes += [dict(id=f'T{i}',label=f'Technique {i}',parent_id=f'G{(i-1)%16+1}',active=True) for i in range(1,95)]
    for coding in (left,right):
        coding['codebook']['codes'] = deepcopy(codes)
    report = build_qualbench([left,right],stability_groups=[['left','right']])
    assert report['codes'] == 94 and report['codebook_codes'] == 110
    assert report['code_universes'] == {'code':94,'parent code':16}
    assert [(r['n_codes'],r['n_units']) for r in report['presence'] if r['scope_kind']=='all'] == [(94,188),(16,32)]
    assert [r['n_units'] for r in report['stability']] == [188,32]
    assert len(report['units']) == 2*2*94


def test_inactive_hierarchy_chain_is_followed_and_orphans_are_not_a_universe():
    left,right=_set('left',[('t/one.txt','c',0,2)]),_set('right',[])
    for coding in (left,right):
        coding['codebook']['codes'] = [dict(id='root',label='Root',domain='Hierarchy',active=False),
            dict(id='p',label='Middle',parent_id='root',active=False),
            dict(id='c',label='Child',parent_id='p'),dict(id='orphan',label='Orphan',active=False)]
    report=build_qualbench([left,right])
    assert report['code_universes'] == {'code':1,'parent code':1}
    assert {u['parent_code_id'] for u in report['units']} == {'root'}
    parent_domain=next(r for r in report['presence'] if r['level']=='parent code' and r['scope_kind']=='domain')
    assert parent_domain['scope']=='Hierarchy' and parent_domain['left_only']==1


def test_missing_active_flag_matches_explicit_true_in_legacy_codebooks():
    left,right=_set('left',[]),_set('right',[])
    for c in right['codebook']['codes']:
        c['active']=True
    report=build_qualbench([left,right])
    assert not report['warnings'] and report['codes']==3


def test_active_flag_difference_warns_and_first_codebook_sets_universe():
    left,right=_set('left',[]),_set('right',[])
    left['codebook']['codes'][0]['active']=False
    report=build_qualbench([left,right])
    assert report['codebook_differences']==[dict(left='left',right='right',code_id='p',fields=['active'])]
    assert 'active-code universe' in report['warnings'][-1]
    assert report['codes']==2


def test_all_inactive_codebook_is_empty_not_perfect_agreement():
    left,right=_set('left',[]),_set('right',[])
    for coding in (left,right):
        for c in coding['codebook']['codes']:
            c['active']=False
    report=build_qualbench([left,right],stability_groups=[['left','right']])
    assert report['codes']==0 and report['units']==[] and report['code_universes']=={'code':0}
    assert report['presence'][0]['n_units']==0 and report['presence'][0]['percent_agreement'] is None
    assert report['stability'][0]['krippendorff_alpha'] is None


def test_differing_flags_use_same_baseline_mask_for_both_sides():
    left,right=_set('left',[('t/one.txt','c',0,2)]),_set('right',[('t/one.txt','c',0,2)])
    right['codebook']['codes'][1]['active']=False
    forward=build_qualbench([left,right],stability_groups=[['left','right']])
    reverse=build_qualbench([right,left],stability_groups=[['right','left']])
    assert forward['codes']==3 and reverse['codes']==2
    assert next(r for r in forward['presence'] if r['scope_kind']=='all' and r['level']=='code')['both']==1
    assert next(r for r in reverse['presence'] if r['scope_kind']=='all' and r['level']=='code')['both']==0
    assert {u['present'] for u in forward['units'] if u['code_id']=='c' and u['transcript']=='one.txt'}=={1}
    assert all(u['code_id']!='c' for u in reverse['units'])
    assert forward['stability'][0]['units_all_agree']==1
