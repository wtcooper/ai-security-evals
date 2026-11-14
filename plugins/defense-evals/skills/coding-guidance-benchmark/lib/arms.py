"""Arms: opaque folders placed in front of the coding agent before it starts.

The benchmark copies an arm folder and never reads what is in it. Two names are reserved:

  arm.json   optional label, e.g. {"control_type": "rules file"}. Used only to name the arm
             in the report. Never copied.
  _home/     optional. Its contents are copied into the agent user's home directory
             (user-level configuration). Everything else is copied into the agent's
             working directory.

`baseline` is the implicit arm with nothing installed; no folder may use that name.
Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
from pathlib import Path

BASELINE = "baseline"
LABEL_FILE = "arm.json"
HOME_DIR = "_home"
ARM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def read_label(arm_dir: str | Path) -> dict:
    """The arm's label. A missing arm.json is fine; a broken one is an error, so a typo
    cannot silently drop the control type from the report."""
    path = Path(arm_dir) / LABEL_FILE
    if not path.is_file():
        return {"control_type": None, "description": None}
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: must be a JSON object such as {{\"control_type\": \"skill\"}}")
    return {"control_type": data.get("control_type"), "description": data.get("description")}


def _files(arm_dir: Path) -> list[tuple[Path, str]]:
    """(source file, path relative to the arm folder), sorted. Symlinks are followed when they
    stay inside the arm folder and rejected when they point out of it."""
    root = arm_dir.resolve()
    out = []
    for dirpath, dirnames, filenames in os.walk(arm_dir, followlinks=True):
        dirnames.sort()
        for name in sorted(filenames):
            src = Path(dirpath) / name
            real = src.resolve()
            if root != real and root not in real.parents:
                raise ValueError(f"{src}: symlink points outside the arm folder")
            rel = src.relative_to(arm_dir).as_posix()
            if rel == LABEL_FILE:
                continue
            out.append((src, rel))
    return out


def install_plan(arm_dir: str | Path | None, workspace: str, home: str) -> list[dict]:
    """Where each file of the arm goes. Pure path arithmetic: no file is opened.
    `workspace` and `home` are POSIX paths as the agent sees them."""
    if arm_dir is None:
        return []
    plan = []
    for src, rel in _files(Path(arm_dir)):
        if rel.split("/", 1)[0] == HOME_DIR:
            inner = rel.split("/", 1)[1] if "/" in rel else None
            if inner is None:      # a plain file named _home: treat as workspace content
                root, inner = "workspace", rel
            else:
                root = "home"
        else:
            root, inner = "workspace", rel
        base = home if root == "home" else workspace
        plan.append({"src": str(src), "rel": inner, "root": root,
                     "dest": posixpath.join(base, inner),
                     "mode": src.stat().st_mode & 0o777})
    return plan


def install(arm_dir: str | Path | None, workspace: str | Path, home: str | Path) -> list[dict]:
    """Copy the arm into a workspace and home directory on this machine. Bytes and permission
    bits are preserved; nothing is parsed, rendered or filtered."""
    plan = install_plan(arm_dir, str(workspace), str(home))
    for item in plan:
        dest = Path(item["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item["src"], dest)
        os.chmod(dest, item["mode"])
    return plan


def fingerprint(arm_dir: str | Path | None) -> str | None:
    """sha256 over every file's relative path and bytes, so a result can be tied to the exact
    arm that produced it. None for the baseline."""
    if arm_dir is None:
        return None
    h = hashlib.sha256()
    for src, rel in _files(Path(arm_dir)):
        h.update(rel.encode() + b"\0" + src.read_bytes() + b"\0")
    return h.hexdigest()


def discover(arms_dir: str | Path | None) -> list[dict]:
    """The baseline plus one arm per immediate subfolder of `arms_dir`, sorted by name."""
    arms = [{"name": BASELINE, "dir": None, "control_type": "none (nothing installed)",
             "description": None, "files": 0, "fingerprint": None}]
    if arms_dir is None:
        return arms
    root = Path(arms_dir)
    if not root.is_dir():
        raise ValueError(f"--arms {root}: not a directory")
    for sub in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if sub.name == BASELINE:
            raise ValueError(f"{sub}: '{BASELINE}' is the implicit empty arm; rename this folder")
        if not ARM_NAME.match(sub.name):
            raise ValueError(f"{sub}: arm names may use letters, digits, '.', '_' and '-'")
        label = read_label(sub)
        arms.append({"name": sub.name, "dir": str(sub), **label,
                     "files": len(_files(sub)), "fingerprint": fingerprint(sub)})
    return arms
