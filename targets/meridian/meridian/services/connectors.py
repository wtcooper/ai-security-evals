import hashlib
import hmac
import json
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from .. import db
from ..config import settings
from ..models import DocumentInput
from .documents import create_document


def validate_source_url(url):
    parsed = urlsplit(url)
    registered = urlsplit(settings.connector_url)
    if parsed.scheme != registered.scheme or parsed.netloc != registered.netloc:
        raise HTTPException(422, "URL must use the registered content connector")
    if not parsed.path.startswith("/feeds/") or parsed.username or parsed.password:
        raise HTTPException(422, "URL must identify a connector feed")


def synchronize(actor, source):
    validate_source_url(source["url"])
    with httpx.Client(timeout=10, follow_redirects=True, trust_env=False) as client:
        with client.stream("GET", source["url"]) as response:
            response.raise_for_status()
            data = bytearray()
            for part in response.iter_bytes():
                data.extend(part)
                if len(data) > 100000:
                    raise ValueError("Feed exceeded the import budget")
    payload = DocumentInput.model_validate(json.loads(data))
    document = create_document(actor, source["collection_id"], payload.title, payload.body, payload.metadata)
    db.audit(actor.workspace_id, actor.user_id, "source.synchronized", source["id"], {"document_id": document["id"]})
    return {"document_id": document["id"]}


def delivery_signature(body, timestamp):
    signed = timestamp.encode() + b"." + body
    return hmac.new(settings.connector_key.encode(), signed, hashlib.sha256).hexdigest()


def verify_delivery(body, timestamp, signature):
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        raise HTTPException(401, "Invalid delivery timestamp")
    if age > 300 or not hmac.compare_digest(delivery_signature(body, timestamp), signature):
        raise HTTPException(401, "Invalid delivery signature")
