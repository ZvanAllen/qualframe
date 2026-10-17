from copy import deepcopy
from types import SimpleNamespace

import pytest

from qualframe.qualbench import build_qualbench, passage_agreement, write_qualbench
from qualframe.qualbench_ui import _report_html
from test_qualbench import _set


def _reference(alternatives, *, code='c', source='t/one.txt'):
    reference=_set('reference',[],kind='reference')
    reference['statement']='Synthetic reference fixture.'
    reference['included']=[dict(record_id='r1',source=source,code_id=code,quote='repeated text',
        match='repeated',anchoring_method='exact_repeated',
        alternative_spans=[dict(start=a,end=b,exact_text='x'*(b-a)) for a,b in alternatives])]
    return reference


def test_second_alternative_matches_once_and_is_excluded_from_text_overlap():
    model=_set('model',[('t/one.txt','c',20,30)])
    reference=_reference([(0,10),(20,30)])
    before=deepcopy(reference)
    report=build_qualbench([model],reference=reference)
    row=next(r for r in report['passages'] if r['scope_kind']=='all')
    assert (row['left_passages'],row['right_passages'],row['matched_exact'],row['f1_exact'])==(1,1,1,1)
    assert row['coded_text_jaccard']==0
    assert (row['left_coded_text_passages_excluded'],row['right_coded_text_passages_excluded'],row['coded_text_passages_excluded'])==(0,1,1)
    assert row['right_text_also_coded_by_left'] is None
    profile=report['coding_sets'][-1]
    assert profile['coded_passages']==1 and profile['codes_present']==1
    assert (profile['reference_passages_unique'],profile['reference_passages_repeated'],profile['reference_passages_unanchored'])==(0,1,0)
    assert profile['median_passage_words'] is None and profile['passages_coded_more_than_once']==0
    assert reference==before


def test_two_model_occurrences_cannot_match_one_reference_twice():
    model=_set('model',[('t/one.txt','c',0,10),('t/one.txt','c',20,30)])
    row=passage_agreement(model,_reference([(0,10),(20,30)]),versus_reference=True)
    assert row['matched_exact']==1 and row['right_passages']==1
    assert row['f1_exact']==pytest.approx(2/3)


def test_alternative_edges_use_augmenting_paths_not_greedy_matching():
    model=_set('model',[('t/one.txt','c',0,10),('t/one.txt','c',20,30)])
    reference=_reference([(0,10),(20,30)])
    reference['included'] += _set('unique',[('t/one.txt','c',0,10)])['included']
    row=passage_agreement(model,reference,versus_reference=True)
    assert row['matched_exact']==2 and row['f1_exact']==1
    assert row['coded_text_jaccard']==pytest.approx(1/2)


@pytest.mark.parametrize('span,quarter,half,three_quarters', [((20,40),1,1,0),((20,60),1,0,0),((21,60),0,0,0)])
def test_alternatives_respect_inclusive_iou_thresholds(span,quarter,half,three_quarters):
    model=_set('model',[('t/one.txt','c',*span)])
    row=passage_agreement(model,_reference([(0,10),(20,30)]),versus_reference=True)
    assert (row['matched_iou_quarter'],row['matched_iou_half'],row['matched_iou_three_quarters'])==(quarter,half,three_quarters)
    assert row['matched_any_overlap']==1


@pytest.mark.parametrize('source,code', [('t/two.txt','c'),('t/one.txt','q')])
def test_alternatives_never_match_other_source_or_code(source,code):
    model=_set('model',[(source,code,20,30)])
    row=passage_agreement(model,_reference([(0,10),(20,30)]),versus_reference=True)
    assert row['matched_any_overlap']==0


def test_text_overlap_omits_alternatives_from_either_side_and_can_be_undefined():
    left,right=_reference([(0,10),(20,30)]),_reference([(20,30),(40,50)])
    left['set_id']='left'
    row=passage_agreement(left,right,versus_reference=False)
    assert row['matched_exact']==1 and row['f1_exact']==1
    assert row['coded_text_jaccard'] is None and row['coded_text_passages_excluded']==2


def test_mixed_reference_profile_and_saved_report_show_location_counts(tmp_path):
    model=_set('model',[('t/one.txt','c',20,30),('t/two.txt','p',1,5)])
    reference=_reference([(0,10),(20,30)])
    reference['included'] += _set('unique',[('t/two.txt','p',1,5)])['included']
    reference['excluded'] += _set('old',[],excluded=[('t/one.txt','q'),('t/one.txt','unknown')])['excluded']
    reference['presence_only']=[dict(source='t/two.txt',code_id='q')]
    reference['absences']=[dict(source='t/one.txt',code_id='p')]
    report=build_qualbench([model],reference=reference)
    profile=report['coding_sets'][-1]
    assert (profile['reference_passages_unique'],profile['reference_passages_repeated'],profile['reference_passages_unanchored'])==(1,1,1)
    assert profile['unknown_codes']==1 and profile['codes_without_quotation']==1 and profile['no_evidence_rows']==1
    assert profile['coded_passages']==3 and profile['passages_located']==2
    by_source={r['transcript']:r for r in report['passages']
               if r['scope_kind']=='transcript' and r['scope']=='all pairs'}
    assert by_source['one.txt']['right_coded_text_passages_excluded']==1
    assert by_source['two.txt']['right_coded_text_passages_excluded']==0
    folder=write_qualbench(report,tmp_path/'report')
    assert 'reference_passages_repeated' in (folder/'coding_sets.csv').read_text()
    assert 'coded_text_passages_excluded' in (folder/'passages.csv').read_text()
    readme=(folder/'README.md').read_text(encoding='utf-8')
    assert 'it is still one passage' in readme and 'Earlier saved references remain readable' in readme
    page=_report_html(SimpleNamespace(_file_link=lambda path,label:label),folder)
    assert 'Reference quotation locations' in page and 'Repeated quotation' in page
    assert 'Excluded from text overlap, left / right' in page


def test_legacy_unanchored_reference_stays_unanchored_without_reimport():
    model=_set('model',[('t/one.txt','c',0,10)])
    reference=_set('reference',[],excluded=[('t/one.txt','c')],kind='reference')
    reference['excluded'][0]['issues']=['Quotation not found once in the transcript']
    report=build_qualbench([model],reference=reference)
    assert report['coding_sets'][-1]['reference_passages_unanchored']==1
    assert report['coding_sets'][-1]['reference_passages_repeated']==0
    assert report['passages'][0]['right_passages']==0
    assert report['presence'][0]['both']==1


def test_alternatives_survive_content_rekeying_and_common_cohort_restriction():
    model=_set('model',[('t/one.txt','c',20,30)])
    reference=_reference([(0,10),(20,30)],source='other/one.txt')
    reference['sources']={'other/one.txt':'h1','other/extra.txt':'extra'}
    reference['included'].append(dict(reference['included'][0],record_id='omitted',source='other/extra.txt'))
    report=build_qualbench([model],reference=reference)
    assert report['transcripts']==['t/one.txt']
    assert report['passages'][0]['matched_exact']==1 and report['passages'][0]['right_passages']==1
    assert report['coding_sets'][-1]['reference_passages_repeated']==1
