import json
from types import SimpleNamespace
import pytest
from geological_agent.agent.compact_review import compact_review_request, parse_compact_review
from geological_agent.agent.intent_review import intent_request, parse_intent
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings
from geological_agent.skills import SkillSummary

FLAGS = ("GEOTOOL_INTENT_REVIEW","GEOTOOL_COMPACT_REVIEW","GEOTOOL_REQUIREMENT_COVERAGE",
         "GEOTOOL_COMBINED_COMPLETION_REVIEW","GEOTOOL_OPTIMIZE_ROUND_TRIPS",
         "GEOTOOL_COMPACT_DISCOVERY","GEOTOOL_REVIEW_REFERENCE_SETS")

def response(name,args,identity="internal"):
    return ModelResponse(tool_calls=(ToolCall(identity,name,args),),finish_reason="tool_calls")

def enable(monkeypatch):
    for flag in FLAGS: monkeypatch.setenv(flag,"1")

class Model:
    def __init__(self,*responses):
        self.responses=iter(responses)
        self.requests=[]
    def invoke(self,request):
        self.requests.append(request)
        value=next(self.responses)
        return value(request) if callable(value) else value

def audit(request):
    payload=json.loads(request.messages[1].content)
    refs=[*payload["answer_line_ids"],*payload["successful_result_ids"]]
    return response("assess_completion",{
        "verdict":"complete","feedback":"","required_outputs":[],"requires_python_execution":False,
        "requirement_checks":{key:refs for key in payload["requirement_ids"]},
        "unmet_requirement_ids":[]},"review")

def test_fused_discovery_keeps_dynamic_native_professional_batch_and_review(tmp_path,monkeypatch):
    enable(monkeypatch)
    args={"lat1":0,"lon1":0,"lat2":0,"lon2":1}
    model=Model(
        response("assess_task_intent",{"objective_present":True,"question":"","skill_ids":["geodesic_coordinate_analysis"]},"intent"),
        ModelResponse(tool_calls=(ToolCall("distance","GeoHaversineDistance",args),
                                  ToolCall("bearing","GeoBearing",args)),finish_reason="tool_calls"),
        ModelResponse("Distance: 111.195 km. Initial bearing: 90 degrees. Spherical approximation."),
        audit)
    result=create_agent(model,settings=Settings(max_model_turns=4)).run(
        "Use professional tools to calculate spherical distance and initial bearing from (0,0) to (0,1). State units and the spherical assumption.",workspace=tmp_path)
    assert result.status=="completed",result.reason
    assert result.model_turns==4 and len(model.requests)==4
    assert result.state["metadata"]["intent_selected_skill_ids"]==["geodesic_coordinate_analysis"]
    definitions={d.name for d in model.requests[1].tools}
    assert {"GeoHaversineDistance","GeoBearing"}<=definitions
    assert "GeoMagnitudeToEnergy" not in definitions
    calls=[c for m in result.state["messages"] for c in m.tool_calls]
    assert [c.name for c in calls]==["GeoHaversineDistance","GeoBearing"]
    results=[json.loads(m.content) for m in result.state["messages"] if m.role=="tool"]
    assert all(r["status"]=="ok" and not r["cached"] for r in results)
    assert results[0]["data"]["distance_km"]==pytest.approx(111.195)
    assert results[1]["data"]["bearing_degrees"]==pytest.approx(90)
    assert len(result.state["metadata"]["completion_reviews"])==1
    assert "unmet_requirement_ids" in model.requests[-1].tools[0].input_schema["properties"]

def test_fused_missing_objective_pauses_without_disclosing_or_executing_tools(tmp_path,monkeypatch):
    enable(monkeypatch)
    model=Model(response("assess_task_intent",{"objective_present":False,"question":"Which result do you need?","skill_ids":[]}))
    result=create_agent(model,human_input=True).run("Beijing: 39.9042,116.4074; Shanghai: 31.2304,121.4737",
           workspace=tmp_path,checkpoint_path=tmp_path/"checkpoint.sqlite3")
    assert result.status=="needs_input" and result.model_turns==1
    assert result.state["selected_skill_ids"]==[]
    assert not [m for m in result.state["messages"] if m.role=="tool"]

def test_fused_selection_can_cover_multiple_skills_without_a_fixed_tool_plan():
    summaries=[SkillSummary("s1","first","first operation","first"),SkillSummary("s2","second","second operation","second")]
    state={"task":"Calculate both outputs","metadata":{}}
    request=intent_request(state,Settings(),skill_summaries=summaries)
    parsed=parse_intent(response("assess_task_intent",{"objective_present":True,"question":"","skill_ids":["s1","s2"]}),
                        skill_summaries=summaries)
    assert parsed["skill_ids"]==["s1","s2"]
    payload=json.loads(request.messages[1].content)
    assert [s["id"] for s in payload["available_skills"]]==["s1","s2"]
    assert "execution_steps" not in payload

