#!/usr/bin/env python3
"""Tiny manifest.json / samples.jsonl editor used by every harness script (stdlib only).

  manifest.py <EXP> set model.id claude-sonnet-5          # dotted path, JSON-parsed value if valid
  manifest.py <EXP> set k 10
  manifest.py <EXP> add cost.usd 1.23                     # numeric accumulate (creates if missing)
  manifest.py <EXP> append scorers '{"name":"codeql"}'    # append to a list (creates if missing)
  manifest.py <EXP> append-sample '{"arm":"A","sample":1,...}'   # -> <EXP>/samples.jsonl (upsert on arm+target+sample)
  manifest.py <EXP> todo-clear model.id                    # remove from _todo
  manifest.py <EXP> get model.id

<EXP> is the experiment folder (or a path to manifest.json). Values are parsed as JSON when
possible, else kept as strings. Every write also drops the key from `_todo`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _mpath(exp: str) -> Path:
    p = Path(exp)
    return p if p.name == "manifest.json" else p / "manifest.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {}


def _save(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")


def _parse(v: str):
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return v


def _walk(doc: dict, dotted: str, create: bool):
    parts = dotted.split(".")
    cur = doc
    for k in parts[:-1]:
        if k not in cur or not isinstance(cur[k], (dict, list)):
            if not create:
                return None, None
            cur[k] = {}
        cur = cur[k]
        if isinstance(cur, list):
            raise SystemExit(f"cannot descend into list at {k}")
    return cur, parts[-1]


def get(doc: dict, dotted: str):
    cur, leaf = _walk(doc, dotted, create=False)
    return None if cur is None else cur.get(leaf)


def set_(doc: dict, dotted: str, value) -> None:
    cur, leaf = _walk(doc, dotted, create=True)
    cur[leaf] = value
    todo_clear(doc, dotted)


def add(doc: dict, dotted: str, value) -> None:
    cur, leaf = _walk(doc, dotted, create=True)
    cur[leaf] = (cur.get(leaf) or 0) + value
    todo_clear(doc, dotted)


def append(doc: dict, dotted: str, value) -> None:
    cur, leaf = _walk(doc, dotted, create=True)
    if not isinstance(cur.get(leaf), list):
        cur[leaf] = []
    cur[leaf].append(value)
    todo_clear(doc, dotted)


def todo_clear(doc: dict, dotted: str) -> None:
    if isinstance(doc.get("_todo"), list) and dotted in doc["_todo"]:
        doc["_todo"].remove(dotted)


def append_sample(exp: Path, row: dict) -> Path:
    """Upsert into <EXP>/samples.jsonl on (arm, target, sample); merges keys."""
    p = exp / "samples.jsonl"
    rows = []
    if p.exists():
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    key = (row.get("arm"), row.get("target"), row.get("sample"))
    for r in rows:
        if (r.get("arm"), r.get("target"), r.get("sample")) == key:
            r.update(row)
            break
    else:
        rows.append(row)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    exp, cmd, args = argv[1], argv[2], argv[3:]
    mp = _mpath(exp)
    if cmd == "append-sample":
        row = _parse(args[0])
        if not isinstance(row, dict):
            raise SystemExit("append-sample needs a JSON object")
        print(append_sample(mp.parent, row))
        return 0
    doc = _load(mp)
    if cmd == "get":
        v = get(doc, args[0])
        print(json.dumps(v) if not isinstance(v, str) else v)
        return 0
    if cmd == "set":
        set_(doc, args[0], _parse(args[1]))
    elif cmd == "add":
        v = _parse(args[1])
        if not isinstance(v, (int, float)):
            raise SystemExit("add needs a number")
        add(doc, args[0], v)
    elif cmd == "append":
        append(doc, args[0], _parse(args[1]))
    elif cmd == "todo-clear":
        todo_clear(doc, args[0])
    else:
        raise SystemExit(f"unknown command {cmd}")
    _save(mp, doc)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
