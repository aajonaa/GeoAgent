"""Display-only provider process text. Never an execution receipt or final answer."""


def process_event(kind, fields):
    if kind != "model_responded" or fields.get("phase") not in (None, "execution", "intent"):
        return None
    response = fields.get("response")
    if not isinstance(response, dict):
        return None
    text = response.get("reasoning_content")
    if not isinstance(text, str) or not text.strip():
        return None
    return {"kind": "model_process", "phase": fields.get("phase") or "execution",
            "turn": fields.get("turn"), "text": text,
            "source": "provider_reasoning_content", "verified": False}
