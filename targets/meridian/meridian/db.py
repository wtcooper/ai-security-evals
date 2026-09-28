import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import settings


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


@contextmanager
def connect():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.database, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript(Path(__file__).with_name("schema.sql").read_text())


def one(sql, args=()):
    with connect() as db:
        row = db.execute(sql, args).fetchone()
        return dict(row) if row else None


def many(sql, args=()):
    with connect() as db:
        return [dict(row) for row in db.execute(sql, args).fetchall()]


def execute(sql, args=()):
    with connect() as db:
        return db.execute(sql, args).rowcount


def audit(workspace, actor, action, resource, detail=None):
    execute(
        "INSERT INTO audit_events(workspace_id,actor_id,action,resource_id,detail,created_at) VALUES(?,?,?,?,?,?)",
        (workspace, actor, action, resource, json.dumps(detail or {}), time.time()),
    )
