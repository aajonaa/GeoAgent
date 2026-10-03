import json
import os
from pathlib import Path
import uuid
import pytest
from geological_agent.rag.store import chunks, lexical, vector, KnowledgeError, KnowledgeIndex, citation_issues, prompt_references
from geological_agent.contracts import ModelResponse, Message
from geological_agent.settings import Settings
from geological_agent.bootstrap import create_agent


def test_question_views_preserve_complete_request_and_all_questions():
    from geological_agent.rag.store import ranking_views
    query="Record check: What is the density? What is the porosity? Cite sources. Do not browse."
    views=ranking_views(query)
    assert views[0]==query
    assert views[1:]==["What is the density?", "What is the porosity?"]
    assert ranking_views("List all rock samples.")==["List all rock samples."]
    chinese="资料核对：岩芯的孔隙度是多少？请带单位，不联网。"
    assert ranking_views(chinese)==[chinese,"岩芯的孔隙度是多少？"]

def test_ranking_policy_bound_to_model_and_override_is_explicit(monkeypatch):
    from geological_agent.rag.store import ranking_policy, RERANK_POLICY
    monkeypatch.delenv("GEOTOOL_KNOWLEDGE_MIN_SCORE",raising=False)
    policy=ranking_policy(RERANK_POLICY["model"])
    assert policy["negative_max"] < policy["threshold"] < policy["positive_min"]
    assert policy["pairs"]==policy["positives"]+policy["negatives"]
    with pytest.raises(KnowledgeError):
        ranking_policy("unreviewed-other-model")
    monkeypatch.setenv("GEOTOOL_KNOWLEDGE_MIN_SCORE","0")
    assert ranking_policy(RERANK_POLICY["model"])["threshold"]==0
    assert "override" in ranking_policy(RERANK_POLICY["model"])["method"]
    assert RERANK_POLICY["threshold"]!=0

@pytest.mark.parametrize("value",["nan","inf","-inf","not-a-number"])
def test_invalid_ranking_threshold_is_explicit(monkeypatch,value):
    from geological_agent.rag.store import ranking_policy, RERANK_POLICY
    monkeypatch.setenv("GEOTOOL_KNOWLEDGE_MIN_SCORE",value)
    with pytest.raises(KnowledgeError): ranking_policy(RERANK_POLICY["model"])

def test_knowledge_dialog_overrides_inherited_maximum():
    css=(Path(__file__).resolve().parents[1]/"geological_agent/team/web/knowledge.css")
    if not css.exists():
        import geological_agent
        css=Path(geological_agent.__file__).parent/"team/web/knowledge.css"
    source=css.read_text(encoding="utf-8")
    assert "#knowledge-dialog{width:min(1080px,94vw);max-width:min(1080px,94vw);" in source
    assert "grid-template-columns:1fr;padding:18px" in source

def test_chunk_coverage_and_offsets():
    text=("Layer A: granite.\n" + "\u5730\u5c42\u539a\u5ea6\u4e0e\u5b54\u9699\u5ea6\u8bb0\u5f55\u3002"*30)*5
    parts=chunks(text)
    covered=set()
    for part in parts:
        assert part["text"]==text[part["start_char"]:part["end_char"]]
        assert len(part["text"])<=600
        covered.update(range(part["start_char"],part["end_char"]))
    assert covered==set(range(len(text)))

def test_lexical_scientific_and_cjk():
    value=lexical("CRUST3-BOTTOM \u5317\u4eac\u5730\u58f3").split()
    assert "crust3" in value and "bottom" in value and "\u5317\u4eac" in value

@pytest.mark.parametrize("value",[[],[0.0]*384,[float("nan")]*384,[True]*384,[1.0]*383])
def test_bad_vectors(value):
    with pytest.raises(KnowledgeError): vector(value)

def test_valid_vector():
    assert len(json.loads(vector([1.0]*384)))==384

def test_citation_validation_preserves_provenance():
    state={"answer":"Value [Kabc_1]", "metadata":{"knowledge":{"references":[{"citation_id":"Kabc_1"}]}}}
    assert not citation_issues(state)
    state["answer"]="Value [Kdifferent_9]"
    assert citation_issues(state)
    assert "candidates" not in prompt_references({"candidates":[{"private":"candidate"}],"references":[{"text":"exact"}]})

