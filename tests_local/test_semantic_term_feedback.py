"""Synthetic evidence fixtures for precise, non-authorizing review corrections."""
from copy import deepcopy
import hashlib
import json
from threading import Event
from types import SimpleNamespace

import pytest

from geological_agent.agent.knowledge_semantics import (
    SemanticReviewProtocolError, parse_semantic_review, semantic_request,
)
from geological_agent.agent.semantic_recovery import review_sources
from geological_agent.contracts import ModelEvent, ModelResponse, ToolCall
from geological_agent.settings import Settings


CID = "K" + "a" * 32 + "_1"
OTHER = "K" + "b" * 32 + "_2"
TERM = "structured, machine-readable knowledge bases"
SOURCE = (
    "Synthetic test record. The process first reads scanned PDFs. "
    "It creates structured, machine-readable knowledge bases without certifying mineral reserves. "
    "The sample contains 10 mg/kg, not 100 mg/kg."
)
ANSWER = "The framework produces structured knowledge [" + CID + "]."
PREFIX = "Compared term needs its exact quoted source evidence: "


def make_state(source=SOURCE):
    return {
        "run_id": "synthetic-term-feedback", "status": "running",
        "answer": ANSWER, "messages": [], "model_turns": 0,
        "metadata": {"usage": [], "knowledge": {"status": "matched", "references": [
            {"citation_id": CID, "document_id": "a" * 32,
             "title": "Synthetic source", "source": "Synthetic test fixture",
             "text": source, "sha256": hashlib.sha256(source.encode()).hexdigest()},
        ]}},
    }


def native_review(term=TERM):
    return ModelResponse(tool_calls=(ToolCall("audit-feedback", "assess_knowledge_semantics", {
        "checks": {"b1": {
            "verdict": "supported", "feedback": "",
            "source_quotes": [{"source_id": CID, "field": "text",
                               "quote": "The process first reads scanned PDFs."}],
            "translations": [{"answer_term": "structured knowledge", "source_id": CID,
                              "source_term": term, "target_term": "structured knowledge",
                              "verdict": "equivalent"}],
        }},
    }),), finish_reason="tool_calls")


def rejected_detail(request, response):
    with pytest.raises(SemanticReviewProtocolError) as exc:
        parse_semantic_review(response, request)
    error = exc.value
    assert not error.checks and not error.issues
    assert error.block_errors["b1"].startswith(PREFIX)
    return json.loads(error.block_errors["b1"][len(PREFIX):]), error


