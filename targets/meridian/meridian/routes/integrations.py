import json
import sqlite3
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from .. import db
from ..config import settings
from ..models import HookDocument, SourceInput
from ..security import Principal, collection_access, owned_resource, principal
from ..services import connectors, documents, queue

router = APIRouter(tags=["Integrations"])


@router.get("/api/sources")
def list_sources(actor=Depends(principal)):
    return db.many("SELECT s.* FROM sources s JOIN collections c ON c.id=s.collection_id WHERE s.workspace_id=? AND (c.access='team' OR ?='admin')", (actor.workspace_id, actor.role))


@router.post("/api/sources", status_code=201)
def create_source(payload: SourceInput, actor=Depends(principal)):
    actor.require("analyst")
    collection_access(actor, payload.collection_id)
    connectors.validate_source_url(payload.url)
    source_id = db.new_id("src")
    try:
        db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)", (source_id, actor.workspace_id, payload.name, payload.collection_id, payload.url, actor.user_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Source name is already registered")
    db.audit(actor.workspace_id, actor.user_id, "source.created", source_id)
    return owned_resource("sources", source_id, actor)


@router.post("/api/sources/{source_id}/sync", status_code=202)
def sync_source(source_id: str, actor=Depends(principal)):
    actor.require("analyst")
    source = owned_resource("sources", source_id, actor)
    collection_access(actor, source["collection_id"])
    return queue.enqueue(actor, "sync", {"source_id": source_id})


@router.post("/api/sources/{source_id}/preview-delivery")
def preview_delivery(source_id: str, payload: HookDocument, actor=Depends(principal)):
    actor.require("analyst")
    source = owned_resource("sources", source_id, actor)
    collection_access(actor, source["collection_id"])
    body = json.dumps(payload.model_dump(), separators=(",", ":"))
    timestamp = str(int(time.time()))
    return {
        "url": f"/hooks/{actor.workspace_id}/{source['name']}", "body": body,
        "headers": {"X-Delivery-Time": timestamp, "X-Delivery-Signature": connectors.delivery_signature(body.encode(), timestamp)},
    }


@router.post("/hooks/{workspace_id}/{source_name}", status_code=202)
async def receive_delivery(workspace_id: str, source_name: str, request: Request,
                           x_delivery_time: str = Header(...), x_delivery_signature: str = Header(...)):
    body = await request.body()
    if len(body) > 120000:
        raise HTTPException(413, "Delivery too large")
    connectors.verify_delivery(body, x_delivery_time, x_delivery_signature)
    try:
        payload = HookDocument.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Invalid delivery document")
    source = db.one("SELECT * FROM sources WHERE workspace_id=? AND name=?", (workspace_id, source_name))
    if not source:
        raise HTTPException(404, "Source not found")
    try:
        db.execute("INSERT INTO hook_deliveries VALUES(?,?,?)", (source["id"], payload.delivery_id, time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Delivery already accepted")
    actor = Principal(source["created_by"], workspace_id, "admin")
    document = documents.create_document(actor, source["collection_id"], payload.title, payload.body, payload.metadata)
    db.audit(workspace_id, actor.user_id, "source.delivery_received", source["id"], {"delivery_id": payload.delivery_id})
    return {"document_id": document["id"]}


@router.get("/api/deliveries/{channel}")
def deliveries(channel: str, actor=Depends(principal)):
    if channel != actor.workspace_id:
        raise HTTPException(403, "Delivery channel is outside the workspace")
    actor.require("analyst")
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.get(f"{settings.connector_url}/deliveries/{channel}")
        response.raise_for_status()
        return response.json()
