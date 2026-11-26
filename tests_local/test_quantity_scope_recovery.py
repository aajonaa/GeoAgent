"""Regression cases from the external-model HITL acceptance trace."""
import json
import pytest

from geological_agent.agent.completion import final_answer_request, resolve_final_answer
from geological_agent.contracts import Message, ModelResponse, ToolCall, ToolResult
from geological_agent.geology.validation import validate_energy_answer
from geological_agent.settings import Settings
from geological_agent.team.model_settings import ModelProfile, redact, trace_credentials
from geological_agent.team.protocol import scrub


def observed(answer):
    return {
        "task": "Estimate earthquake energy for Mw=6.0 and explain the TNT conversion.",
        "answer": answer, "artifacts": [], "metadata": {},
        "messages": [
            Message("assistant", tool_calls=(ToolCall("energy", "GeoMagnitudeToEnergy", {"mw": 6.0}),)),
            ToolResult("energy", "GeoMagnitudeToEnergy", "ok",
                       {"energy_j": 63095734448019.43, "tnt_tons": 15080.242458895656}).message()
        ]
    }


@pytest.mark.parametrize("conversion", [
    "1 ton TNT = 4.184e9 J",
    "1 tonne of TNT equals 4.184 GJ",
    "4.184e9 J = 1 tonne TNT",
    "1 kg TNT = 4.184e6 J",
    "1 gram TNT = 4184 J",
    "1 kilotonne TNT = 4.184e12 J",
    "2 tonnes TNT = 8.368e9 J",
    "4.184e9 J per tonne of TNT",
    "4.184e6 J/kg TNT",
    "1 \u5428 TNT = 4.184 \u00d7 10\u2079 J",
    "**1 \u5428 TNT = 4.184 \u00d7 10\u2079 J**",
    "1 \u5343\u514b TNT = 4.184 MJ",
    "1 \u514b TNT = 4.184 kJ",
    "1 \u5343\u5428 TNT = 4.184 TJ",
])
def test_valid_conversion_is_not_mistaken_for_event_energy(conversion):
    state = observed("Event energy: 6.31e13 J.\n" + conversion)
    assert not validate_energy_answer(state)


@pytest.mark.parametrize("conversion", [
    "1 ton TNT = 4.184e12 J",
    "1 kg TNT = 4.184e9 J",
    "4.184e6 J = 1 tonne TNT",
    "1 gram TNT = 4.184 J",
    "2 tonnes TNT = 4.184e9 J",
    "4.184e12 J per tonne TNT",
    "1 ton TNT = 1e999 J",
    "0 ton TNT = 0 J",
    "-1 ton TNT = -4.184e9 J",
])
def test_wrong_conversion_remains_rejected(conversion):
    issues = validate_energy_answer(observed("Event energy: 6.31e13 J.\n" + conversion))
    assert issues
    assert all("TNT conversion" in issue.message for issue in issues)


@pytest.mark.parametrize("answer", [
    "Event energy: 4.184e9 J.",
    "Event energy: 6.31e16 J. Conversion: 1 tonne TNT = 4.184e9 J.",
    "1 tonne TNT = 4.184e9 J. Event energy: 6.31 \u00d7 10\u00b9\u2076 J.",
    "Event energy: 6.31e13 J. Another event estimate: 6.31e16 J. 1 tonne TNT = 4.184e9 J.",
])
def test_conversion_does_not_whitelist_wrong_or_contradictory_result(answer):
    issues = validate_energy_answer(observed(answer))
    assert issues
    assert any("TNT conversion" not in issue.message for issue in issues)


def test_energy_and_conversion_errors_are_both_reported():
    issues = validate_energy_answer(observed("Event: 6.31e16 J. 1 ton TNT = 4.184e12 J."))
    assert len(issues) == 2
    assert any("TNT conversion" in issue.message for issue in issues)
    assert all(not issue.needs_action for issue in issues)


def test_observed_browser_answer_with_tnt_note_is_accepted():
    answer = (
        "\u91ca\u653e\u80fd\u91cf: **6.31 \u00d7 10\u00b9\u00b3 \u7126\u8033\uff08J\uff09** "
        "(6.309573444801943e+13 J)\n"
        "TNT: 15080.24 \u5428\n"
        "\u6362\u7b97\u6309 **1 \u5428 TNT = 4.184 \u00d7 10\u2079 J**."
    )
    assert not validate_energy_answer(observed(answer))


def test_feedback_preserves_scientific_notation_and_successful_tools():
    issue = validate_energy_answer(observed("Event: 6.31e16 J."))[0]
    assert "Equivalent scientific notation" in issue.message
    assert "do not repeat successful calculations" in issue.message
    assert "Do not convert them" not in issue.message


