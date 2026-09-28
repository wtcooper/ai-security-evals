import json
import time

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import ChatInput, ConversationInput
from ..security import owned_resource, principal
from ..services.assistant import respond

router = APIRouter(prefix="/api/conversations", tags=["Assistant"])


def access(actor, conversation_id):
    row = owned_resource("conversations", conversation_id, actor)
    if row["owner_id"] != actor.user_id:
        raise HTTPException(403, "Conversation belongs to another user")
    return row


@router.get("")
def list_conversations(actor=Depends(principal)):
    return db.many("SELECT * FROM conversations WHERE workspace_id=? AND owner_id=? ORDER BY created_at DESC", (actor.workspace_id, actor.user_id))


@router.post("", status_code=201)
def create_conversation(payload: ConversationInput, actor=Depends(principal)):
    conversation_id = db.new_id("conv")
    db.execute("INSERT INTO conversations VALUES(?,?,?,?,?)", (conversation_id, actor.workspace_id, actor.user_id, payload.title, time.time()))
    return access(actor, conversation_id)


@router.get("/{conversation_id}")
def conversation(conversation_id: str, actor=Depends(principal)):
    row = access(actor, conversation_id)
    messages = db.many("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,))
    for message in messages:
        message["citations"] = json.loads(message["citations"])
    return {**row, "messages": messages}


@router.post("/{conversation_id}/messages")
def send_message(conversation_id: str, payload: ChatInput, actor=Depends(principal)):
    access(actor, conversation_id)
    return respond(actor, conversation_id, payload.message, payload.tools_enabled)
