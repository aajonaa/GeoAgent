"""The native context actually transmitted to an OpenAI-compatible endpoint."""
import json


def native_context(request):
    messages = []
    for msg in request.messages:
        item = {"role": msg.role, "content": msg.content}
        if msg.reasoning_content is not None:
            if msg.role != "assistant" or not isinstance(msg.reasoning_content, str):
                raise ValueError("Provider reasoning must be text on an assistant message")
            item["reasoning_content"] = msg.reasoning_content
        if msg.image_urls:
            if msg.role != "user" or any(not url.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")) for url in msg.image_urls):
                raise ValueError("Visual input must be prepared local image data in a user message")
            item["content"] = [{"type": "text", "text": msg.content}] + [
                {"type": "image_url", "image_url": {"url": url, "detail": "high"}} for url in msg.image_urls]
        if msg.tool_calls:
            item["tool_calls"] = [{"id": c.id, "type": "function", "function": {"name": c.name,
                "arguments": c.arguments if isinstance(c.arguments, str) else json.dumps(c.arguments, allow_nan=False)}} for c in msg.tool_calls]
        if msg.tool_call_id:
            item["tool_call_id"] = msg.tool_call_id
        messages.append(item)
    context = {"messages": messages}
    if request.tools:
        context["tools"] = [{"type": "function", "function": {"name": t.name,
            "description": t.description + " Use when: " + t.when_to_use,
            "parameters": t.input_schema}} for t in request.tools]
        context["tool_choice"] = request.tool_choice
    return context