def test_retrieval_once_before_model_and_shared_review_evidence(tmp_path,monkeypatch):
    for name in ("GEOTOOL_INTENT_REVIEW","GEOTOOL_COMBINED_COMPLETION_REVIEW","GEOTOOL_KNOWLEDGE"):
        monkeypatch.delenv(name,raising=False)
    calls=[]
    class Retriever:
        def retrieve(self,query,limit):
            calls.append(query)
            return {"status":"matched","references":[{"citation_id":"Kabc_1","title":"Synthetic sample",
                "text":"The sample density is 2.67 g/cm3.","source":"Synthetic acceptance fixture",
                "sha256":"a"*64}]}
    class Model:
        def invoke(self,request):
            assert len(calls)==1
            refs=[m.content for m in request.messages if "Synthetic sample" in m.content]
            assert refs
            return ModelResponse(content="The sample density is 2.67 g/cm3 [Kabc_1].",finish_reason="stop")
    runtime=create_agent(Model(),settings=Settings(knowledge_enabled=True,verify_completion=False),knowledge=Retriever())
    result=runtime.run("Use the supplied sample note: what is its density?",workspace=tmp_path)
    assert result.status=="completed"
    assert len(calls)==1
    state={"task":"question","messages":[Message("user","question")],"artifacts":[],
           "metadata":{"knowledge":{"references":[{"citation_id":"Kabc_1","text":"Exact source"}]}}}
    from geological_agent.agent.completion import completion_evidence
    evidence=completion_evidence(state,runtime.context)
    assert evidence["knowledge_sources"]["references"][0]["text"]=="Exact source"
    assert "source_evidence_policy" in evidence
    assert evidence["observed_actions"]==[]

def test_failed_retrieval_is_explicit_not_fabricated(tmp_path,monkeypatch):
    monkeypatch.delenv("GEOTOOL_KNOWLEDGE",raising=False)
    class Retriever:
        def retrieve(self,*args,**kwargs): raise RuntimeError("secret-DSN-must-not-leak")
    class Model:
        def invoke(self,request):
            payload="\n".join(m.content for m in request.messages)
            assert '"status": "unavailable"' in payload
            assert "secret-DSN" not in payload
            return ModelResponse(content="The knowledge service is unavailable; I cannot verify that fact.",finish_reason="stop")
    result=create_agent(Model(),settings=Settings(knowledge_enabled=True,verify_completion=False),
                        knowledge=Retriever()).run("What does the supplied note say?",workspace=tmp_path)
    assert result.status=="completed"

def test_context_build_does_not_requery():
    class Retriever:
        def search(self,*args,**kwargs): raise AssertionError("Context must use the retrieval node snapshot")
    runtime=create_agent(None,settings=Settings(knowledge_enabled=True),knowledge=Retriever())
    state={"task":"Hi","messages":[Message("user","Hi")],"selected_skill_ids":[],
           "exposed_tool_names":list(runtime.base_tools),"metadata":{"knowledge":{"status":"empty","references":[]}}}
    runtime.context.build(state)
    runtime.context.build(state)

def test_graph_has_automatic_knowledge_node():
    from geological_agent.agent.graph import build_graph
    fn=lambda state: {}
    graph=build_graph(fn,fn,fn,retrieve_knowledge=fn,human_input=fn).get_graph()
    edges={(e.source,e.target) for e in graph.edges}
    assert ("__start__","knowledge") in edges
    assert ("knowledge","model") in edges
    assert ("human","knowledge") in edges

@pytest.fixture
def real_indexes():
    file=os.environ.get("GEOTOOL_TEST_POSTGRES_DSN_FILE")
    socket=os.environ.get("GEOTOOL_ENCODER_SOCKET")
    if not file or not socket:
        pytest.skip("Requires private PostgreSQL + real cross-encoder service")
    from geological_agent.context_store import private_dsn
    from geological_agent.rag.store import EncoderClient
    dsn=private_dsn(file)
    prefix="rag-acceptance-"+uuid.uuid4().hex
    a=KnowledgeIndex(dsn,prefix+"-a",EncoderClient(socket))
    b=KnowledgeIndex(dsn,prefix+"-b",EncoderClient(socket))
    a.setup()
    yield a,b
    for index in (a,b):
        for d in index.documents(): index.delete(d["id"])

