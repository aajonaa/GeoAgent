"""P0-3 regression suite: slim review cascade fast paths and parallel semantic review."""
import json
from threading import Event, Lock
import time
from types import SimpleNamespace

import pytest

from geological_agent.agent.fast_path import (
    can_skip_completion_review,
    has_clear_objective,
    is_direct_conversational_query,
    promises_unfinished_work,
)
from geological_agent.agent.semantic_recovery import review_sources
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.requests = []

    def invoke(self, request):
        self.requests.append(request)
        item = next(self.responses)
        return item(request) if callable(item) else item


def test_direct_conversational_and_clear_objective_predicates():
    assert is_direct_conversational_query("你好")
    assert is_direct_conversational_query("你是谁？")
    assert is_direct_conversational_query("你用的什么模型？")
    assert is_direct_conversational_query("Who are you?")
    assert not is_direct_conversational_query("斑岩型铜矿的成矿模式是什么？")
    assert not is_direct_conversational_query("请帮我计算北京到上海的距离")

    assert has_clear_objective("什么是斑岩型铜矿？")
    assert has_clear_objective("请解释流体包裹体均一温度的地质意义")
    assert not has_clear_objective("39.9042, 116.4074; 31.2304, 121.4737")
    assert not has_clear_objective("Beijing: 39.9042,116.4074; Shanghai:31.2304,121.4737")
    assert not has_clear_objective("这个智能体")
    assert not has_clear_objective("帮我查一下")
    assert promises_unfinished_work("Next I will calculate the result.")
    assert promises_unfinished_work("接下来我将读取文件并计算。")
    assert not promises_unfinished_work("断层是岩层发生明显位移的构造变形。")