def test_missing_quote_identifies_term_source_and_original_location_without_mutation():
    state = make_state()
    request = semantic_request(state, Settings())
    response = native_review()
    before_state, before_args = deepcopy(state), deepcopy(response.tool_calls[0].arguments)
    detail, _ = rejected_detail(request, response)
    assert detail["block_id"] == "b1" and detail["source_id"] == CID
    assert detail["source_term"] == TERM and detail["answer_term"] == "structured knowledge"
    assert detail["source_term_found"] is True
    quote, location = detail["suggested_source_quote"], detail["original_location"]
    assert quote["quote"] == SOURCE[location["start"]:location["end"]]
    assert SOURCE[location["term_start"]:location["term_end"]] == TERM
    assert location["source_field_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert state == before_state and response.tool_calls[0].arguments == before_args
    assert "evidence_bindings" not in response.tool_calls[0].arguments["checks"]["b1"]


def test_submitting_repaired_quote_passes_with_original_binding():
    request = semantic_request(make_state(), Settings())
    response = native_review()
    detail, _ = rejected_detail(request, response)
    response.tool_calls[0].arguments["checks"]["b1"]["source_quotes"].append(detail["suggested_source_quote"])
    verdict = parse_semantic_review(response, request)
    assert verdict["passed"] and not verdict["issues"]
    assert verdict["checks"]["b1"]["evidence_bindings"]


@pytest.mark.parametrize("term", [
    "structured machine readable knowledge bases", "STRUCTURED, MACHINE-READABLE KNOWLEDGE BASES",
    "does certify mineral reserves", "1000 mg/kg", "10 g/kg",
])
def test_absent_or_altered_terms_stay_rejected_without_fabricated_excerpt(term):
    detail, _ = rejected_detail(semantic_request(make_state(), Settings()), native_review(term))
    assert detail["source_term_found"] is False
    assert "suggested_source_quote" not in detail and "original_location" not in detail
    assert "do not invent a quote" in detail["repair"]


def test_excerpt_cannot_be_borrowed_from_another_source():
    state = make_state(SOURCE.replace(TERM, "a structured index"))
    state["metadata"]["knowledge"]["references"].append({
        "citation_id": OTHER, "document_id": "b" * 32, "text": SOURCE,
        "title": "Other synthetic source", "source": "Synthetic", "sha256": "b" * 64,
    })
    detail, _ = rejected_detail(semantic_request(state, Settings()), native_review())
    assert detail["source_id"] == CID and not detail["source_term_found"]
    assert "suggested_source_quote" not in detail


def test_diagnostic_fields_cannot_be_submitted_as_verified_evidence():
    request = semantic_request(make_state(), Settings())
    response = native_review()
    detail, _ = rejected_detail(request, response)
    check = response.tool_calls[0].arguments["checks"]["b1"]
    check["source_quotes"].append(detail["suggested_source_quote"])
    check["evidence_bindings"] = detail["original_location"]
    with pytest.raises(SemanticReviewProtocolError):
        parse_semantic_review(response, request)


def test_normalized_term_diagnostic_still_quotes_untouched_original():
    source = SOURCE.replace(TERM, "structured,\n machine-readable knowledge bases")
    request = semantic_request(make_state(source), Settings())
    response = native_review()
    detail, _ = rejected_detail(request, response)
    quote = detail["suggested_source_quote"]["quote"]
    assert "structured,\n machine-readable" in quote and quote in source
    response.tool_calls[0].arguments["checks"]["b1"]["source_quotes"].append(detail["suggested_source_quote"])
    assert parse_semantic_review(response, request)["passed"]


def test_recovery_forwards_specific_feedback_and_rechecks_without_task_replay():
    state = make_state()
    originals = deepcopy(state)
    requests, events, pauses = [], [], []

    class Model:
        def invoke(self, request):
            requests.append(request)
            response = native_review()
            if len(requests) == 2:
                data = json.loads(request.messages[1].content)
                feedback = data["protocol_feedback"]
                assert feedback["pending_blocks"] == ["b1"]
                block_errors = json.loads(feedback["error"].split(": ", 1)[1])
                detail = json.loads(block_errors["b1"][len(PREFIX):])
                assert detail["source_term"] == TERM and detail["source_id"] == CID
                assert feedback["rejected_checks"]
                response.tool_calls[0].arguments["checks"]["b1"]["source_quotes"].append(detail["suggested_source_quote"])
            return response

        def stream(self, request):
            yield ModelEvent("response", response=self.invoke(request))

    result, issues = review_sources(
        state, settings=Settings(), model=Model(), cancel=Event(),
        record=lambda *args: None,
        trace=SimpleNamespace(emit=lambda name, **data: events.append((name, data))),
        activity=lambda *args, **kwargs: None,
        pause=lambda *args: pauses.append(args),
    )
    assert not issues and not pauses and len(requests) == 2
    assert result["model_turns"] == 2 and result["answer"] == originals["answer"]
    assert result["metadata"]["knowledge"] == originals["metadata"]["knowledge"]
    assert result["messages"] == originals["messages"]
    assert result["metadata"]["knowledge_semantic_reviews"][-1]["passed"]
    assert "semantic_pending_draft" not in result["metadata"]
    assert all(request.tools[0].name == "assess_knowledge_semantics" for request in requests)
    assert not any("tool_" in name or "retriev" in name for name, _ in events)