def test_real_hybrid_cross_encoder_recall_isolation_and_persistence(real_indexes,tmp_path):
    a,b=real_indexes
    docs=[
        ("Synthetic Granite Lab Record","Synthetic acceptance data, not a real geological measurement. The granite specimen G-17 has a dry bulk density of 2.67 g/cm3. Measure dry mass and divide by external sample volume. Do not confuse density with porosity.","granite"),
        ("\u5408\u6210\u78b3\u5c01\u5b58\u5b9e\u9a8c\u8bb0\u5f55","\u672c\u6761\u4e3a\u5408\u6210\u9a8c\u6536\u6570\u636e\uff0c\u4e0d\u662f\u771f\u5b9e\u5de5\u7a0b\u7ed3\u8bba\u3002\u7802\u5ca9\u5ca9\u5fc3 S-22 \u7684\u5b54\u9699\u5ea6\u4e3a 18.5%\uff0c\u6e17\u900f\u7387\u4e3a 120 mD\u3002\u8be5\u5ca9\u5fc3\u7528\u4e8e\u4e8c\u6c27\u5316\u78b3\u6ce8\u5165\u5b9e\u9a8c\u3002\u8bb0\u5f55\u6ca1\u6709\u5b89\u5168\u6ce8\u5165\u538b\u529b\u6570\u636e\u3002","sandstone"),
        ("Synthetic Field Safety Procedure","Synthetic research-group procedure. Before entering the drilling platform, check the hydrogen sulfide detector and calibrate it with certified gas. Wear an H2S personal monitor. Leave immediately if the detector alarm sounds.","safety"),
        ("Synthetic River Temperature","Synthetic acceptance record. River station R-8 had a water temperature of 12.4 degrees Celsius. This is not a groundwater level or a rock-property measurement.","distractor")]
    identities={}
    for title,text,key in docs:
        identities[key]=a.ingest(title,text,"Synthetic acceptance corpus v1")["id"]
    secret=b.ingest("Private sentinel","The private project access marker is cobalt-raven-824.", "Other account fixture")["id"]
    cases=[
        ("For granite sample G-17, how heavy is a unit volume when dried?", "granite"),
        ("\u4e8c\u6c27\u5316\u78b3\u6ce8\u5165\u7528\u7684S-22\u5ca9\u82af\uff0c\u7a7a\u9699\u6240\u5360\u7684\u767e\u5206\u6bd4\u662f\u591a\u5c11\uff1f","sandstone"),
        ("What detector should I check before stepping onto the drilling platform?", "safety"),
        ("Knowledge RAG acceptance 20261003-A：根据我的知识资料，G-17 花岗岩样品的干体积密度是多少？请带单位、引用来源，并说明是否属于真实测量。不要联网，不创建文件。", "granite"),
        ("Please use my notes: What porosity is recorded for sandstone S-22? Cite the source and state whether it is synthetic.", "sandstone"),
        ("请根据资料回答：进入钻井平台前需要检查什么气体检测仪？请引用来源，不要联网。", "safety"),
        ("According to my knowledge: What safe injection pressure is recorded for S-22? Do not infer a pressure from porosity.", "sandstone"),
]
    outcomes=[]
    for query,key in cases:
        result=a.retrieve(query)
        assert result["status"]=="matched",result
        assert result["references"][0]["document_id"]==identities[key],result
        assert result["reranker"].startswith("cross-encoder/mmarco")
        assert all("rerank_score" in r for r in result["candidates"])
        assert all(r["document_id"]!=secret for r in result["candidates"])
        outcomes.append({"query":query,"expected":key,"result":result})
    combined=a.retrieve("What is the dry bulk density of G-17? What is the porosity of S-22? Cite both source notes.")
    assert {identities["granite"],identities["sandstone"]} <= {r["document_id"] for r in combined["references"]},combined
    assert len(combined["rerank_query_views"])==3
    misses=[]
    for query in ("Who won the 1998 football World Cup final?",
                  "请根据我的资料回答：意大利的首都是哪里？请引用来源，不联网。",
                  "According to my uploaded records: Who wrote Pride and Prejudice? Cite sources. Do not browse."):
        result=a.retrieve(query)
        assert result["status"]=="no_match",result
        misses.append(result)
    miss=misses[0]
    assert miss["status"]=="no_match",miss
    assert a.document(secret) is None
    assert not a.delete(secret)
    assert b.document(secret) is not None
    # RLS is defense-in-depth: even an accidentally unscoped SELECT stays tenant-filtered.
    with a.connection() as conn:
        owners=conn.execute("SELECT DISTINCT owner_id FROM geotool_knowledge.documents").fetchall()
        assert {r["owner_id"] for r in owners}=={a.owner_id}
        row=conn.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='geotool_knowledge.documents'::regclass").fetchone()
        assert row["relrowsecurity"] and row["relforcerowsecurity"]
    fresh=KnowledgeIndex(a.dsn,a.owner_id,a.encoder)
    assert fresh.document(identities["granite"])["body"]==docs[0][1]
    assert fresh.ingest(docs[0][0],docs[0][1],"Synthetic acceptance corpus v1")["reused"]
    assert len(fresh.documents())==4
    target=Path(os.environ.get("GEOTOOL_KNOWLEDGE_ACCEPTANCE_REPORT",str(tmp_path/"retrieval.json")))
    target.write_text(json.dumps({"cases":outcomes,"combined":combined,"no_match":miss,"no_match_cases":misses,"isolation_passed":True,
                                 "persistence_passed":True},ensure_ascii=False,indent=2),encoding="utf-8")

