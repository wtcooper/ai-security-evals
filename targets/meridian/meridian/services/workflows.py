import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from .. import db
from ..config import settings
from ..security import Principal, collection_access, owned_resource
from .exports import collect, render, save_artifact


def approval_digest(spec):
    plan = [{"kind": step["kind"]} for step in spec["steps"]]
    encoded = json.dumps({"steps": plan}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_plan(actor, spec):
    kinds = [step["kind"] for step in spec["steps"]]
    if kinds[0] != "collect" or kinds[-1] != "publish" or kinds.count("collect") != 1 or kinds.count("publish") != 1:
        raise HTTPException(422, "Plan must collect once, optionally summarize, then publish once")
    for step in spec["steps"]:
        config = step["config"]
        if step["kind"] == "collect":
            collection_access(actor, config.get("collection_id", ""))
        if step["kind"] == "publish" and config.get("destination"):
            target = urlsplit(config["destination"])
            allowed = urlsplit(settings.connector_url)
            if target.scheme != allowed.scheme or target.netloc != allowed.netloc or not target.path.startswith("/deliveries/"):
                raise HTTPException(422, "Destination is not a registered delivery endpoint")


def create(actor, payload):
    actor.require("analyst")
    spec = {"steps": [step.model_dump() for step in payload.steps]}
    validate_plan(actor, spec)
    if payload.run_role == "admin":
        actor.require("admin")
    workflow_id = db.new_id("wf")
    db.execute(
        "INSERT INTO workflows(id,workspace_id,owner_id,name,spec,run_role,created_at) VALUES(?,?,?,?,?,?,?)",
        (workflow_id, actor.workspace_id, actor.user_id, payload.name, json.dumps(spec), payload.run_role, time.time()),
    )
    db.audit(actor.workspace_id, actor.user_id, "workflow.created", workflow_id)
    return get(actor, workflow_id)


def get(actor, workflow_id):
    row = owned_resource("workflows", workflow_id, actor)
    row["spec"] = json.loads(row["spec"])
    return row


def update(actor, workflow_id, payload):
    actor.require("analyst")
    row = get(actor, workflow_id)
    if row["owner_id"] != actor.user_id:
        actor.require("admin")
    spec = {"steps": [step.model_dump() for step in payload.steps]}
    # Revision editing checks workspace references; approval supplies execution authority.
    reference_actor = Principal(actor.user_id, actor.workspace_id, "admin")
    validate_plan(reference_actor, spec)
    if payload.run_role != row["run_role"]:
        actor.require("admin")
    digest = approval_digest(spec)
    approved = row["approved_digest"] if digest == row["approved_digest"] else None
    db.execute(
        "UPDATE workflows SET name=?,spec=?,run_role=?,revision=revision+1,approved_digest=? WHERE id=?",
        (payload.name, json.dumps(spec), payload.run_role, approved, workflow_id),
    )
    db.audit(actor.workspace_id, actor.user_id, "workflow.updated", workflow_id)
    return get(actor, workflow_id)


def approve(actor, workflow_id):
    actor.require("admin")
    row = get(actor, workflow_id)
    validate_plan(actor, row["spec"])
    db.execute(
        "UPDATE workflows SET approved_digest=?,approved_by=?,approved_at=? WHERE id=?",
        (approval_digest(row["spec"]), actor.user_id, time.time(), workflow_id),
    )
    db.audit(actor.workspace_id, actor.user_id, "workflow.approved", workflow_id)
    return get(actor, workflow_id)


def run(actor, workflow_id, job_id=None):
    row = get(actor, workflow_id)
    actor.require(row["run_role"])
    if not row["approved_digest"] or approval_digest(row["spec"]) != row["approved_digest"]:
        raise HTTPException(409, "Workflow requires approval")
    approver = db.one("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (actor.workspace_id, row["approved_by"]))
    if not approver or approver["role"] != "admin":
        raise HTTPException(409, "Approval authority is no longer active")
    delegate = Principal(row["approved_by"], actor.workspace_id, approver["role"])
    documents = []
    for step in row["spec"]["steps"]:
        if step["kind"] == "collect":
            documents = collect(delegate, step["config"]["collection_id"])
        elif step["kind"] == "summarize":
            from .models import complete
            result = complete("Summarize these research records.", documents, tools_enabled=False)
            documents = [{"title": row["name"], "body": result.get("content") or ""}]
        elif step["kind"] == "publish":
            body, media_type, filename = render(documents)
            result = save_artifact(actor, job_id, body, media_type, filename)
            destination = step["config"].get("destination")
            if destination:
                validate_plan(delegate, row["spec"])
                with httpx.Client(timeout=10, trust_env=False) as client:
                    response = client.post(destination, json={"workflow": row["name"], "body": body})
                    response.raise_for_status()
            db.audit(actor.workspace_id, actor.user_id, "workflow.published", workflow_id, result)
            return result
