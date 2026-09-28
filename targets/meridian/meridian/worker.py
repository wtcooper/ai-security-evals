import json
import logging
import signal
import time

from . import db
from .security import Principal
from .services import connectors, exports, queue, workflows

logger = logging.getLogger("meridian.worker")
running = True


def process_one():
    job = queue.claim()
    if not job:
        return False
    actor = Principal(job["requested_by"], job["workspace_id"], job["role_snapshot"])
    payload = json.loads(job["payload"])
    try:
        if job["kind"] == "export":
            result = exports.export_collection(actor, job["id"], payload)
        elif job["kind"] == "workflow":
            result = workflows.run(actor, payload["workflow_id"], job["id"])
        elif job["kind"] == "sync":
            source = db.one("SELECT * FROM sources WHERE id=? AND workspace_id=?", (payload["source_id"], actor.workspace_id))
            result = connectors.synchronize(actor, source)
        else:
            raise ValueError("Unknown job kind")
        queue.finish(job["id"], result=result)
        db.audit(actor.workspace_id, actor.user_id, "job.succeeded", job["id"])
    except Exception as exc:
        logger.exception("Job %s failed", job["id"])
        queue.finish(job["id"], error=type(exc).__name__)
        db.audit(actor.workspace_id, actor.user_id, "job.failed", job["id"], {"error": type(exc).__name__})
    return True


def stop(*_):
    global running
    running = False


def main():
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    db.initialize()
    while running:
        if not process_one():
            time.sleep(0.3)


if __name__ == "__main__":
    main()