def binding_references():
    return [
        {"citation_id":"Kgranite_1","document_id":"granite","title":"Synthetic Granite Lab Record",
         "text":"Synthetic specimen G-17: dry bulk density 2.67 g/cm3."},
        {"citation_id":"Ksandstone_1","document_id":"sandstone","title":"Synthetic Sandstone Record",
         "text":"Synthetic core S-22: porosity 18.5%; permeability 120 mD. No pressure is recorded."},
        {"citation_id":"Ksafety_1","document_id":"safety","title":"Synthetic Field Safety Procedure",
         "text":"Check the hydrogen sulfide (H2S) detector."},
    ]

def binding_state(answer, references=None):
    return {"answer":answer,"metadata":{"knowledge":{"references":
            binding_references() if references is None else references}}}

@pytest.mark.parametrize("answer",[
    "G-17 density: 2.67 g/cm3 [Kgranite_1].",
    "G-17 density: 2.67 g/cm3. [Kgranite_1]",
    "G-17 density: 2.67 g/cm3 Kgranite_1.",
    "G-17 has density 2.67 g/cm3 and S-22 has porosity 18.5% [Kgranite_1] [Ksandstone_1].",
    "| Sample | Value | Source |\n|---|---|---|\n| G-17 | 2.67 g/cm3 | [Kgranite_1] |\n| S-22 | 18.5% | [Ksandstone_1] |",
    "1. G-17\n   - Title: Synthetic Granite Lab Record\n   - Citation: Kgranite_1\n\n2. S-22\n   - Title: Synthetic Sandstone Record\n   - Citation: Ksandstone_1",
])
def test_citation_binding_valid_claims(answer):
    assert not citation_issues(binding_state(answer))

@pytest.mark.parametrize("answer",[
    "G-17 density: 2.67 g/cm3 [Ksandstone_1].",
    "G-17 density: 2.67 g/cm3. [Ksandstone_1]",
    "G-17 density: 2.67 g/cm3 Ksandstone_1.",
    "G-17 density 2.67 g/cm3 [Ksandstone_1]. S-22 porosity 18.5% [Kgranite_1].",
    "| Sample | Value | Source |\n|---|---|---|\n| G-17 | 2.67 g/cm3 | [Ksandstone_1] |\n| S-22 | 18.5% | [Kgranite_1] |",
    "1. G-17\n   - Title: Synthetic Granite Lab Record\n   - Citation: Ksandstone_1\n\n2. S-22\n   - Title: Synthetic Sandstone Record\n   - Citation: Kgranite_1",
    "Synthetic Granite Lab Record: 2.67 g/cm3 [Ksandstone_1].",
    "Synthetic Field Safety Procedure: check the detector [Kgranite_1].",
])
def test_citation_binding_rejects_wrong_known_sources(answer):
    issues=citation_issues(binding_state(answer))
    assert issues and all("binding mismatch" in issue.message for issue in issues)
    assert all(not issue.needs_action for issue in issues)

