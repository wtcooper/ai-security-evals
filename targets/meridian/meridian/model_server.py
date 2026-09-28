"""Deterministic local provider for offline demos and integration testing."""
import json
import time
import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Meridian local inference service")


class CompletionRequest(BaseModel):
    model: str
    messages: list[dict]
    tools: list[dict] = Field(default_factory=list)
    temperature: float = 0


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "meridian-local", "object": "model", "owned_by": "meridian"}]}


@app.post("/v1/chat/completions")
def complete(payload: CompletionRequest):
    records = []
    for message in payload.messages:
        try:
            content = json.loads(message.get("content", ""))
            if isinstance(content, dict):
                records.extend(content.get("records", []))
        except (ValueError, TypeError):
            continue
    answer = "\n\n".join(f"[{row.get('title', 'Record')}] {row.get('text', row.get('body', ''))}" for row in records)
    message = {"role": "assistant", "content": answer or "No matching records were found in the research library."}
    if payload.tools:
        cards = [row.get("metadata", {}).get("action_card") for row in records]
        cards = [card for card in cards if isinstance(card, dict) and isinstance(card.get("workflow_id"), str)]
        if cards:
            message["tool_calls"] = [{
                "id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                "function": {"name": "run_workflow", "arguments": json.dumps({"workflow_id": cards[0]["workflow_id"]})},
            }]
    return {
        "id": "chatcmpl_" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
        "model": payload.model, "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}],
        "usage": {"prompt_tokens": sum(len(str(m)) for m in payload.messages) // 4, "completion_tokens": len(answer) // 4},
    }
