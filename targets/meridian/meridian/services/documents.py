import json
import time

from fastapi import HTTPException

from .. import db
from ..security import Principal, collection_access


def index_document(conn, document_id, body):
    old = conn.execute("SELECT id FROM chunks WHERE document_id=?", (document_id,)).fetchall()
    conn.executemany("DELETE FROM chunk_search WHERE chunk_id=?", [(row["id"],) for row in old])
    conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
    paragraphs = [body[i:i + 1400] for i in range(0, len(body), 1200)]
    for ordinal, text in enumerate(paragraphs):
        chunk_id = db.new_id("chk")
        conn.execute("INSERT INTO chunks VALUES(?,?,?,?)", (chunk_id, document_id, ordinal, text))
        conn.execute("INSERT INTO chunk_search(chunk_id,text) VALUES(?,?)", (chunk_id, text))


def create_document(actor: Principal, collection_id, title, body, metadata=None):
    actor.require("analyst")
    collection_access(actor, collection_id)
    document_id = db.new_id("doc")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,collection_id,title,body,metadata,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
            (document_id, collection_id, title, body, json.dumps(metadata or {}), actor.user_id, time.time()),
        )
        index_document(conn, document_id, body)
        conn.execute("DELETE FROM retrieval_cache")
    db.audit(actor.workspace_id, actor.user_id, "document.created", document_id)
    return read_document(actor, document_id)


def read_document(actor, document_id):
    doc = db.one("SELECT * FROM documents WHERE id=? AND archived=0", (document_id,))
    if not doc:
        raise HTTPException(404, "Document not found")
    collection_access(actor, doc["collection_id"])
    doc["metadata"] = json.loads(doc["metadata"])
    return doc


def update_document(actor, document_id, update):
    actor.require("analyst")
    read_document(actor, document_id)
    with db.connect() as conn:
        changed = conn.execute(
            "UPDATE documents SET title=?,body=?,metadata=?,revision=revision+1 WHERE id=? AND revision=?",
            (update.title, update.body, json.dumps(update.metadata), document_id, update.expected_revision),
        ).rowcount
        if not changed:
            raise HTTPException(409, "Document changed; reload before editing")
        index_document(conn, document_id, update.body)
        conn.execute("DELETE FROM retrieval_cache")
    db.audit(actor.workspace_id, actor.user_id, "document.updated", document_id)
    return read_document(actor, document_id)
