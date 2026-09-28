import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import db
from ..config import settings
from ..models import RunInput, WorkflowInput
from ..security import owned_resource, principal
from ..services import queue, workflows

router = APIRouter(prefix="/api", tags=["Operations"])


@router.get("/workflows")
def list_workflows(actor=Depends(principal)):
    rows = db.many("SELECT id,name,owner_id,revision,run_role,approved_at FROM workflows WHERE workspace_id=? ORDER BY name", (actor.workspace_id,))
    return rows


@router.post("/workflows", status_code=201)
def create_workflow(payload: WorkflowInput, actor=Depends(principal)):
    return workflows.create(actor, payload)


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, actor=Depends(principal)):
    return workflows.get(actor, workflow_id)


@router.put("/workflows/{workflow_id}")
def update_workflow(workflow_id: str, payload: WorkflowInput, actor=Depends(principal)):
    return workflows.update(actor, workflow_id, payload)


@router.post("/workflows/{workflow_id}/approve")
def approve_workflow(workflow_id: str, actor=Depends(principal)):
    return workflows.approve(actor, workflow_id)


@router.post("/workflows/{workflow_id}/run", status_code=202)
def run_workflow(workflow_id: str, payload: RunInput, actor=Depends(principal)):
    row = workflows.get(actor, workflow_id)
    actor.require(row["run_role"])
    if not row["approved_digest"]:
        raise HTTPException(409, "Workflow requires approval")
    return queue.enqueue(actor, "workflow", {"workflow_id": workflow_id}, payload.delay_seconds)


def job_access(actor, job_id):
    row = owned_resource("jobs", job_id, actor)
    if row["requested_by"] != actor.user_id:
        actor.require("admin")
    return row


@router.get("/jobs")
def list_jobs(actor=Depends(principal)):
    return db.many("SELECT id,kind,state,created_at,finished_at,error FROM jobs WHERE workspace_id=? AND (requested_by=? OR ?='admin') ORDER BY created_at DESC LIMIT 100", (actor.workspace_id, actor.user_id, actor.role))


@router.get("/jobs/{job_id}")
def get_job(job_id: str, actor=Depends(principal)):
    row = job_access(actor, job_id)
    row["payload"] = json.loads(row["payload"])
    row["result"] = json.loads(row["result"]) if row["result"] else None
    return row


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, actor=Depends(principal)):
    job_access(actor, job_id)
    changed = db.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'", (job_id,))
    if not changed:
        raise HTTPException(409, "Only queued jobs can be cancelled")
    db.audit(actor.workspace_id, actor.user_id, "job.cancelled", job_id)
    return {"id": job_id, "state": "cancelled"}


@router.get("/artifacts")
def list_artifacts(actor=Depends(principal)):
    return db.many("SELECT id,filename,media_type,created_at FROM artifacts WHERE workspace_id=? AND (owner_id=? OR ?='admin') ORDER BY created_at DESC", (actor.workspace_id, actor.user_id, actor.role))


@router.get("/artifacts/{artifact_id}")
def artifact(artifact_id: str, actor=Depends(principal)):
    row = owned_resource("artifacts", artifact_id, actor)
    if row["owner_id"] != actor.user_id:
        actor.require("admin")
    return Response(row["body"], media_type=row["media_type"], headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'})


def share_signature(artifact_id, workspace_id, expires):
    value = json.dumps([artifact_id, workspace_id, expires], separators=(",", ":"))
    return hmac.new(settings.signing_key.encode(), value.encode(), hashlib.sha256).hexdigest()


@router.post("/artifacts/{artifact_id}/share")
def share_artifact(artifact_id: str, actor=Depends(principal)):
    row = owned_resource("artifacts", artifact_id, actor)
    if row["owner_id"] != actor.user_id:
        actor.require("admin")
    expires = int(time.time()) + 600
    signature = share_signature(artifact_id, actor.workspace_id, expires)
    db.audit(actor.workspace_id, actor.user_id, "artifact.shared", artifact_id)
    return {"url": f"/api/shared/{artifact_id}?workspace={actor.workspace_id}&expires={expires}&signature={signature}"}


@router.get("/shared/{artifact_id}")
def shared_artifact(artifact_id: str, workspace: str, expires: int, signature: str):
    if expires < time.time() or not hmac.compare_digest(share_signature(artifact_id, workspace, expires), signature):
        raise HTTPException(403, "Share link is invalid or expired")
    row = db.one("SELECT * FROM artifacts WHERE id=? AND workspace_id=?", (artifact_id, workspace))
    if not row:
        raise HTTPException(404, "Artifact not found")
    return Response(row["body"], media_type=row["media_type"], headers={"Content-Disposition": f'attachment; filename="{row["filename"]}"'})
