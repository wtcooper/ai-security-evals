import json
import time

from fastapi import HTTPException

from .. import db
from ..security import Principal
from . import models, retrieval, workflows


def save_message(conversation_id, role, content, citations=None):
    message_id = db.new_id("msg")
    db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (message_id, conversation_id, role, content, json.dumps(citations or []), time.time()))
    return message_id


def execute_tool(actor, name, arguments):
    if name != "run_workflow":
        raise HTTPException(422, "Unknown assistant tool")
    row = workflows.get(actor, arguments["workflow_id"])
    membership = db.one("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (actor.workspace_id, row["owner_id"]))
    if not membership:
        raise HTTPException(409, "Workflow owner is unavailable")
    execution_actor = Principal(row["owner_id"], actor.workspace_id, membership["role"])
    result = workflows.run(execution_actor, row["id"])
    artifact = db.one("SELECT body FROM artifacts WHERE id=?", (result["artifact_id"],))
    db.audit(actor.workspace_id, actor.user_id, "assistant.tool_executed", row["id"], {"tool": name})
    return artifact["body"]


def respond(actor, conversation_id, message, tools_enabled):
    records = retrieval.search(actor, message)
    save_message(conversation_id, "user", message)
    output = models.complete(message, records, tools_enabled)
    content = output.get("content") or ""
    calls = output.get("tool_calls", [])[:3] if tools_enabled else []
    for call in calls:
        function = call["function"]
        result = execute_tool(actor, function["name"], json.loads(function["arguments"]))
        content += "\n\n" + result
    citations = [{"document_id": row["document_id"], "title": row["title"]} for row in records]
    message_id = save_message(conversation_id, "assistant", content, citations)
    db.audit(actor.workspace_id, actor.user_id, "assistant.responded", conversation_id, {"tool_calls": len(calls)})
    return {"id": message_id, "content": content.strip(), "citations": citations, "tool_calls": len(calls)}
