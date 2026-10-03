import json
from types import SimpleNamespace
import pytest
from geological_agent.agent.execution_contract import requested_execution_issues
from geological_agent.agent.compact_review import compact_review_request, parse_compact_review
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.settings import Settings

NAMES = {"GeoMagnitudeToEnergy", "GeoHaversineDistance"}
TASK = "请先让我选择震级，等待我回复后再使用已有专业工具计算。最终给出能量和公式。"

def state(task=TASK, names=(), status="ok"):
    return {"task":task,"answer":"Energy: 6.31e13 J","artifacts":[],"selected_skill_ids":[],
            "exposed_tool_names":list(NAMES),"metadata":{},
            "messages":[ToolResult(str(i), name, status, {}).message() for i,name in enumerate(names)]}

@pytest.mark.parametrize("names",[(),("request_user_input",),("skill_find",),("skill_load",),
                                      ("request_user_input","skill_load")])
def test_control_actions_do_not_establish_professional_execution(names):
    issues=requested_execution_issues(state(names=names),NAMES)
    assert issues and all(i.needs_action for i in issues)

def test_failed_professional_execution_is_not_evidence():
    assert requested_execution_issues(state(names=("GeoMagnitudeToEnergy",),status="error"),NAMES)

def test_successful_professional_execution_satisfies_minimum():
    assert not requested_execution_issues(state(names=("GeoMagnitudeToEnergy",)),NAMES)

@pytest.mark.parametrize("query",[
    "Use an existing professional tool to compute energy.",
    "Calculate energy using a specialized tool.",
    "Please use GeoMagnitudeToEnergy to calculate energy.",
    "请调用GeoMagnitudeToEnergy计算能量。",
    "Use GeoMagnitudeToEnergy and GeoHaversineDistance.",
])
def test_explicit_requests_are_grounded(query):
    assert requested_execution_issues(state(query),NAMES)

@pytest.mark.parametrize("query",[
    "Explain the magnitude-energy formula.",
    "How to use professional tools?",
    "如何使用专业工具？",
    "Do not use professional tools. Explain the formula only.",
    "不要使用专业工具，只解释公式。",
    "Use request_user_input tool to ask my preference.",
])
def test_no_mandatory_calculation_for_explanations_or_control_requests(query):
    assert not requested_execution_issues(state(query),NAMES)

def test_confirmed_parameter_does_not_erase_original_requirement():
    s=state();s["metadata"]["human_responses"]=[{"text":"6.0"}]
    assert requested_execution_issues(s,NAMES)

def test_explicit_later_withdrawal_does_not_force_tools():
    s=state();s["metadata"]["human_responses"]=[{"text":"不要使用工具，只解释公式。"}]
    assert not requested_execution_issues(s,NAMES)

def test_each_explicit_named_tool_requires_success():
    s=state("Use GeoMagnitudeToEnergy and GeoHaversineDistance.",("GeoMagnitudeToEnergy",))
    assert "GeoHaversineDistance" in requested_execution_issues(s,NAMES)[0].message

def native(name,args,identity):
    return ModelResponse(tool_calls=(ToolCall(identity,name,args),),finish_reason="tool_calls")

def test_compact_request_has_one_reference_namespace_and_all_observations():
    s=state()
    s["metadata"]["optimize_round_trips"]=True
    s["messages"]=[
        Message("assistant",tool_calls=(ToolCall("provider-human","request_user_input",{"question":"Mw?"}),)),
        ToolResult("provider-human","request_user_input","ok",{"question":"Mw?"}).message(),
        Message("assistant",tool_calls=(ToolCall("provider-energy","GeoMagnitudeToEnergy",{"mw":6}),)),
        ToolResult("provider-energy","GeoMagnitudeToEnergy","ok",{"energy_j":6.3095734448e13,"note":"untouched"}).message()]
    request=compact_review_request(s,None,Settings())
    payload=json.loads(request.messages[1].content)
    assert len(request.messages)==2
    assert "provider-human" not in request.messages[1].content
    assert "provider-energy" not in request.messages[1].content
    assert "candidate_answer" not in payload
    assert payload["answer_line_ids"]=={"a1":s["answer"]}
    assert payload["observed_actions"][0]["evidence_role"]=="interaction"
    assert payload["observed_actions"][1]["evidence_role"]=="execution"
    assert payload["observed_actions"][1]["result"]["data"]=={"energy_j":6.3095734448e13,"note":"untouched"}
    assert s["messages"][0].tool_calls[0].id=="provider-human"
    checks={key:{"ok":True,"a":["a1"],"t":["t2"]} for key in payload["requirement_ids"]}
    parsed=parse_compact_review(native("assess_completion",{
        "verdict":"complete","feedback":"","required_outputs":[],"requires_python_execution":False,
        "evidence_call_ids":["t2"],"requirement_checks":checks},"audit"),s,request)
    assert parsed["evidence_call_ids"]==["provider-energy"]

