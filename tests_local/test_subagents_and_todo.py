"""P1-1 regression suite: isolated Subagents (literature + data_analyst + parallel) and dynamic todo recitation."""
import json
from threading import Lock
import time
from types import SimpleNamespace

import pytest

from geological_agent.agent.completion import observations
from geological_agent.agent.subagent import FORBIDDEN_IN_SUBAGENT
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ModelResponse, ToolCall
from geological_agent.settings import Settings


def test_update_todo_writes_internal_checklist_and_recites_at_tail(tmp_path):
    requests = []
    events = []

    class Model:
        def invoke(self, request):
            requests.append(request)
            if len(requests) == 1:
                return ModelResponse(tool_calls=(ToolCall("t1", "update_todo", {
                    "objective": "Compare two porphyry Cu belts",
                    "items": [
                        {"id": "s1", "task": "Read Jiaodong notes", "status": "done", "evidence": "K123"},
                        {"id": "s2", "task": "Plot Cu-Mo ratios", "status": "in_progress"},
                        {"id": "s3", "task": "Write final synthesis", "status": "pending"},
                    ],
                }),), finish_reason="tool_calls")
            return ModelResponse("Synthesis complete.")

    agent = create_agent(
        Model(),
        settings=Settings(verify_completion=False, max_model_turns=4),
        trace_factory=lambda *a: SimpleNamespace(emit=lambda k, **f: events.append((k, f))),
    )
    result = agent.run("Compare two porphyry Cu belts and summarize.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    # Todo persisted internally under .agent/todo.md and does not pollute deliverable artifacts.
    assert (tmp_path / ".agent/todo.md").is_file()
    assert not result.artifacts
    assert any(k == "todo_updated" for k, _ in events)
    # Turn 2 appends concise todo recitation at the TAIL without mutating messages[0].
    assert len(requests) == 2
    assert requests[0].messages[0] == requests[1].messages[0]
    assert "Current task progress (todo recitation" in requests[1].messages[-1].content
    assert "- [x] s1: Read Jiaodong notes [evidence: K123]" in requests[1].messages[-1].content
    assert "- [~] s2: Plot Cu-Mo ratios" in requests[1].messages[-1].content
    # update_todo is classified as planning, never as scientific execution proof.
    obs = observations(result.state["messages"])
    assert len(obs) == 1 and obs[0]["evidence_role"] == "planning"


def test_delegate_literature_researcher_isolates_context_and_enforces_read_only(tmp_path):
    big_text = "RAW_NOISY_EXCERPT_TOKEN " * 260 + "Grade is 0.85% Cu (sample JD-01, p. 14)."
    (tmp_path / "paper_excerpt.txt").write_text(big_text, encoding="utf-8")
    cid = "K" + "a" * 32 + "_1"
    lead_requests = []
    sub_requests = []

    class DummyKnowledge:
        def retrieve(self, query, limit=4):
            return {
                "status": "matched",
                "references": [{
                    "citation_id": cid, "document_id": "a" * 32,
                    "title": "Jiaodong Cu-Au Note", "source": "Test KB",
                    "text": "Sample JD-01 reports 0.85% Cu.", "sha256": "b" * 64,
                }],
            }

    class DualModel:
        def invoke(self, request):
            if request.tools == () and request.tool_choice == "none":
                # source_selection / source_relevance bounded_json inside knowledge retrieval
                sys_text = request.messages[0].content
                if "source_selection" in sys_text or '"source":"task"' in sys_text:
                    return ModelResponse(json.dumps({"source": "library", "query": "Jiaodong Cu grade"}))
                return ModelResponse(json.dumps({"relevant": [0]}))
            is_sub = "[Subagent Role:" in request.messages[1].content
            if is_sub:
                sub_requests.append(request)
                tool_names = {t.name for t in request.tools}
                # Read-only & depth-1 isolation strictly enforced!
                assert "write_file" not in tool_names
                assert "execute_python" not in tool_names
                assert not (tool_names & FORBIDDEN_IN_SUBAGENT)
                if len(sub_requests) == 1:
                    return ModelResponse(
                        tool_calls=(ToolCall("sub_read", "read_file", {"path": "paper_excerpt.txt"}),),
                        finish_reason="tool_calls",
                        usage={"prompt_tokens": 200, "completion_tokens": 20},
                    )
                return ModelResponse(
                    f"Distilled finding: Cu grade is 0.85% (sample JD-01) [{cid}].",
                    usage={"prompt_tokens": 900, "completion_tokens": 30},
                )
            lead_requests.append(request)
            if len(lead_requests) == 1:
                return ModelResponse(
                    tool_calls=(ToolCall("del1", "delegate_subagent", {
                        "role": "literature_researcher",
                        "task": "Read paper_excerpt.txt and extract the Cu grade with citation ID.",
                        "max_turns": 4,
                    }),),
                    finish_reason="tool_calls",
                    usage={"prompt_tokens": 300, "completion_tokens": 40},
                )
            return ModelResponse(
                f"Observed Cu grade is 0.85% [{cid}].",
                usage={"prompt_tokens": 450, "completion_tokens": 25},
            )

    agent = create_agent(
        DualModel(),
        settings=Settings(verify_completion=False, knowledge_enabled=True, max_model_turns=8),
        knowledge=DummyKnowledge(),
    )
    result = agent.run("Extract Cu grade from paper_excerpt.txt.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert len(lead_requests) == 2 and len(sub_requests) == 2
    # Lead agent's context NEVER received the noisy 6KB raw excerpt!
    assert all("RAW_NOISY_EXCERPT_TOKEN" not in m.content for m in lead_requests[1].messages)
    # Distilled finding and verified citation ID propagated to parent knowledge ledger!
    tool_receipt = json.loads([m for m in result.state["messages"] if m.role == "tool"][0].content)
    assert tool_receipt["status"] == "ok"
    assert cid in tool_receipt["data"]["citation_ids"]
    assert any(r.get("citation_id") == cid for r in result.state["metadata"]["knowledge"]["references"])
    assert "read_file" in tool_receipt["data"]["successful_tools"]
    # Subagent audit trail persisted under .agent/subagents/
    assert (tmp_path / tool_receipt["data"]["audit_path"]).is_file()
    # Subagent usage billed back to parent metadata.
    assert len(result.state["metadata"]["usage"]) >= 4
    assert len(result.state["metadata"]["subagent_runs"]) == 1


def test_delegate_data_analyst_propagates_verified_artifacts_to_parent(tmp_path):
    lead_turns = {"n": 0}
    sub_turns = {"n": 0}

    class Model:
        def invoke(self, request):
            if "[Subagent Role:" in request.messages[1].content:
                sub_turns["n"] += 1
                tool_names = {t.name for t in request.tools}
                assert "execute_python" in tool_names
                assert not (tool_names & FORBIDDEN_IN_SUBAGENT)
                if sub_turns["n"] == 1:
                    return ModelResponse(tool_calls=(ToolCall("py1", "execute_python", {
                        "code": "from pathlib import Path\nPath('summary.csv').write_text('metal,ppm\\nCu,8500\\n')\nprint('Cu=8500 ppm')",
                    }),), finish_reason="tool_calls")
                return ModelResponse("Created summary.csv with Cu=8500 ppm.")
            lead_turns["n"] += 1
            if lead_turns["n"] == 1:
                return ModelResponse(tool_calls=(ToolCall("ana1", "delegate_subagent", {
                    "role": "data_analyst",
                    "task": "Write summary.csv with metal=Cu, ppm=8500 using Python.",
                }),), finish_reason="tool_calls")
            return ModelResponse("Generated summary.csv (Cu = 8500 ppm).")

    agent = create_agent(Model(), settings=Settings(verify_completion=False, max_model_turns=6))
    result = agent.run("Generate summary.csv with Cu=8500 ppm.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert (tmp_path / "summary.csv").is_file()
    # Artifact propagated to parent RunResult.artifacts!
    assert any(a.path == "summary.csv" for a in result.artifacts)
    receipt = json.loads([m for m in result.state["messages"] if m.role == "tool"][0].content)
    assert receipt["data"]["artifacts"][0]["path"] == "summary.csv"
    assert len(receipt["data"]["artifacts"][0]["sha256"]) == 64


def test_run_subagents_parallel_executes_concurrently_and_merges_artifacts(tmp_path):
    concurrency = {"now": 0, "peak": 0}
    lock = Lock()
    lead_turns = {"n": 0}

    class ParallelModel:
        def invoke(self, request):
            text = request.messages[1].content
            if "[Subagent Role:" in text:
                with lock:
                    concurrency["now"] += 1
                    concurrency["peak"] = max(concurrency["peak"], concurrency["now"])
                time.sleep(0.15)
                with lock:
                    concurrency["now"] -= 1
                if "SUB_TASK_A" in text:
                    return ModelResponse("Finding A: Jiaodong belt gold.")
                if "SUB_TASK_B" in text:
                    return ModelResponse("Finding B: Qinling belt Mo.")
                if "SUB_TASK_C" in text:
                    if not any(m.role == "tool" for m in request.messages):
                        return ModelResponse(tool_calls=(ToolCall("w_c", "write_file", {
                            "path": "belt_table.md", "content": "| Belt | Metal |\n|---|---|\n| Jiaodong | Au |\n",
                        }),), finish_reason="tool_calls")
                    return ModelResponse("Created belt_table.md.")
            lead_turns["n"] += 1
            if lead_turns["n"] == 1:
                return ModelResponse(tool_calls=(ToolCall("par1", "run_subagents_parallel", {
                    "tasks": [
                        {"role": "literature_researcher", "task": "SUB_TASK_A: review Jiaodong."},
                        {"role": "literature_researcher", "task": "SUB_TASK_B: review Qinling."},
                        {"role": "data_analyst", "task": "SUB_TASK_C: write belt_table.md."},
                    ],
                }),), finish_reason="tool_calls")
            return ModelResponse("Combined Jiaodong, Qinling, and belt_table.md.")

    agent = create_agent(ParallelModel(), settings=Settings(verify_completion=False, max_model_turns=10))
    t0 = time.perf_counter()
    result = agent.run("Compare Jiaodong & Qinling and produce belt_table.md.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    assert concurrency["peak"] >= 2, f"expected parallel subagents, peak={concurrency['peak']}"
    assert any(a.path == "belt_table.md" for a in result.artifacts)
    receipt = json.loads([m for m in result.state["messages"] if m.role == "tool"][0].content)
    assert receipt["data"]["count"] == 3
    assert [r["role"] for r in receipt["data"]["results"]] == [
        "literature_researcher", "literature_researcher", "data_analyst"
    ]
    assert "Finding A" in receipt["data"]["results"][0]["summary"]
    assert "Finding B" in receipt["data"]["results"][1]["summary"]
    assert len(result.state["metadata"]["subagent_runs"]) == 3


def test_subagent_respects_remaining_parent_budget_limit(tmp_path):
    lead_turns = {"n": 0}

    class Model:
        def invoke(self, request):
            lead_turns["n"] += 1
            if lead_turns["n"] == 1:
                return ModelResponse(tool_calls=(ToolCall("del_over", "delegate_subagent", {
                    "role": "literature_researcher", "task": "Should be blocked by tight budget.",
                }),), finish_reason="tool_calls")
            return ModelResponse("Handled gracefully without exceeding budget.")

    # max_model_turns=2: turn 1 calls delegate_subagent, leaving only 1 turn (reserved for parent synthesis).
    agent = create_agent(Model(), settings=Settings(verify_completion=False, max_model_turns=2))
    result = agent.run("Test budget cap.", workspace=tmp_path)
    assert result.status == "completed", result.reason
    receipt = json.loads([m for m in result.state["messages"] if m.role == "tool"][0].content)
    assert receipt["status"] == "error"
    assert receipt["error"]["code"] == "subagent_budget_exhausted"
