"""Display-only contracts; no provider calls."""
import pytest
from geological_agent.team.timeline import process_event
from test_team import group


def test_process_text_is_provider_owned_unverified_and_lossless():
    text = "Provider-returned process text.\n" * 2000
    fields = {"phase": "execution", "turn": 2, "response": {"reasoning_content": text}}
    event = process_event("model_responded", fields)
    assert event["text"] == text
    assert event["verified"] is False
    assert event["source"] == "provider_reasoning_content"
    assert fields["response"]["reasoning_content"] == text


@pytest.mark.parametrize("phase", ["final_answer", "context_compaction", "human_input", "vision"])
def test_internal_stages_do_not_publish_process_text(phase):
    assert process_event("model_responded", {"phase": phase, "response": {"reasoning_content": "private stage"}}) is None


@pytest.mark.parametrize("response", [{"content": "unreviewed final answer"}, {"reasoning_content": None}, {"reasoning_content": "  "}, "invalid"])
def test_no_invented_thinking_or_final_answer_fallback(response):
    assert process_event("model_responded", {"response": response}) is None


def test_review_events_are_never_a_model_process():
    assert process_event("completion_review_responded", {"response": {"reasoning_content": "review draft"}}) is None


def test_timeline_assets_are_served_and_unlisted_paths_stay_blocked(group):
    _, clients = group
    for name in ("timeline.js", "timeline.css"):
        result = clients["alice"].get("/assets/" + name)
        assert result.status_code == 200 and result.content
    assert clients["alice"].get("/assets/timeline.py").status_code == 404
