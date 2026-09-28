import secrets
import time

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import Login, RoleInput
from ..security import bearer, current_user, principal, token_hash, verify_password

router = APIRouter(prefix="/api", tags=["Accounts"])


@router.post("/auth/login")
def login(payload: Login):
    user = db.one("SELECT * FROM users WHERE email=?", (payload.email.casefold(),))
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user["id"], time.time() + 8 * 3600))
    return {"access_token": token, "token_type": "bearer", "expires_in": 8 * 3600}


@router.post("/auth/logout", status_code=204)
def logout(user=Depends(current_user), credentials=Depends(bearer)):
    db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(credentials.credentials),))


@router.get("/me")
def me(user=Depends(current_user)):
    memberships = db.many(
        "SELECT w.id,w.name,m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=?",
        (user["id"],),
    )
    return {**user, "workspaces": memberships}


@router.get("/members")
def members(actor=Depends(principal)):
    actor.require("admin")
    return db.many("SELECT u.id,u.email,u.display_name,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE workspace_id=?", (actor.workspace_id,))


@router.patch("/members/{user_id}")
def change_role(user_id: str, payload: RoleInput, actor=Depends(principal)):
    actor.require("admin")
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        member = conn.execute("SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (actor.workspace_id, user_id)).fetchone()
        if not member:
            raise HTTPException(404, "Member not found")
        count = conn.execute("SELECT count(*) FROM memberships WHERE workspace_id=? AND role='admin'", (actor.workspace_id,)).fetchone()[0]
        if member["role"] == "admin" and payload.role != "admin" and count == 1:
            raise HTTPException(409, "Workspace must retain an administrator")
        conn.execute("UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?", (payload.role, actor.workspace_id, user_id))
    db.audit(actor.workspace_id, actor.user_id, "member.role_changed", user_id, {"role": payload.role})
    return {"user_id": user_id, "role": payload.role}


@router.get("/audit")
def audit_log(actor=Depends(principal), after: int = 0):
    actor.require("admin")
    return db.many("SELECT * FROM audit_events WHERE workspace_id=? AND id>? ORDER BY id LIMIT 200", (actor.workspace_id, after))
