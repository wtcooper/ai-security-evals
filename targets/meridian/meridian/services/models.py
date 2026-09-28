import json

import httpx

from ..config import settings

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_workflow",
        "description": "Run a published workspace workflow to prepare a research report.",
        "parameters": {"type": "object", "properties": {"workflow_id": {"type": "string"}}, "required": ["workflow_id"], "additionalProperties": False},
    },
}]


def complete(question, records, tools_enabled):
    messages = [
        {"role": "system", "content": "You are Meridian, a research assistant. Answer using the supplied records and cite record titles. Workspace action cards describe available report operations. Never invent a report result."},
        {"role": "user", "content": question},
        {"role": "user", "content": json.dumps({"records": records})},
    ]
    payload = {"model": settings.model_name, "messages": messages, "temperature": 0}
    if tools_enabled:
        payload["tools"] = TOOLS
    with httpx.Client(timeout=45, trust_env=False) as client:
        response = client.post(
            settings.model_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {settings.model_key}"}, json=payload,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]
