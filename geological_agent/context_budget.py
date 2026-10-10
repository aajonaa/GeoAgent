"""Per-model BPE estimates, never a claim of verified provider capacity."""
from functools import lru_cache
import base64
import io
import json
import math

from .model_context import native_context


@lru_cache(maxsize=64)
def _encodings(model):
    try:
        import tiktoken
    except ImportError:
        raise RuntimeError("Token budgeting requires the context-tokenizers dependency") from None
    try:
        return (tiktoken.encoding_for_model(model),)
    except KeyError:
        # Cross-encoding fallback is an estimate, not this provider's tokenizer.
        return (tiktoken.get_encoding("cl100k_base"), tiktoken.get_encoding("o200k_base"))


def _token_count(text, settings):
    return max(len(enc.encode(text, disallowed_special=())) for enc in _encodings(settings.context_model))


def input_allowance(settings):
    window = settings.context_window_tokens
    if window is None:
        return settings.max_context_chars
    return window - settings.max_output_tokens - max(1024, (window + 19) // 20)


def text_budget_size(text, settings):
    return len(text) if settings.context_window_tokens is None else _token_count(text, settings)


def _image_estimate(url):
    # Vision tokens are not the BPE tokens of a base64 string. This deliberately
    # conservative tile allowance is provider-independent, NOT an exact vision
    # formula. Keep the original image payload unchanged in the actual request.
    from PIL import Image
    encoded = url.split(",", 1)[1]
    with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
        width, height = image.size
    return max(4096, 256 * math.ceil(width / 512) * math.ceil(height / 512))


def request_token_estimate(request, settings):
    context = native_context(request)
    image_tokens = 0
    for message in context["messages"]:
        content = message.get("content")
        if isinstance(content, list):
            prepared = []
            for part in content:
                if part.get("type") == "image_url":
                    image_tokens += _image_estimate(part["image_url"]["url"])
                    prepared.append({"type": "image_url", "image_url": {"detail": part["image_url"].get("detail", "auto")}})
                else:
                    prepared.append(part)
            message["content"] = prepared
    serialized = json.dumps(context, ensure_ascii=False, allow_nan=False)
    # Serialized JSON includes every schema, tool argument/result and retained
    # reasoning field. Native chat/schema framing remains an estimate.
    return _token_count(serialized, settings) + image_tokens + 32 * (len(context["messages"]) + len(request.tools) + 1)


def request_budget_size(request, settings):
    if settings.context_window_tokens is None:
        return len(json.dumps(native_context(request), ensure_ascii=False, allow_nan=False))
    return request_token_estimate(request, settings)


def budget_description(settings):
    window = settings.context_window_tokens
    names = [enc.name for enc in _encodings(settings.context_model)] if window is not None else []
    return {
        "context_window_tokens": window,
        "input_budget_tokens": input_allowance(settings) if window is not None else None,
        "output_reserve_tokens": settings.max_output_tokens if window is not None else None,
        "safety_reserve_tokens": max(1024, (window + 19) // 20) if window is not None else None,
        "legacy_allowance_chars": settings.max_context_chars if window is None else None,
        "count_method": ("tiktoken_native_json_estimate" if len(names) == 1 else "tiktoken_cross_encoding_estimate") if window is not None else "legacy_characters",
        "tokenizer_model": settings.context_model,
        "tokenizer_encodings": names,
        "provider_tokenizer_known": len(names) == 1,
        "native_framing_exact": False,
        "vision_count_method": "conservative_tile_estimate_not_provider_exact",
        "provider_capacity_verified": False,
    }