def test_direct_identity_question_skips_source_selection_and_completion_review(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")
    monkeypatch.setenv("GEOTOOL_OPTIMIZE_ROUND_TRIPS", "1")
    monkeypatch.delenv("GEOTOOL_INTENT_REVIEW", raising=False)
    retriever_calls = []

    class DummyKnowledge:
        def retrieve(self, query, limit=4):
            retriever_calls.append(query)
            return {"status": "empty", "references": []}

    model = ScriptedModel(ModelResponse("我是 OreBOGAO，面向地质科研与矿产勘查的找矿智能体。"))
    agent = create_agent(model, settings=Settings(knowledge_enabled=True, verify_completion=True),
                         knowledge=DummyKnowledge())
    result = agent.run("你是谁？", workspace=tmp_path)
    assert result.status == "completed", result.reason
    # Only 1 LLM call total (skipped both source_selection AND assess_completion)!
    assert result.model_turns == 1 and len(model.requests) == 1
    assert not retriever_calls
    metrics = result.state["metadata"]["review_cascade_metrics"]
    assert metrics["source_selection_skipped"] == 1
    assert metrics["completion_review_skipped"] == 1
    assert metrics["saved_model_turns"] == 2


def test_read_only_ask_mode_skips_redundant_completion_review_and_slim_intent(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")
    monkeypatch.setenv("GEOTOOL_SLIM_INTENT", "1")
    model = ScriptedModel(ModelResponse("断层是岩层发生明显位移的构造变形。"))
    agent = create_agent(model, read_only=True, settings=Settings(verify_completion=True))
    result = agent.run("什么是断层？", workspace=tmp_path)
    assert result.status == "completed", result.reason
    # With GEOTOOL_SLIM_INTENT=1 + read_only completion fast path: 1 LLM call instead of 3!
    assert result.model_turns == 1 and len(model.requests) == 1
    metrics = result.state["metadata"]["review_cascade_metrics"]
    assert metrics["intent_review_skipped"] == 1
    assert metrics["completion_review_skipped"] == 1


def test_slim_intent_still_runs_llm_intent_review_for_vague_or_bare_input(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_SLIM_INTENT", "1")
    model = ScriptedModel(ModelResponse(
        tool_calls=(ToolCall("i1", "assess_task_intent", {
            "objective_present": False, "question": "您想了解什么问题？",
        }),),
        finish_reason="tool_calls",
    ))
    agent = create_agent(model, read_only=True, settings=Settings(verify_completion=False))
    result = agent.run("这个智能体", workspace=tmp_path)
    assert result.status == "needs_input" and result.model_turns == 1
    assert model.requests[0].tools[0].name == "assess_task_intent"


def test_read_only_unfinished_promise_is_not_bypassed_by_fast_path(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOTOOL_COMBINED_COMPLETION_REVIEW", "1")
    monkeypatch.setenv("GEOTOOL_SLIM_INTENT", "1")
    model = ScriptedModel(
        ModelResponse("接下来我将读取文件并分析结果。"),
        ModelResponse(tool_calls=(ToolCall("r1", "assess_completion", {
            "verdict": "revise_answer", "feedback": "Do not promise future execution.",
            "required_outputs": [], "requires_python_execution": False, "evidence_call_ids": [],
        }),), finish_reason="tool_calls"),
        ModelResponse("断层按相对位移可分为正断层、逆断层和平移断层。"),
        ModelResponse(tool_calls=(ToolCall("r2", "assess_completion", {
            "verdict": "complete", "feedback": "",
            "required_outputs": [], "requires_python_execution": False, "evidence_call_ids": [],
        }),), finish_reason="tool_calls"),
    )
    agent = create_agent(model, read_only=True, settings=Settings(verify_completion=True))
    result = agent.run("请解释断层的主要分类？", workspace=tmp_path)
    assert result.status == "completed", result.reason
    # Unfinished promise fell through to full LLM completion review!
    assert len(result.state["metadata"]["completion_reviews"]) == 2


def test_library_first_semantic_review_parallelizes_multiple_four_block_chunks():
    cid = "K" + "a" * 32 + "_1"
    source_text = "Porphyry copper deposits form above subduction zones with potassic alteration."
    paragraphs = [f"Paragraph {i + 1}: porphyry copper forms above subduction zones [{cid}]." for i in range(9)]
    state = {
        "run_id": "a" * 32,
        "task": "Summarize porphyry copper formation.",
        "answer": "\n\n".join(paragraphs),
        "status": "running",
        "model_turns": 1,
        "messages": [],
        "metadata": {
            "library_first": True,
            "usage": [],
            "knowledge": {
                "status": "matched",
                "references": [{
                    "citation_id": cid, "document_id": "a" * 32,
                    "title": "Porphyry Cu", "source": "Test", "text": source_text, "sha256": "b" * 64,
                }],
            },
        },
    }
    concurrency = {"now": 0, "peak": 0}
    lock = Lock()

    class ParallelSemanticModel:
        def invoke(self, request):
            with lock:
                concurrency["now"] += 1
                concurrency["peak"] = max(concurrency["peak"], concurrency["now"])
            time.sleep(0.15)
            with lock:
                concurrency["now"] -= 1
            data = json.loads(request.messages[1].content)
            checks = {
                key: {
                    "verdict": "supported",
                    "source_quotes": [{"source_id": cid, "field": "text",
                                       "quote": "Porphyry copper deposits form above subduction zones"}],
                    "translations": [],
                    "feedback": "",
                }
                for key in data["answer_blocks"]
            }
            return ModelResponse(
                tool_calls=(ToolCall("sem", "assess_knowledge_semantics", {"checks": checks}),),
                finish_reason="tool_calls",
                usage={"prompt_tokens": 100, "completion_tokens": 50},
            )

    t0 = time.perf_counter()
    final_state, issues = review_sources(
        state,
        settings=Settings(max_model_turns=10),
        model=ParallelSemanticModel(),
        cancel=Event(),
        record=lambda u, s: u,
        trace=SimpleNamespace(emit=lambda *a, **kw: None),
        activity=lambda *a, **kw: None,
        pause=lambda s, p, e: {**s, "status": "incomplete", "last_error": e},
    )
    elapsed = time.perf_counter() - t0
    assert not issues
    assert concurrency["peak"] >= 2, f"expected parallel semantic chunks, peak={concurrency['peak']}"
    # 3 chunks of 150ms each ran in parallel (well under 450ms serial).
    assert elapsed < 0.42, f"expected parallel speedup, elapsed={elapsed:.3f}s"
    assert final_state["metadata"]["semantic_parallel_batches"] == 1
    assert len(final_state["metadata"]["knowledge_semantic_reviews"][-1]["checks"]) == 9