@pytest.mark.parametrize("args",[
    {"objective_present":True,"question":"","skill_ids":["unknown"]},
    {"objective_present":False,"question":"What task?","skill_ids":["s1"]},
    {"objective_present":True,"question":"","skill_ids":"s1"},
    {"objective_present":True,"question":""},
])
def test_fused_intent_invalid_selection_fails_closed(args):
    summaries=[SkillSummary("s1","first","first operation","first")]
    with pytest.raises(ModelProtocolError):
        parse_intent(response("assess_task_intent",args),skill_summaries=summaries)

def review_state():
    return {"task":"Calculate the distance. Report the bearing. Do not create files.",
            "answer":"Distance: 10 km\nBearing: 20 degrees","artifacts":[],
            "selected_skill_ids":[],"exposed_tool_names":["GeoHaversineDistance","GeoBearing"],
            "metadata":{"optimize_round_trips":True,"review_reference_sets":True},
            "messages":[
                Message("assistant",tool_calls=(ToolCall("d","GeoHaversineDistance",{}),ToolCall("b","GeoBearing",{}))),
                ToolResult("d","GeoHaversineDistance","ok",{"distance_km":10}).message(),
                ToolResult("b","GeoBearing","ok",{"bearing_degrees":20}).message()]}

def review_payload():
    return {"verdict":"complete","feedback":"","required_outputs":[],"requires_python_execution":False,
            "requirement_checks":{"r1":["a1","t1"],"r2":["a2","t2"],"r3":[]},
            "unmet_requirement_ids":[]}

def test_reference_sets_preserve_requirement_coverage_and_exact_full_evidence():
    state=review_state()
    request=compact_review_request(state,None,Settings())
    payload=json.loads(request.messages[1].content)
    assert payload["observed_actions"][0]["result"]["data"]=={"distance_km":10}
    assert payload["observed_actions"][1]["result"]["data"]=={"bearing_degrees":20}
    parsed=parse_compact_review(response("assess_completion",review_payload()),state,request)
    assert parsed["evidence_call_ids"]==["d","b"]
    assert parsed["requirement_checks"]["r1"]=={"satisfied":True,"answer_quotes":["Distance: 10 km"],"call_ids":["d"]}
    assert parsed["requirement_checks"]["r3"]=={"satisfied":True,"answer_quotes":[],"call_ids":[]}
    assert state["messages"][0].tool_calls[0].id=="d"

@pytest.mark.parametrize("failure",["missing_requirement","unknown_answer","unknown_tool","unknown_unmet","missing_unmet","wrong_shape"])
def test_reference_sets_do_not_accept_weaker_or_invented_evidence(failure):
    state=review_state();request=compact_review_request(state,None,Settings());args=review_payload()
    if failure=="missing_requirement":del args["requirement_checks"]["r2"]
    elif failure=="unknown_answer":args["requirement_checks"]["r1"]=["a999"]
    elif failure=="unknown_tool":args["requirement_checks"]["r1"]=["t999"]
    elif failure=="unknown_unmet":args["unmet_requirement_ids"]=["r999"]
    elif failure=="missing_unmet":del args["unmet_requirement_ids"]
    elif failure=="wrong_shape":args["requirement_checks"]["r1"]={"ok":True}
    with pytest.raises(ModelProtocolError):
        parse_compact_review(response("assess_completion",args),state,request)

def test_unmet_requirement_cannot_be_approved():
    state=review_state();request=compact_review_request(state,None,Settings());args=review_payload()
    args["unmet_requirement_ids"]=["r2"]
    parsed=parse_compact_review(response("assess_completion",args),state,request)
    assert parsed["verdict"]=="revise_answer"
    assert not parsed["requirement_checks"]["r2"]["satisfied"]

def test_failed_tool_not_in_successful_reference_set():
    state=review_state()
    state["messages"][-1]=ToolResult("b","GeoBearing","error",{}).message()
    request=compact_review_request(state,None,Settings())
    with pytest.raises(ModelProtocolError):
        parse_compact_review(response("assess_completion",review_payload()),state,request)

def test_reference_set_output_is_smaller_without_skipping_requirements():
    new=review_payload()
    old={k:v for k,v in new.items() if k not in ("requirement_checks","unmet_requirement_ids")}
    old["evidence_call_ids"]=["t1","t2"]
    old["requirement_checks"]={"r1":{"ok":True,"a":["a1"],"t":["t1"]},
                               "r2":{"ok":True,"a":["a2"],"t":["t2"]},
                               "r3":{"ok":True,"a":[],"t":[]}}
    assert len(json.dumps(new))<len(json.dumps(old))


