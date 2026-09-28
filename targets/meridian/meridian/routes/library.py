import time

from fastapi import APIRouter, Depends

from .. import db
from ..models import CollectionInput, DocumentInput, DocumentUpdate, ExportInput, SearchInput
from ..security import collection_access, principal
from ..services import documents, queue, retrieval

router = APIRouter(prefix="/api", tags=["Library"])


@router.get("/collections")
def collections(actor=Depends(principal)):
    return db.many(
        "SELECT c.*,count(d.id) AS document_count FROM collections c LEFT JOIN documents d ON d.collection_id=c.id AND d.archived=0 "
        "WHERE workspace_id=? AND (access='team' OR ?='admin') GROUP BY c.id ORDER BY c.name",
        (actor.workspace_id, actor.role),
    )


@router.post("/collections", status_code=201)
def create_collection(payload: CollectionInput, actor=Depends(principal)):
    actor.require("analyst")
    if payload.access == "restricted":
        actor.require("admin")
    collection_id = db.new_id("col")
    db.execute("INSERT INTO collections VALUES(?,?,?,?)", (collection_id, actor.workspace_id, payload.name, payload.access))
    db.audit(actor.workspace_id, actor.user_id, "collection.created", collection_id)
    return collection_access(actor, collection_id)


@router.get("/collections/{collection_id}/documents")
def list_documents(collection_id: str, actor=Depends(principal)):
    collection_access(actor, collection_id)
    return db.many("SELECT id,title,revision,created_at FROM documents WHERE collection_id=? AND archived=0 ORDER BY created_at DESC", (collection_id,))


@router.post("/collections/{collection_id}/documents", status_code=201)
def create_document(collection_id: str, payload: DocumentInput, actor=Depends(principal)):
    return documents.create_document(actor, collection_id, payload.title, payload.body, payload.metadata)


@router.get("/documents/{document_id}")
def get_document(document_id: str, actor=Depends(principal)):
    return documents.read_document(actor, document_id)


@router.put("/documents/{document_id}")
def update_document(document_id: str, payload: DocumentUpdate, actor=Depends(principal)):
    return documents.update_document(actor, document_id, payload)


@router.delete("/documents/{document_id}", status_code=204)
def archive_document(document_id: str, actor=Depends(principal)):
    actor.require("analyst")
    documents.read_document(actor, document_id)
    with db.connect() as conn:
        conn.execute("UPDATE documents SET archived=1 WHERE id=?", (document_id,))
        conn.execute("DELETE FROM retrieval_cache")
    db.audit(actor.workspace_id, actor.user_id, "document.archived", document_id, {"at": time.time()})


@router.post("/search")
def search(payload: SearchInput, actor=Depends(principal)):
    return {"results": retrieval.search(actor, payload.query, payload.limit)}


@router.post("/exports", status_code=202)
def export(payload: ExportInput, actor=Depends(principal)):
    actor.require("analyst")
    collection_access(actor, payload.collection_id)
    return queue.enqueue(actor, "export", payload.model_dump(exclude={"delay_seconds"}), payload.delay_seconds)
