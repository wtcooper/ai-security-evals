import json
import time

from .. import db


def enqueue(actor, kind, payload, delay=0):
    job_id = db.new_id("job")
    now = time.time()
    db.execute(
        "INSERT INTO jobs(id,workspace_id,requested_by,role_snapshot,kind,payload,scheduled_at,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (job_id, actor.workspace_id, actor.user_id, actor.role, kind, json.dumps(payload), now + delay, now),
    )
    db.audit(actor.workspace_id, actor.user_id, "job.queued", job_id, {"kind": kind})
    return {"id": job_id, "state": "queued"}


def claim():
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        job = conn.execute(
            "SELECT * FROM jobs WHERE state='queued' AND scheduled_at<=? ORDER BY created_at LIMIT 1",
            (time.time(),),
        ).fetchone()
        if not job:
            return None
        conn.execute("UPDATE jobs SET state='running',started_at=? WHERE id=?", (time.time(), job["id"]))
        return dict(job)


def finish(job_id, result=None, error=None):
    db.execute(
        "UPDATE jobs SET state=?,result=?,error=?,finished_at=? WHERE id=?",
        ("failed" if error else "succeeded", json.dumps(result), error, time.time(), job_id),
    )
