"""Formatting tolerance never becomes factual, semantic or provenance tolerance."""
from copy import deepcopy
import hashlib
import json

import pytest

from geological_agent.agent.source_quotes import bind_source_quote
from geological_agent.agent.knowledge_semantics import (
    semantic_request, parse_semantic_review, SemanticReviewProtocolError)
from geological_agent.settings import Settings
from test_knowledge_semantics import (
    CID, GOOD, RIGHT, WRONG, assessment, response, state)


def test_pdf_paragraph_bold_boundary_maps_back_to_untouched_source():
    source = ("**The pipeline executes sequentially: mineral entities are normalized, and the vocabulary**"
              "\n\n**mapping agent aligns the results to controlled vocabularies.**")
    quote = "mineral entities are normalized, and the vocabulary mapping agent aligns the results to controlled vocabularies."
    bound = bind_source_quote(source, quote)
    assert bound["match_mode"] == "format_normalized"
    assert bound["raw_quote"] == source[bound["start"]:bound["end"]]
    assert "vocabulary**\n\n**mapping" in bound["raw_quote"]
    assert bound["source_field_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert bound["offset_unit"] == "unicode_codepoints"
    term = bind_source_quote(source, "vocabulary mapping", within=(bound["start"], bound["end"]))
    assert term and bound["start"] <= term["start"] < term["end"] <= bound["end"]


@pytest.mark.parametrize("source", [
    "**hydrogen sulfide**\n\n**detector**", "__hydrogen sulfide__\r\n\r\n__detector__",
    "hydrogen\r\nsulfide\t detector", "  **hydrogen sulfide detector**  "])
def test_layout_whitespace_and_paragraph_strong_wrappers_are_allowed(source):
    bound = bind_source_quote(source, "hydrogen sulfide detector")
    assert bound and bound["raw_quote"] == source[bound["start"]:bound["end"]]


@pytest.mark.parametrize(("source", "quote"), [
    ("**Gold is not confirmed.**", "Gold is confirmed."),
    ("**The mass is 12 kg.**", "The mass is 2 kg."),
    ("**The value is 1e-3 m.**", "The value is 1e3 m."),
    ("**The depth is 10 km.**", "The depth is 10 m."),
    ("**hydrogen sulfide detector**", "hydrogen sulfate detector"),
    ("**may indicate alteration**", "indicates alteration"),
    ("**A, B, C.**", "A B C."),
    ("**A omitted material B**", "A B"),
    ("1,000 kg", "1000 kg"), ("H_2O", "H2O"),
    ("2 ** 3 ** 4", "2 3 4"), ("x**y**z", "xyz"),
    ("2 **3** + 4", "2 3 + 4"),
    ("https://example.org/__data__/", "https://example.org/data/"),
    ("`**literal**`", "`literal`"),
    ("```\nreturn\nx\n```", "return x"),
    ("~~~\nreturn\nx\n~~~", "return x"),
    ("\\**literal\\**", "**literal**"),
    ("<b>gold</b>", "gold deposit"),
    ("**A** + **B**", "A + B"),
    ("**Copper.**", "copper."),
    ("**\u22122 kg**", "-2 kg"),
])
def test_factual_changes_operators_and_unsupported_markup_are_rejected(source, quote):
    assert bind_source_quote(source, quote) is None


def test_exact_code_is_accepted_without_presentation_rewriting():
    source = "Use `2**3` literally."
    assert bind_source_quote(source, "`2**3`")["match_mode"] == "exact"


def test_exact_substring_in_escaped_source_keeps_original_offsets():
    source = "\\**literal\\**"
    binding = bind_source_quote(source, "literal")
    assert binding["match_mode"] == "exact"
    assert binding["raw_quote"] == source[binding["start"]:binding["end"]] == "literal"
    assert binding["start"] == 3 and binding["end"] == 10
    assert binding["source_field_sha256"] == hashlib.sha256(source.encode()).hexdigest()


def test_source_locator_and_quote_bounds_are_enforced():
    source = "hydrogen sulfide outside; **other text**; hydrogen sulfide inside"
    low = source.index("hydrogen sulfide inside")
    bound = bind_source_quote(source, "hydrogen sulfide", within=(low, len(source)))
    assert bound["start"] == low
    assert bind_source_quote(source, "outside", within=(low, len(source))) is None
    assert bind_source_quote("https://a/\npath", "https://a/ path", allow_formatting=False) is None
    with pytest.raises(ValueError):
        bind_source_quote(source, "text", within=(-1, 3))


def request_with_formatted_source():
    value = state(GOOD)
    value["metadata"]["knowledge"]["references"][0]["text"] = "**hydrogen**\n\n**sulfide detector**"
    return semantic_request(value, Settings())


def test_semantic_review_keeps_raw_source_and_native_response_unchanged():
    request = request_with_formatted_source()
    native = response(assessment(request))
    original = deepcopy(native.tool_calls[0].arguments)
    result = parse_semantic_review(native, request)
    assert result["passed"]
    assert native.tool_calls[0].arguments == original
    assert json.loads(request.messages[1].content)["sources"][CID]["text"] == "**hydrogen**\n\n**sulfide detector**"
    binding = result["checks"]["b1"]["evidence_bindings"]
    assert binding["quotes"][0]["source_id"] == CID
    assert binding["quotes"][0]["raw_quote"] == "hydrogen**\n\n**sulfide detector"
    assert binding["terms"][0]["raw_quote"] == "hydrogen**\n\n**sulfide"


def test_formatting_tolerance_never_overrides_semantic_mismatch():
    value = state()
    value["metadata"]["knowledge"]["references"][0]["text"] = "**hydrogen**\n\n**sulfide detector**"
    request = semantic_request(value, Settings())
    result = parse_semantic_review(response(assessment(request, term=WRONG, term_verdict="mismatch")), request)
    assert not result["passed"] and result["issues"]


@pytest.mark.parametrize("corruption", ["wrong_source", "wrong_field", "outside_quote", "model_binding"])
def test_provenance_and_term_checks_cannot_be_bypassed(corruption):
    request = request_with_formatted_source()
    args = assessment(request)
    check = args["checks"]["b1"]
    if corruption == "wrong_source":
        check["source_quotes"][0]["source_id"] = "Kunknown_1"
    elif corruption == "wrong_field":
        check["source_quotes"][0]["field"] = "title"
    elif corruption == "outside_quote":
        check["source_quotes"][0]["quote"] = "detector"
    else:
        check["evidence_bindings"] = {"quotes": [{"start": 0, "end": 1}]}
    with pytest.raises(SemanticReviewProtocolError):
        parse_semantic_review(response(args), request)


def test_valid_binding_survives_another_malformed_block_without_approval():
    value = state(GOOD + "\n\n" + GOOD.replace("hydrogen sulfide", "H2S"))
    value["metadata"]["knowledge"]["references"][0]["text"] = "**hydrogen**\n\n**sulfide detector**"
    request = semantic_request(value, Settings())
    args = assessment(request)
    assert len(args["checks"]) == 2
    args["checks"]["b2"]["source_quotes"][0]["quote"] = "fabricated quote"
    with pytest.raises(SemanticReviewProtocolError) as caught:
        parse_semantic_review(response(args), request)
    assert list(caught.value.checks) == ["b1"]
    assert caught.value.checks["b1"]["evidence_bindings"]["quotes"][0]["raw_quote"]
    assert "b2" in caught.value.block_errors
