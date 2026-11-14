"""Write rows to a review's evidence.jsonl.

The row format belongs to the review-evidence skill; this module writes rows that its
validator accepts and nothing more. One JSON object per line:

  id          E001, E002 ... assigned here on append, continuing from the file
  claim       one sentence stating what was observed or published
  threats     threat ids the claim bears on, lower-case words joined by hyphens
  source      a URL; for self_run and reviewed rows a URL or a file path
  captured    YYYY-MM-DD
  provenance  published | harvested | self_run | reviewed
  note        the conditions the claim holds under and what it leaves out
  absent      true when the row records that something was looked for and not found, or
              that nothing was established
  kind        optional label
  pointer     path to the file the row came from (required for self_run)

published = the vendor's or authors' own document; harvested = a third party or a feed;
self_run = measured by this organisation; reviewed = a person here examined something and
recorded what they saw.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

REQUIRED = ("id", "claim", "threats", "source", "captured", "provenance", "note")
OPTIONAL = ("absent", "kind", "pointer")
PROVENANCE = ("published", "harvested", "self_run", "reviewed")
KINDS = ("system_card", "model_card", "benchmark_score", "limitation", "data_handling",
         "hosting", "incident", "research", "weights_scan", "result", "design_review", "other")
_THREAT = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROW_ID = re.compile(r"^E(\d+)$")
_URL = re.compile(r"^https?://[^\s/]+\S*$")


def today() -> str:
    return _dt.date.today().isoformat()


def row(claim: str, threats: list[str], source: str, provenance: str,
        captured: str | None = None, note: str = "", absent: bool = False,
        kind: str | None = None, pointer: str | None = None) -> dict:
    """A row without its id (append assigns one). Raises ValueError if it would not validate."""
    out = {"claim": " ".join(str(claim).split()), "threats": list(threats),
           "source": str(source), "captured": captured or today(),
           "provenance": provenance, "note": " ".join(str(note or "").split()),
           "absent": bool(absent)}
    if kind:
        out["kind"] = kind
    if pointer:
        out["pointer"] = str(pointer)
    problems = check(out)
    if problems:
        raise ValueError(f"evidence row ({out['claim'][:50]!r}): " + "; ".join(problems))
    return out


def check(r: dict) -> list[str]:
    """Problems with a row, id aside. The same rules the review-evidence validator applies."""
    errs = [f"unknown field {k!r}" for k in r if k not in REQUIRED + OPTIONAL]
    errs += [f"missing field {k!r}" for k in REQUIRED if k != "id" and k not in r]
    if errs:
        return errs
    if not r["claim"].strip():
        errs.append("claim is empty")
    for t in r["threats"]:
        if not isinstance(t, str) or not _THREAT.match(t):
            errs.append(f"threat id {t!r} must be lower-case words joined by hyphens")
    if r["provenance"] not in PROVENANCE:
        errs.append(f"provenance {r['provenance']!r} must be one of {PROVENANCE}")
    if not r["source"].strip():
        errs.append("source is empty")
    elif r["provenance"] in ("published", "harvested") and not _URL.match(r["source"]):
        errs.append(f"source must be an http(s) URL for provenance {r['provenance']!r}; a "
                    "document you hold that has no URL is a `reviewed` row")
    if r["provenance"] == "self_run" and not r.get("pointer"):
        errs.append("self_run rows need `pointer`")
    try:
        if _dt.date.fromisoformat(r["captured"]) > _dt.date.today():
            errs.append(f"captured {r['captured']} is in the future")
    except (TypeError, ValueError):
        errs.append(f"captured {r['captured']!r} is not a YYYY-MM-DD date")
    if r.get("absent") and not r["note"].strip():
        errs.append("an absent row needs a note saying where you looked")
    if "kind" in r and r["kind"] not in KINDS:
        errs.append(f"kind {r['kind']!r} must be one of {KINDS}")
    return errs


def apply_threat_map(rows: list[dict], mapping: dict[str, list[str]] | None) -> list[dict]:
    """Translate this skill's threat ids into the ids a review's test plan uses. An id with no
    entry in the mapping is kept as it is."""
    if not mapping:
        return rows
    out = []
    for r in rows:
        ids: list[str] = []
        for t in r["threats"]:
            for m in mapping.get(t, [t]):
                if m not in ids:
                    ids.append(m)
        out.append({**r, "threats": ids})
    return out


def load_threat_map(path: str | None) -> dict[str, list[str]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    return {k: ([v] if isinstance(v, str) else list(v)) for k, v in data.items()
            if not k.startswith("_")}


def read(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(path: str | Path, rows: list[dict],
           threat_map: dict[str, list[str]] | None = None) -> int:
    """Append rows with fresh ids. A row already in the file (same content, any id) is not
    written again, so running a script twice does not double the evidence. Returns rows added."""
    path = Path(path)
    rows = apply_threat_map(rows, threat_map)
    for r in rows:
        problems = check(r)
        if problems:
            raise ValueError(f"evidence row ({r.get('claim', '')[:50]!r}): " + "; ".join(problems))
    existing = read(path)

    def body(r: dict) -> str:
        return json.dumps({k: v for k, v in r.items() if k != "id"}, sort_keys=True)

    seen = {body(r) for r in existing}
    number = max([int(m.group(1)) for r in existing
                  for m in [_ROW_ID.match(str(r.get("id", "")))] if m], default=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with open(path, "a") as fh:
        for r in rows:
            if body(r) in seen:
                continue
            number += 1
            fh.write(json.dumps({"id": f"E{number:03d}", **r}, sort_keys=True) + "\n")
            seen.add(body(r))
            added += 1
    return added
