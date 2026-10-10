from copy import deepcopy
import json
from types import SimpleNamespace
import pytest

from geological_agent.agent.knowledge_semantics import (
    semantic_request, parse_semantic_review, fingerprint, material)
from geological_agent.agent.compaction import ContextOverflow
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelEvent, ModelResponse, ToolCall
from geological_agent.llm import ModelProtocolError
from geological_agent.settings import Settings

CID = "K" + "a" * 32 + "_1"
SOURCE = "Synthetic training example. Before entering the drilling platform, check the hydrogen sulfide detector."
WRONG = "\u6c22\u6c14\u786b\u5316\u7269"
RIGHT = "\u786b\u5316\u6c22"
BAD = "\u5e94\u68c0\u67e5" + WRONG + "\uff08H2S\uff09\u68c0\u6d4b\u4eea [" + CID + "]"
GOOD = "\u5e94\u68c0\u67e5" + RIGHT + "\uff08hydrogen sulfide\uff09\u68c0\u6d4b\u4eea [" + CID + "]"

def state(answer=BAD):
    return {"answer":answer,"metadata":{"knowledge":{"status":"matched","references":[
        {"citation_id":CID,"document_id":"a"*32,"title":"Synthetic safety note",
         "source":"Synthetic test record","text":SOURCE,"sha256":"b"*64}]}}}

def assessment(request, verdict="supported", term_verdict="equivalent", term=RIGHT, feedback=""):
    data=json.loads(request.messages[1].content)
    checks={}
    for key, block in data["answer_blocks"].items():
        checks[key]={"verdict":verdict,
                     "source_quotes":[{"source_id":CID,"field":"text","quote":"hydrogen sulfide detector"}],
                     "translations":[{"answer_term":term,"source_id":CID,"source_term":"hydrogen sulfide",
                                      "target_term":RIGHT,"verdict":term_verdict}],
                     "feedback":feedback}
    return {"checks":checks}

def response(args):
    return ModelResponse(tool_calls=(ToolCall("audit-call","assess_knowledge_semantics",args),),
                         finish_reason="tool_calls")

def test_semantic_request_is_isolated_and_keeps_exact_source():
    s=state()
    s["messages"]=[{"role":"assistant","content":"Previous reviewer approved everything"}]
    s["metadata"]["completion_reviews"]=[{"verdict":"complete"}]
    req=semantic_request(s,Settings())
    payload=json.loads(req.messages[1].content)
    assert payload["sources"][CID]["text"]==SOURCE
    assert BAD in payload["answer_blocks"].values()
    assert "Previous reviewer" not in req.messages[1].content
    assert req.tool_choice=="required"
    assert req.tools[0].name=="assess_knowledge_semantics"
    assert not any(word in req.messages[0].content for word in (WRONG,RIGHT,"hydrogen sulfide"))

def test_correct_translation_with_source_is_accepted():
    req=semantic_request(state(GOOD),Settings())
    result=parse_semantic_review(response(assessment(req)),req)
    assert result["passed"] and not result["issues"]

def test_translation_mismatch_overrides_claimed_supported_verdict():
    req=semantic_request(state(),Settings())
    result=parse_semantic_review(response(assessment(req,term_verdict="mismatch",term=WRONG)),req)
    assert not result["passed"]
    assert WRONG in result["issues"][0] and RIGHT in result["issues"][0]

@pytest.mark.parametrize("verdict",["revise","uncertain"])
def test_wrong_numbers_negation_or_missing_support_are_not_accepted(verdict):
    req=semantic_request(state(GOOD),Settings())
    args=assessment(req,verdict=verdict,feedback="The answer changes the source limitation.")
    assert not parse_semantic_review(response(args),req)["passed"]

@pytest.mark.parametrize("corruption",[
    "invented_quote","missing_quote","missing_block","unknown_source","wrong_answer_term",
    "unquoted_source_term","missing_translation","not_claim_bypass","empty_target_term"])
def test_semantic_approval_requires_real_evidence_and_complete_coverage(corruption):
    req=semantic_request(state(GOOD),Settings())
    args=assessment(req)
    check=args["checks"]["b1"]
    if corruption=="invented_quote": check["source_quotes"][0]["quote"]="made up source quotation"
    elif corruption=="missing_quote": check["source_quotes"]=[]
    elif corruption=="missing_block": args["checks"]={}
    elif corruption=="unknown_source": check["source_quotes"][0]["source_id"]="Kunknown_1"
    elif corruption=="wrong_answer_term": check["translations"][0]["answer_term"]=WRONG
    elif corruption=="unquoted_source_term": check["source_quotes"][0]["quote"]="drilling platform"
    elif corruption=="missing_translation":
        # A Chinese-only target with an English source needs explicit mapping.
        req=semantic_request(state(GOOD.replace("hydrogen sulfide","H2S")),Settings())
        check["translations"]=[]
    elif corruption=="not_claim_bypass": check.update(verdict="not_claim",source_quotes=[],translations=[])
    elif corruption=="empty_target_term": check["translations"][0]["target_term"]=""
    with pytest.raises(ModelProtocolError): parse_semantic_review(response(args),req)

@pytest.mark.parametrize("kind",["plain_text","wrong_name","missing_id","truncated"])
def test_only_complete_native_review_is_accepted(kind):
    req=semantic_request(state(GOOD),Settings())
    call=ToolCall("" if kind=="missing_id" else "a",
                  "wrong_name" if kind=="wrong_name" else "assess_knowledge_semantics",
                  assessment(req))
    reply=(ModelResponse(content=json.dumps(assessment(req))) if kind=="plain_text" else
           ModelResponse(tool_calls=(call,),finish_reason="length" if kind=="truncated" else "stop"))
    with pytest.raises(ModelProtocolError): parse_semantic_review(reply,req)

