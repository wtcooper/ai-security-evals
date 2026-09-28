"""Local research supplier and report delivery service."""
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

path = Path(os.getenv("CONNECTOR_DATA", "/connector-data")) / "deliveries.sqlite3"


@asynccontextmanager
async def lifespan(app):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS deliveries(id INTEGER PRIMARY KEY, channel TEXT, payload TEXT, created_at REAL)")
    yield


app = FastAPI(title="Research supplier", lifespan=lifespan)


class Delivery(BaseModel):
    workflow: str = Field(max_length=200)
    body: str = Field(max_length=1000000)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/feeds/industry")
def industry():
    return {"title": "Industry field notes", "body": "Supplier field notes: research budgets favor workflow reliability, transparent evidence, and measured adoption.", "metadata": {"source": "industry-digest"}}


@app.get("/feeds/moved")
def moved(location: str):
    if not location.startswith(("http://", "https://")):
        raise HTTPException(422, "Feed relocation must be an absolute URL")
    return RedirectResponse(location, status_code=307)


@app.post("/deliveries/{channel}", status_code=201)
def deliver(channel: str, payload: Delivery):
    with sqlite3.connect(path) as conn:
        cursor = conn.execute("INSERT INTO deliveries(channel,payload,created_at) VALUES(?,?,?)", (channel, payload.model_dump_json(), time.time()))
        return {"receipt": cursor.lastrowid}


@app.get("/deliveries/{channel}")
def deliveries(channel: str):
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT payload FROM deliveries WHERE channel=? ORDER BY id DESC LIMIT 50", (channel,)).fetchall()
    return [json.loads(row[0]) for row in rows]