def test_plain_answer_cannot_bypass_required_execution(tmp_path,monkeypatch):
    monkeypatch.setenv("GEOTOOL_INTENT_REVIEW","0")
    requests=[]
    def invoke(request):
        requests.append(request)
        return ModelResponse("6.31e13 J")
    result=create_agent(SimpleNamespace(invoke=invoke)).run(TASK,workspace=tmp_path)
    assert result.status=="incomplete" and result.answer==""
    assert [request.tool_choice for request in requests]==["required", "required"]
    assert len(requests)==2
    assert not result.artifacts
    assert not any(message.role=="tool" for message in result.state["messages"])
    assert len(result.state["metadata"]["protocol_failures"])==2

def test_human_resume_executes_professional_tool_once(tmp_path,monkeypatch):
    for key in ("GEOTOOL_INTENT_REVIEW","GEOTOOL_COMPACT_REVIEW","GEOTOOL_REQUIREMENT_COVERAGE","GEOTOOL_COMBINED_COMPLETION_REVIEW","GEOTOOL_OPTIMIZE_ROUND_TRIPS"):
        monkeypatch.setenv(key,"1")
    question={"question":"Choose magnitude","reason":"Magnitude missing","missing":["mw"],"options":["5.0","6.0"],
              "reason_type":"missing_input","supporting_call_ids":[],"approval_tool_names":[]}
    answer="Mw 6.0: 6.31e13 J. Formula: log10(E/J)=1.5 Mw+4.8."
    def review(request):
        payload=json.loads(request.messages[1].content)
        energy=[r["result"]["call_id"] for r in payload["observed_actions"] if r["result"]["name"]=="GeoMagnitudeToEnergy"]
        assert energy
        return native("assess_completion",{"verdict":"complete","feedback":"","required_outputs":[],
            "requires_python_execution":False,"evidence_call_ids":energy,
            "requirement_checks":{key:{"ok":True,"a":["a1"],"t":energy} for key in payload["requirement_ids"]}},"audit")
    responses=iter([
        native("assess_task_intent",{"objective_present":True,"question":""},"intent"),
        native("request_user_input",question,"ask"),
        native("assess_human_input",{"decision":"ask","feedback":"Magnitude missing"},"human-audit"),
        native("skill_load",{"skill_id":"earthquake_energy"},"load"),
        native("GeoMagnitudeToEnergy",{"mw":6.0},"energy"),
        ModelResponse(answer),review])
    requests=[]
    def invoke(request):
        requests.append(request);response=next(responses)
        return response(request) if callable(response) else response
    agent=create_agent(SimpleNamespace(invoke=invoke),human_input=True)
    kwargs={"workspace":tmp_path/"work","checkpoint_path":tmp_path/"checkpoint.sqlite3"}
    first=agent.run(TASK,**kwargs)
    assert first.status=="needs_input" and first.model_turns==3
    second=agent.run(TASK,resume={"run_id":first.run_id,"request_id":first.state["metadata"]["pending_input"]["id"],
                                "text":"6.0","files":[]},**kwargs)
    assert second.status=="completed" and second.model_turns==7
    records=[json.loads(m.content) for m in second.state["messages"] if m.role=="tool"]
    assert [r["name"] for r in records]==["request_user_input","skill_load","GeoMagnitudeToEnergy"]
    assert requests[3].tool_choice==requests[4].tool_choice=="required"
    assert requests[5].tool_choice=="auto"
    assert second.answer==answer
