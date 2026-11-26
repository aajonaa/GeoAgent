"""BPE and multimodal estimates; synthetic data, no model API calls."""
import base64
from dataclasses import replace
import io
import json

from PIL import Image
import pytest
import tiktoken

from geological_agent.contracts import Message, ModelRequest
from geological_agent.model_context import native_context
from geological_agent.settings import Settings
from geological_agent.context_budget import budget_description, request_budget_size, text_budget_size
from geological_agent.agent.compaction import fit_request
from geological_agent.team.model_settings import builtin_profile


@pytest.mark.parametrize("text", ["Hello world", "\u5730\u8d28\u77ff\u4ea7\u9065\u611f"*50, "a"*20000, "<|endoftext|>", "3.548e14 J; 39.9042; 116.4074"])
def test_known_text_uses_bpe_not_characters_or_utf8_bytes(text):
    settings = Settings(context_window_tokens=128000, context_model="gpt-4o")
    encoding = tiktoken.encoding_for_model("gpt-4o")
    assert text_budget_size(text, settings) == len(encoding.encode(text, disallowed_special=()))
    info = budget_description(settings)
    assert info["tokenizer_encodings"] == ["o200k_base"]
    assert info["provider_tokenizer_known"] is True
    assert info["native_framing_exact"] is False
    assert info["provider_capacity_verified"] is False


def test_unknown_model_uses_visible_cross_encoding_estimate():
    settings = Settings(context_window_tokens=128000, context_model="unknown-third-party-model")
    text = "\u5317\u4eac geoscience "*100
    expected = max(len(tiktoken.get_encoding(name).encode(text)) for name in ("cl100k_base","o200k_base"))
    assert text_budget_size(text, settings) == expected
    assert budget_description(settings)["count_method"] == "tiktoken_cross_encoding_estimate"


def test_complete_request_counts_tool_calls_results_reasoning_and_schemas():
    from types import SimpleNamespace
    from geological_agent.contracts import ToolCall
    settings = Settings(context_window_tokens=128000, context_model="gpt-4o")
    tool = SimpleNamespace(name="calc", description="calculate", when_to_use="numeric work",
                          input_schema={"type":"object","properties":{"value":{"type":"number"}}})
    call = ToolCall("c1", "calc", {"value":6.5})
    request = ModelRequest((Message("user","calculate"), Message("assistant","", (call,), reasoning_content="retained reasoning"),
                            Message("tool",'{"joules":3.548e14}',tool_call_id="c1")), (tool,))
    serialized = json.dumps(native_context(request), ensure_ascii=False, allow_nan=False)
    expected = len(tiktoken.encoding_for_model("gpt-4o").encode(serialized, disallowed_special=()))+32*(3+1+1)
    assert request_budget_size(request, settings) == expected
    assert request_budget_size(replace(request,tools=()),settings) < expected
    assert request_budget_size(replace(request,messages=request.messages[:-1]),settings) < expected


def test_image_base64_is_not_counted_as_prose_and_originals_survive():
    # Random-looking pixels make transport encoding much larger than vision input.
    image = Image.new("RGB",(512,512))
    import random
    pixels = random.Random(123).randbytes(512*512*3)
    image.frombytes(pixels)
    output = io.BytesIO()
    image.save(output,format="PNG")
    url = "data:image/png;base64,"+base64.b64encode(output.getvalue()).decode()
    request = ModelRequest((Message("user","Inspect synthetic image",image_urls=(url,)),),())
    settings = Settings(context_window_tokens=128000,context_model="gpt-4o")
    before = native_context(request)
    measured = request_budget_size(request,settings)
    assert 4096 <= measured < 10000
    assert native_context(request) == before
    state = {"task":request.messages[0].content,"messages":list(request.messages),"metadata":{}}
    assert fit_request(request,state,settings) == request
    assert state["messages"] == list(request.messages)
    assert budget_description(settings)["vision_count_method"] == "conservative_tile_estimate_not_provider_exact"


def test_builtin_window_is_explicit_environment_configuration(monkeypatch):
    monkeypatch.setenv("GEOTOOL_MODEL_CONTEXT_TOKENS","32768")
    assert builtin_profile().context_window_tokens == 32768
    assert builtin_profile().runtime_settings()["context_window_tokens"] == 32768
    monkeypatch.delenv("GEOTOOL_MODEL_CONTEXT_TOKENS")
    assert builtin_profile().context_window_tokens == 32768


@pytest.mark.parametrize("model",[True,123,"x"*257])
def test_invalid_tokenizer_model_is_rejected(model):
    with pytest.raises(ValueError):
        Settings(context_model=model)