def repair_state(count=2):
    state = observed("Event: 6.31e16 J.")
    state["metadata"]["rejected_answers"] = [
        {"answer": "Event: 6.31e16 J.", "feedback": "Numerical inconsistency: wrong event energy."}
        for _ in range(count)
    ]
    return state


def test_single_numerical_rejection_does_not_add_a_native_format_stage():
    request = final_answer_request(repair_state(1), None, Settings())
    assert request.tool_choice == "none"
    assert not request.tools
    assert json.loads(request.messages[1].content)["rejected_draft"]["text"] == "Event: 6.31e16 J."


def test_repeated_same_numerical_failure_changes_repair_method():
    request = final_answer_request(repair_state(), None, Settings())
    assert request.tool_choice == "required"
    assert [tool.name for tool in request.tools] == ["format_final_answer"]
    schema = request.tools[0].input_schema["properties"]["lines"]
    assert schema["minItems"] == 1 and "maxItems" not in schema
    assert json.loads(request.messages[1].content)["repair_strategy"] == "native_line_array"


def test_different_feedback_does_not_prematurely_force_format_repair():
    state = repair_state()
    state["metadata"]["rejected_answers"][0]["feedback"] = "Missing requested units."
    assert not final_answer_request(state, None, Settings()).tools


def test_repair_method_still_honors_explicit_line_count():
    state = repair_state()
    state["task"] = "Return exactly three lines."
    schema = final_answer_request(state, None, Settings()).tools[0].input_schema["properties"]["lines"]
    assert schema["minItems"] == schema["maxItems"] == 3


@pytest.mark.parametrize("value,rejected", [("6.31e13 J", False), ("6.31e16 J", True)])
def test_native_repair_does_not_bypass_numerical_checks(value, rejected):
    state = repair_state()
    request = final_answer_request(state, None, Settings())
    response = ModelResponse(tool_calls=(ToolCall("format", "format_final_answer", {"lines": [value]}),),
                             finish_reason="tool_calls")
    rendered = resolve_final_answer(response, request)
    assert rendered.content == value and not rendered.tool_calls
    state["answer"] = rendered.content
    assert bool(validate_energy_answer(state)) is rejected
    assert len([m for m in state["messages"] if m.role == "tool"]) == 1


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_local_placeholder_keeps_normal_words_and_protocol_literals(host):
    profile = ModelProfile("builtin", "http://" + host + ":8000/v1", "local", "none")
    env = {"GEOTOOL_MODEL_URL": profile.base_url, "GEOTOOL_MODEL_KEY": "none"}
    credentials = trace_credentials(profile, env)
    assert credentials == ()
    value = {"text": "nonempty nonetheless none", "tool_choice": "none"}
    assert redact(value, credentials) == value
    assert scrub(value, credentials) == value


@pytest.mark.parametrize("source,url", [
    ("custom", "https://api.example.org/v1"),
    ("custom", "http://127.0.0.1:8000/v1"),
    ("builtin", "https://api.example.org/v1"),
])
def test_none_used_as_a_real_custom_or_remote_key_is_not_exempted(source, url):
    profile = ModelProfile(source, url, "model", "none")
    assert trace_credentials(profile, {}) == ("none",)
    assert redact("none", trace_credentials(profile, {})) == "[REDACTED]"


def test_real_credentials_remain_masked_alongside_local_placeholder():
    profile = ModelProfile("custom", "https://api.example.org/v1", "model", "sk-real-test-token")
    env = {"GEOTOOL_MODEL_KEY": "none", "WORKSPACE_MODEL_KEY": "alternate-secret",
           "LANGSMITH_API_KEY": "trace-secret"}
    credentials = trace_credentials(profile, env)
    assert set(credentials) == {"sk-real-test-token", "alternate-secret", "trace-secret"}
    masked = scrub(redact("nonempty sk-real-test-token alternate-secret trace-secret", credentials), credentials)
    assert masked == "nonempty [REDACTED] [REDACTED] [REDACTED]"


def test_remote_legacy_key_and_tracing_key_named_none_remain_protected():
    profile = ModelProfile("builtin", "http://127.0.0.1:8000/v1", "local", "")
    env = {"WORKSPACE_MODEL_URL": "https://api.example.org/v1",
           "WORKSPACE_MODEL_KEY": "none", "LANGSMITH_API_KEY": "none"}
    assert trace_credentials(profile, env) == ("none",)


@pytest.mark.parametrize("key", ["api_token", "api_key", "authorization", "password",
                                 "access_token", "session_token", "refresh_token", "cookie"])
def test_sensitive_fields_stay_masked_even_without_known_secret_values(key):
    assert scrub({key: "none"}, ()) == {key: "[REDACTED]"}
    assert redact({key: "none"}, ()) == {key: "[REDACTED]"}


def test_authorization_header_is_masked_without_treating_none_as_a_global_secret():
    assert scrub("Authorization: Bearer none; nonempty", ()) == "Authorization: Bearer [REDACTED]; nonempty"
