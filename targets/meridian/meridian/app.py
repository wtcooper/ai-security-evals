import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routes import accounts, chat, integrations, library, operations


@asynccontextmanager
async def lifespan(app):
    if not settings.signing_key or not settings.connector_key:
        raise RuntimeError("Application signing keys must be configured")
    db.initialize()
    yield


app = FastAPI(title="Meridian Workspace API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Request-ID"] = uuid.uuid4().hex
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(httpx.HTTPError)
async def upstream_error(request, exc):
    return JSONResponse({"detail": "Upstream service unavailable"}, status_code=502)


@app.get("/health", tags=["System"])
def health():
    db.one("SELECT 1")
    return {"status": "ok", "service": "meridian"}


for router in (accounts.router, library.router, integrations.router, operations.router, chat.router):
    app.include_router(router)

app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "web", html=True), name="web")
