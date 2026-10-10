from copy import deepcopy

import pytest

from qualframe.archival_quote_alignment import align_model_quotes_for_archive
from qualframe.archival_reference import ANCHOR_POLICY
from qualframe.io.files import sha256_for_text
from qualframe.reviewed_analysis import snapshot_identity


def fixture():
    text="A shared source - with support. Another statement."
    digest="a"*64
    original="data/example.txt"
    source="benchmark-source-"+snapshot_identity({"original_path":original,"sha256":digest})[:24]
    mapping={original:dict(source_id=source,original_path=original,sha256=digest,extracted_text_sha256=sha256_for_text(text))}
    def item(identifier,quote,**kwargs):
        return dict(record_id=identifier,source=source,code_id="c1",proposed_quotation=quote,**kwargs)
    p=dict(kind="qualframe_raw_comparison_input_v1",sources={source:digest},
        codebook={"codes":[{"id":"c1"}]},
        benchmark_provenance=dict(source_mapping=mapping,source_mapping_sha256=snapshot_identity(mapping)),
        included=[item("exact","Another statement.",start=31,end=len(text),exact_text=text[31:],
            anchoring_method="unique_exact_quote")],
        excluded=[item("dash","A shared source — with support.",anchoring_method="unresolved_exact_quote",
            issues=["Select the evidence in the transcript; the quotation is missing or ambiguous.","Missing source span"])],
        absences=[])
    return p,{source:text}


def test_symmetric_dash_policy_is_separate_and_keeps_original_exclusions():
    p,texts=fixture()
    before=deepcopy(p)
    out=align_model_quotes_for_archive(p,texts)
    assert p==before
    assert len(out["included"])==2 and out["excluded"]==[]
    assert out["benchmark_provenance"]["quote_anchoring_policy"]==ANCHOR_POLICY
    audit=out["benchmark_provenance"]["archival_quote_alignment"]
    assert audit["original_excluded"]==p["excluded"]
    assert audit["outcomes"]["recovered_quote_only_exclusion"]==1
    recovered=next(x for x in out["included"] if x["record_id"]=="dash")
    assert recovered["proposed_quotation"]=="A shared source — with support."
    assert recovered["exact_text"]=="A shared source - with support."


@pytest.mark.parametrize("change",["code","other_issue","case","word"])
def test_nonmechanical_or_other_validation_issues_never_get_promoted(change):
    p,texts=fixture()
    item=p["excluded"][0]
    if change=="code":item["code_id"]="unknown"
    if change=="other_issue":item["issues"].append("Wrong domain")
    if change=="case":item["proposed_quotation"]="a shared source — with support."
    if change=="word":item["proposed_quotation"]="A shared source — without support."
    out=align_model_quotes_for_archive(p,texts)
    assert len(out["included"])==1 and len(out["excluded"])==1


def test_included_model_quote_is_rechecked_instead_of_trusting_its_span():
    p,texts=fixture()
    p["included"][0]["proposed_quotation"]="Invented words."
    out=align_model_quotes_for_archive(p,texts)
    assert next(x for x in out["excluded"] if x["record_id"]=="exact")["issues"]


def test_source_drift_and_reapplication_fail():
    p,texts=fixture()
    with pytest.raises(ValueError,match="hash differs"):
        align_model_quotes_for_archive(p,{key:value+" changed" for key,value in texts.items()})
    aligned=align_model_quotes_for_archive(p,texts)
    with pytest.raises(ValueError,match="once"):
        align_model_quotes_for_archive(aligned,texts)


def test_ambiguous_matching_is_excluded():
    p,texts=fixture()
    source=next(iter(texts))
    texts[source]+=" A shared source - with support."
    entry=next(iter(p["benchmark_provenance"]["source_mapping"].values()))
    entry["extracted_text_sha256"]=sha256_for_text(texts[source])
    p["benchmark_provenance"]["source_mapping_sha256"]=snapshot_identity(p["benchmark_provenance"]["source_mapping"])
    out=align_model_quotes_for_archive(p,texts)
    assert next(x for x in out["excluded"] if x["record_id"]=="dash")["issues"]
