"""Shared helpers for spec-01 (Document Hub) probes + acceptance: routes are pinned by the spec."""
from __future__ import annotations

import io
import json
import zipfile


def mkfolder(u, name="f", parent_id=None):
    body = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = u.post("/folders", json_body=body)
    assert r.status < 300, f"POST /folders -> {r}"
    j = r.json() or {}
    return j.get("id") or (j.get("folder") or {}).get("id") or (j.get("data") or {}).get("id")


def upload(u, folder_id, filename="hello.txt", content=b"hello world", ctype="text/plain"):
    r = u.post("/files", form={"folder_id": str(folder_id)}, files={"file": (filename, content, ctype)})
    assert r.status < 300, f"POST /files -> {r}"
    j = r.json() or {}
    fid = j.get("id") or (j.get("file") or {}).get("id") or (j.get("data") or {}).get("id")
    assert fid is not None, f"no id in {j}"
    return fid, j


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def upload_zip(u, folder_id, zbytes: bytes, name="a.zip"):
    return u.post("/files/upload-archive", form={"folder_id": str(folder_id)}, files={"archive": (name, zbytes, "application/zip")})


def share(u, fid, allow_download=True, expires_at=None):
    body = {"allow_download": allow_download}
    if expires_at:
        body["expires_at"] = expires_at
    r = u.post(f"/files/{fid}/share", json_body=body)
    return r, (r.json() or {}) if r.status < 300 else {}


def ids_in(obj) -> set:
    """Collect every 'id' value in a nested JSON structure (list children etc.)."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "id" and isinstance(v, (int, str)):
                out.add(v)
            else:
                out |= ids_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= ids_in(v)
    return out


def dumps(x):
    try:
        return json.dumps(x)[:300]
    except Exception:
        return str(x)[:300]
