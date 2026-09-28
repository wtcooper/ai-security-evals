import hashlib
import json
import re
import time

from .. import db
from ..config import settings


def search(actor, query, limit=6):
    terms = sorted(set(re.findall(r"[\w]+", query.casefold())))[:32]
    if not terms:
        return []
    key = hashlib.sha256(json.dumps([terms, limit]).encode()).hexdigest()
    cached = db.one("SELECT chunk_ids FROM retrieval_cache WHERE cache_key=? AND expires_at>?", (key, time.time()))
    if cached:
        chunk_ids = json.loads(cached["chunk_ids"])
        cache_status = "hit"
    else:
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
        rows = db.many(
            "SELECT c.id FROM chunk_search f JOIN chunks c ON c.id=f.chunk_id "
            "JOIN documents d ON d.id=c.document_id JOIN collections co ON co.id=d.collection_id "
            "WHERE chunk_search MATCH ? AND co.workspace_id=? AND d.archived=0 "
            "AND (co.access='team' OR ?='admin') ORDER BY rank LIMIT ?",
            (match, actor.workspace_id, actor.role, limit),
        )
        chunk_ids = [row["id"] for row in rows]
        db.execute(
            "INSERT OR REPLACE INTO retrieval_cache VALUES(?,?,?)",
            (key, json.dumps(chunk_ids), time.time() + settings.cache_seconds),
        )
        cache_status = "miss"
    results = []
    for chunk_id in chunk_ids:
        row = db.one(
            "SELECT c.id,c.text,d.id AS document_id,d.title,d.metadata,co.name AS collection "
            "FROM chunks c JOIN documents d ON d.id=c.document_id "
            "JOIN collections co ON co.id=d.collection_id WHERE c.id=? AND d.archived=0", (chunk_id,),
        )
        if row:
            row["metadata"] = json.loads(row["metadata"])
            results.append(row)
    db.audit(actor.workspace_id, actor.user_id, "retrieval.completed", key, {"cache": cache_status, "count": len(results)})
    return results