@pytest.mark.parametrize("answer", ["Energy: 6.31e13 J", "Energy: 6.31 x 10^13 J",
    "Energy: 6.31 × 10¹³ J", "Value: 6.31 × 10⁻³", "Value: 6.31 × 10⁺³"])
def test_scientific_delivery_accepts_equivalent_notations(answer):
    from geological_agent.agent.delivery_contract import delivery_issues
    assert not delivery_issues({"task":"Use scientific notation.","answer":answer})

@pytest.mark.parametrize("answer", ["Energy: 63100000000000 J", "Energy: 6.31 x 10 J", "Energy: 6.31 x 10^ J"])
def test_scientific_delivery_still_rejects_missing_exponents(answer):
    from geological_agent.agent.delivery_contract import delivery_issues
    assert delivery_issues({"task":"Use scientific notation.","answer":answer})

def test_unicode_presentation_does_not_bypass_wrong_energy_check():
    from geological_agent.agent.delivery_contract import delivery_issues
    from geological_agent.geology.validation import validate_energy_answer
    state={"task":"Use scientific notation.","answer":"Energy: 6.31 × 10¹⁶ J","messages":[
        Message("assistant",tool_calls=(ToolCall("e","GeoMagnitudeToEnergy",{"mw":6.0}),)),
        ToolResult("e","GeoMagnitudeToEnergy","ok",{"energy_j":63095734448019.43,"tnt_tons":15080.242458895656}).message()]}
    assert not delivery_issues(state)
    assert validate_energy_answer(state)

def test_fused_authorization_survives_a_protocol_repair(tmp_path,monkeypatch):
    enable(monkeypatch)
    args={"lat1":0,"lon1":0,"lat2":0,"lon2":1}
    model=Model(
        response("assess_task_intent",{"objective_present":True,"question":"","skill_ids":["geodesic_coordinate_analysis"]},"intent"),
        response("GeoHaversineDistance",args,""),
        ModelResponse(tool_calls=(ToolCall("d","GeoHaversineDistance",args),ToolCall("b","GeoBearing",args)),finish_reason="tool_calls"),
        ModelResponse("Distance: 111.195 km. Initial bearing: 90 degrees. Spherical approximation."),
        audit)
    result=create_agent(model,settings=Settings(max_model_turns=5)).run(
        "Use professional tools to calculate distance and bearing from (0,0) to (0,1).",workspace=tmp_path)
    assert result.status=="completed",result.reason
    assert result.model_turns==5
    assert {"GeoHaversineDistance","GeoBearing"}<=set(result.state["exposed_tool_names"])
    results=[json.loads(m.content) for m in result.state["messages"] if m.role=="tool"]
    assert len(results)==2 and all(r["status"]=="ok" for r in results)


@pytest.mark.parametrize("answer,expected",[
    ("6.31 \u00d7 10\u00b9\u00b3 J",6.31e13),
    ("6.31 \u00d7 10\u207a\u00b9\u00b3 J",6.31e13),
    ("6.31 \u00d7 10\u207b\u00b3 J",6.31e-3),
    ("6.31 \u00d7 10\u2070 J",6.31),
    ("6.31\u00d710\u00b9\u2070 kJ",6.31e13),
])
def test_energy_claims_parse_unicode_exponents_with_sign_and_unit(answer,expected):
    from geological_agent.geology.validation import energy_claims
    claims=energy_claims(answer)
    assert len(claims)==1
    assert claims[0].value==pytest.approx(expected)
    assert claims[0].rounding_allowance==pytest.approx(abs(expected)*0.005/6.31)

@pytest.mark.parametrize("answer,issues",[
    ("Energy: 6.31e13 J",0),
    ("Energy: 6.31 \u00d7 10\u00b9\u00b3 J",0),
    ("Energy: 6.31 \u00d7 10\u00b9\u2076 J",1),
    ("Energy: 6.31e13 J; another estimate: 6.31 \u00d7 10\u00b9\u2076 J",1),
    ("Energy: 6.31 \u00d7 10\u00b9\u00b3 J; another estimate: 6.31e16 J",1),
])
def test_unicode_energy_validation_checks_every_claim(answer,issues):
    from geological_agent.geology.validation import energy_claims,validate_energy_answer
    state={"answer":answer,"messages":[
        Message("assistant",tool_calls=(ToolCall("e","GeoMagnitudeToEnergy",{"mw":6.0}),)),
        ToolResult("e","GeoMagnitudeToEnergy","ok",{"energy_j":63095734448019.43,"tnt_tons":15080.242458895656}).message()]}
    assert len(energy_claims(answer))==(2 if "another" in answer else 1)
    assert len(validate_energy_answer(state))==issues