@pytest.mark.parametrize("answer",["[Kunknown_9]", "Kffffffffffffffffffffffffffffffff_9", "[Kunknown]"])
def test_unknown_citations_cannot_bypass_with_bare_ids(answer):
    assert "Unknown knowledge citation" in citation_issues(binding_state(answer))[0].message

def test_binding_uses_document_identity_not_title_equality_or_chunk_identity():
    refs=binding_references()
    refs.append({**refs[0],"citation_id":"Kgranite_2","text":"Further metadata."})
    assert not citation_issues(binding_state("G-17 [Kgranite_2]",refs))
    refs[0]["title"]=refs[1]["title"]="Shared title"
    assert not citation_issues(binding_state("Shared title [Ksandstone_1]",refs))
    assert citation_issues(binding_state("G-17 [Ksandstone_1]",refs))

def test_citation_identity_does_not_claim_full_semantic_entailment():
    # The source-aware reviewer, not this bounded identity check, must reject
    # a paraphrased factual error with no explicit contradictory identity.
    assert not citation_issues(binding_state("A claimed fact [Kgranite_1]."))

def test_binding_rejection_revises_answer_without_retrieval_or_tool_rerun(tmp_path,monkeypatch):
    for name in ("GEOTOOL_INTENT_REVIEW","GEOTOOL_COMBINED_COMPLETION_REVIEW","GEOTOOL_KNOWLEDGE"):
        monkeypatch.delenv(name,raising=False)
    retrievals, requests, events=[],[],[]
    class Retriever:
        def retrieve(self,query,limit):
            retrievals.append(query)
            return {"status":"matched","references":binding_references()}
    class Model:
        def invoke(self,request):
            requests.append(request)
            if len(requests)==1:
                return ModelResponse(content="G-17 density 2.67 g/cm3 [Ksandstone_1].",finish_reason="stop")
            assert request.tool_choice=="none"
            assert "citation binding mismatch" in "\n".join(m.content for m in request.messages)
            return ModelResponse(content="G-17 density 2.67 g/cm3 [Kgranite_1].",finish_reason="stop")
    runtime=create_agent(Model(),settings=Settings(knowledge_enabled=True,verify_completion=False),
                         knowledge=Retriever())
    result=runtime.run("According to the sample note, what is the density of G-17?",workspace=tmp_path,
                       on_event=lambda event: events.append(event))
    assert result.status=="completed"
    assert result.answer=="G-17 density 2.67 g/cm3 [Kgranite_1]."
    assert len(retrievals)==1 and len(requests)==2
    assert not any("tool" in str(e.get("event","")) and "execut" in str(e.get("event","")) for e in events)

@pytest.mark.parametrize("answer",[
    "The variable Ksample_1 is the first coefficient.",
    "Define KCl_1 = 2.67 and Ksample_2 = 18.5.",
    "Example:\n```python\nKsample_1 = 2.67\n```",
])
def test_plain_variables_are_not_bare_knowledge_citations(answer):
    assert not citation_issues(binding_state(answer))
    assert not citation_issues({"answer":answer,"metadata":{}})

def test_real_bare_citation_namespace_still_rejects_swapped_sources():
    refs=binding_references()
    refs[0]["citation_id"]="K"+"a"*32+"_1"
    refs[1]["citation_id"]="K"+"b"*32+"_1"
    assert not citation_issues(binding_state("G-17 density 2.67 g/cm3 "+refs[0]["citation_id"],refs))
    assert citation_issues(binding_state("G-17 density 2.67 g/cm3 "+refs[1]["citation_id"],refs))
    assert citation_issues(binding_state("G-17 density 2.67 g/cm3 K"+"f"*32+"_1",refs))
