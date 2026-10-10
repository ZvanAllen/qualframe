"""Offline contracts for preparing five-domain synthesis from frozen network outputs."""
import copy
import json
from pathlib import Path

import pytest

from qualframe.cfir_synthesis_preparation import (
    CORE_DOMAINS, NETWORK_COLUMNS, build_cross_domain_plan,
    validate_prepared_response, write_cross_domain_plan,
)
from qualframe.models import StageArtifact

ROOT = Path(__file__).resolve().parents[1]


def inputs(tmp_path):
    result = {}
    for network in ("ON AMN", "NS AMN"):
        rows = {
            domain:[dict(zip(NETWORK_COLUMNS, [domain, "A. Example", "Fictional evidence", "Fictional explanation", "participant-a"]))]
            for domain in CORE_DOMAINS
        }
        artifact = StageArtifact(
            run_id="synthetic-study", stage_id="participant_to_network_synthesis",
            input_path=network+"(1 participants)", input_sha256="a"*64,
            prompt_ref="participant_to_network_synthesis", prompt_sha256="b"*64,
            response_text="synthetic cached output", provider="cached_demo", model="cached",
            timestamp_utc="2026-09-12T00:00:00+00:00", parsed_output=rows,
        )
        path=tmp_path/(network.replace(" ","_")+".json")
        path.write_text(artifact.model_dump_json(),encoding="utf-8")
        result[network]=path
    return result


def plan(tmp_path):
    return build_cross_domain_plan(
        ROOT, inputs(tmp_path), {"id":"synthetic", "codes":[{"id":"code-a"}]},
        input_provenance="Cached synthetic outputs; no human or model quality results.",
    )


def response(request, **changes):
    keys=request["structural_contract"]["required_columns"]
    row=dict.fromkeys(keys,"")
    row.update({"CFIR Domain":request["domain"],"CFIR Construct":"A. Example",
        "Combined Evidence Quotes":"Fictional quote","Synthesized Explanation":"Fictional synthesis",
        "Facilitator Networks":"NS AMN; ON AMN","Overall Valence":"Facilitator",
        "Valence Explanation":"Both fictional groups describe support.","Source File(s)":"NS AMN; ON AMN"})
    row.update(changes)
    return "| "+" | ".join(keys)+" |\n| "+" | ".join("---" for _ in keys)+" |\n| "+" | ".join(row[k] for k in keys)+" |"


def test_plan_prepares_five_distinct_bound_requests_without_dispatch(tmp_path):
    item=plan(tmp_path)
    assert item["provider_calls"]==0
    assert item["provider_configuration"] is None and item["spending_authorized"] is False
    assert [r["domain"] for r in item["requests"]]==list(CORE_DOMAINS)
    assert len({r["user_prompt_sha256"] for r in item["requests"]})==5
    for r in item["requests"]:
        assert "Domain to process = ["+r["domain"]+"]" in r["user_prompt"]
        assert "{CFIR_DOMAIN}" not in r["user_prompt"]
        assert validate_prepared_response(r,response(r))==[]
    assert item["input_provenance"].startswith("Cached synthetic")


def test_no_absent_domain_is_invented(tmp_path):
    mapping=inputs(tmp_path)
    path=mapping["ON AMN"]
    item=json.loads(path.read_text())
    del item["parsed_output"]["Individuals"]
    path.write_text(json.dumps(item))
    with pytest.raises(ValueError,match="five-domain contract"):
        build_cross_domain_plan(ROOT,mapping,{"codes":[{"id":"a"}]},input_provenance="Synthetic")


def test_cohort_and_origin_validation(tmp_path):
    mapping=inputs(tmp_path)
    with pytest.raises(ValueError,match="actual review"):
        build_cross_domain_plan(ROOT,mapping,{"codes":[{"id":"a"}]},input_provenance="")
    with pytest.raises(ValueError,match="known AMN"):
        build_cross_domain_plan(ROOT,{"Unknown":next(iter(mapping.values()))},{"codes":[{"id":"a"}]},input_provenance="Synthetic")
    with pytest.raises(ValueError,match="Outcomes"):
        build_cross_domain_plan(ROOT,mapping,{"codes":[{"id":"a"}]},input_provenance="Synthetic",domains=("Outcomes Addendum",))


def test_cross_run_network_inputs_are_not_silently_combined(tmp_path):
    mapping=inputs(tmp_path)
    path=mapping["ON AMN"]
    item=json.loads(path.read_text())
    item["run_id"]="another-run"
    path.write_text(json.dumps(item))
    with pytest.raises(ValueError,match="different runs"):
        build_cross_domain_plan(ROOT,mapping,{"codes":[{"id":"a"}]},input_provenance="Synthetic")


def test_network_label_must_bind_actual_artifact(tmp_path):
    mapping=inputs(tmp_path)
    mapping["ON AMN"]=mapping["NS AMN"]
    with pytest.raises(ValueError,match="Network identity"):
        build_cross_domain_plan(ROOT,mapping,{"codes":[{"id":"a"}]},input_provenance="Synthetic")


def test_response_rejects_wrong_domain_unknown_network_and_valence_collision(tmp_path):
    request=plan(tmp_path)["requests"][1]
    assert validate_prepared_response(request,response(request,**{"CFIR Domain":"Innovation"}))
    assert validate_prepared_response(request,response(request,**{"Barrier Networks":"ON AMN"}))
    assert validate_prepared_response(request,response(request,**{"Source File(s)":"AB AMN"}))
    assert validate_prepared_response(request,"")


def test_response_rejects_mutated_contract(tmp_path):
    request=plan(tmp_path)["requests"][0]
    changed=copy.deepcopy(request)
    changed["structural_contract"]["allowed_values"]["CFIR Domain"]=["Anything"]
    with pytest.raises(ValueError,match="contract changed"):
        validate_prepared_response(changed,response(request))


def test_dry_run_and_immutable_bundle(tmp_path):
    item=plan(tmp_path)
    output=tmp_path/"out"
    expected=write_cross_domain_plan(item,output,dry_run=True)
    assert not output.exists()
    assert write_cross_domain_plan(item,output)==expected
    assert len(list(expected.glob("*.txt")))==5
    assert write_cross_domain_plan(item,output)==expected
    (expected/"plan.json").write_text("{}")
    with pytest.raises(ValueError,match="existing plan differs"):
        write_cross_domain_plan(item,output)


def test_edited_request_preview_is_not_silently_reused(tmp_path):
    item=plan(tmp_path)
    output=tmp_path/"out"
    folder=write_cross_domain_plan(item,output)
    (folder/"innovation.txt").write_text("Altered prompt",encoding="utf-8")
    with pytest.raises(ValueError,match="request preview differs"):
        write_cross_domain_plan(item,output)