def test_plain_literal_variable_example_is_not_a_source_claim():
    req=semantic_request(state("Ksample_1 = 1"),Settings())
    args={"checks":{"b1":{"verdict":"not_claim","source_quotes":[],"translations":[],"feedback":""}}}
    assert parse_semantic_review(response(args),req)["passed"]

def test_review_fingerprint_changes_with_answer_and_exact_evidence():
    a=state(GOOD)
    b=deepcopy(a)
    b["answer"]=BAD
    assert fingerprint(a)!=fingerprint(b)
    b=deepcopy(a)
    b["metadata"]["knowledge"]["references"][0]["text"]="Changed source"
    assert fingerprint(a)!=fingerprint(b)

def test_semantic_context_is_never_silently_truncated():
    with pytest.raises(ContextOverflow):
        semantic_request(state(GOOD),Settings(context_window_tokens=None, max_context_chars=64))

def run_mock(tmp_path,monkeypatch,*,protocol_mode="",budget=32,with_sources=True):
    for key in ("GEOTOOL_INTENT_REVIEW","GEOTOOL_COMBINED_COMPLETION_REVIEW","GEOTOOL_OPTIMIZE_ROUND_TRIPS",
                "GEOTOOL_COMPACT_REVIEW","GEOTOOL_REVIEW_REFERENCE_SETS","GEOTOOL_KNOWLEDGE"):
        monkeypatch.delenv(key,raising=False)
    seen=SimpleNamespace(retrievals=0,semantic=0,events=[],published=[],requests=[])
    class Retriever:
        def retrieve(self,query,limit):
            seen.retrievals+=1
            return state()["metadata"]["knowledge"] if with_sources else {"status":"empty","references":[]}
    class Model:
        def stream(self,request):
            yield ModelEvent("response",response=self.invoke(request))

        def invoke(self,request):
            seen.requests.append(request)
            name=request.tools[0].name if request.tools else ""
            if name=="assess_knowledge_semantics":
                seen.semantic+=1
                if protocol_mode=="always" or (protocol_mode=="once" and seen.semantic==1):
                    return ModelResponse(content="approved")
                wrong=WRONG in request.messages[1].content
                return response(assessment(request,term=WRONG if wrong else RIGHT,
                                           term_verdict="mismatch" if wrong else "equivalent"))
            if name=="assess_completion":
                return ModelResponse(tool_calls=(ToolCall("general-review","assess_completion",
                    {"verdict":"complete","feedback":"","required_outputs":[],
                     "requires_python_execution":False,"evidence_call_ids":[]}),),finish_reason="tool_calls")
            if not with_sources:
                return ModelResponse(content="No source note is available; I cannot verify the detector name.",finish_reason="stop")
            return ModelResponse(content=BAD if seen.semantic==0 else GOOD,finish_reason="stop")
    runtime=create_agent(Model(),settings=Settings(knowledge_enabled=True,max_model_turns=budget),
                         knowledge=Retriever())
    result=runtime.run("Translate the detector name in the supplied note.",workspace=tmp_path,
                       on_text=seen.published.append,on_event=seen.events.append)
    return result,seen

def test_runtime_revises_mistranslation_without_reretrieval_or_tool_execution(tmp_path,monkeypatch):
    result,seen=run_mock(tmp_path,monkeypatch)
    assert result.status=="completed",result.reason
    assert result.answer==GOOD and seen.published==[GOOD]
    assert seen.retrievals==1 and seen.semantic==2
    reviews=result.state["metadata"]["knowledge_semantic_reviews"]
    assert [r["passed"] for r in reviews]==[False,True]
    assert not any(m.role=="tool" for m in result.state["messages"])
    assert result.state["metadata"]["rejected_answers"]
    assert "semantic_pending_draft" not in result.state["metadata"]

def test_invalid_semantic_protocol_is_retried_not_executed(tmp_path,monkeypatch):
    result,seen=run_mock(tmp_path,monkeypatch,protocol_mode="once")
    assert result.status=="completed",result.reason
    assert seen.semantic==3 and seen.retrievals==1
    assert len(result.state["metadata"]["knowledge_semantic_protocol_errors"])==1
    assert seen.published==[GOOD]

def test_repeated_invalid_semantic_protocol_withholds_answer_and_keeps_draft(tmp_path,monkeypatch):
    result,seen=run_mock(tmp_path,monkeypatch,protocol_mode="always")
    assert result.status=="incomplete"
    assert not result.answer and not seen.published
    assert seen.semantic==2 and seen.retrievals==1
    assert result.state["metadata"]["semantic_pending_draft"]["answer"]==BAD

def test_semantic_review_consumes_existing_budget_before_publish(tmp_path,monkeypatch):
    normal,seen=run_mock(tmp_path/"normal",monkeypatch)
    # The first semantic request is after the existing execution/answer stages.
    first=next(i for i,r in enumerate(seen.requests,1)
               if r.tools and r.tools[0].name=="assess_knowledge_semantics")
    result,limited=run_mock(tmp_path/"limited",monkeypatch,budget=first-1)
    assert result.status=="budget_exhausted" and not result.answer
    assert limited.semantic==0 and not limited.published
    assert result.state["metadata"]["semantic_pending_draft"]["answer"]==BAD

def test_tasks_without_selected_sources_get_no_extra_model_call(tmp_path,monkeypatch):
    result,seen=run_mock(tmp_path,monkeypatch,with_sources=False)
    assert result.status=="completed",result.reason
    assert seen.semantic==0
