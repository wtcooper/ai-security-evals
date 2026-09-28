import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db

bearer = HTTPBearer(auto_error=False)
ROLE_LEVEL = {"viewer": 0, "analyst": 1, "admin": 2}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    salt, expected = encoded.split("$", 1)
    actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1)
    return hmac.compare_digest(actual.hex(), expected)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(401, "Authentication required")
    user = db.one(
        "SELECT u.id,u.email,u.display_name FROM sessions s JOIN users u ON u.id=s.user_id "
        "WHERE s.token_hash=? AND s.expires_at>?",
        (token_hash(credentials.credentials), time.time()),
    )
    if not user:
        raise HTTPException(401, "Session expired")
    return user


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str

    def require(self, role: str):
        if ROLE_LEVEL[self.role] < ROLE_LEVEL[role]:
            raise HTTPException(403, f"{role} role required")


def principal(user=Depends(current_user), x_workspace: str = Header(...)):
    membership = db.one(
        "SELECT role FROM memberships WHERE user_id=? AND workspace_id=?",
        (user["id"], x_workspace),
    )
    if not membership:
        raise HTTPException(403, "Workspace membership required")
    return Principal(user["id"], x_workspace, membership["role"])


def collection_access(actor: Principal, collection_id: str):
    collection = db.one("SELECT * FROM collections WHERE id=?", (collection_id,))
    if not collection or collection["workspace_id"] != actor.workspace_id:
        raise HTTPException(404, "Collection not found")
    if collection["access"] == "restricted":
        actor.require("admin")
    return collection


def owned_resource(table: str, resource_id: str, actor: Principal):
    if table not in {"conversations", "artifacts", "workflows", "jobs", "sources"}:
        raise ValueError("Unknown resource type")
    row = db.one(f"SELECT * FROM {table} WHERE id=? AND workspace_id=?", (resource_id, actor.workspace_id))
    if not row:
        raise HTTPException(404, "Resource not found")
    return row
