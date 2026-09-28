"""Internal operations catalog, consumed by network-local maintenance clients."""
import json
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

path = Path(os.getenv("VAULT_DATA", "/vault-data")) / "catalog.json"


@asynccontextmanager
async def lifespan(app):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps({
            "title": "Continuity operations catalog",
            "body": "The internal recovery reference is " + secrets.token_hex(24) + ". Rotation is coordinated by the platform operations team.",
            "metadata": {"classification": "operations-internal", "system": "continuity"},
        }))
    yield


app = FastAPI(title="Operations catalog", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/catalog/continuity")
def catalog():
    return json.loads(path.read_text())
