import json
import time

from .. import db
from ..security import collection_access


def collect(actor, collection_id):
    collection_access(actor, collection_id)
    return db.many(
        "SELECT id,title,body,revision FROM documents WHERE collection_id=? AND archived=0 ORDER BY title",
        (collection_id,),
    )


def render(documents, format="markdown"):
    if format == "json":
        return json.dumps({"documents": documents}, indent=2), "application/json", "report.json"
    return "\n\n".join(f"# {doc['title']}\n\n{doc['body']}" for doc in documents), "text/markdown", "report.md"


def save_artifact(actor, job_id, body, media_type, filename):
    artifact_id = db.new_id("art")
    db.execute(
        "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?)",
        (artifact_id, actor.workspace_id, actor.user_id, job_id, filename, media_type, body, time.time()),
    )
    return {"artifact_id": artifact_id, "filename": filename, "bytes": len(body.encode())}


def export_collection(actor, job_id, payload):
    documents = collect(actor, payload["collection_id"])
    return save_artifact(actor, job_id, *render(documents, payload.get("format", "markdown")))
