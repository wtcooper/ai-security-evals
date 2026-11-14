#!/usr/bin/env python3
"""Append to and validate evidence.jsonl, the evidence log of a review. Stdlib only.

    python scripts/evidence.py append   --file evidence.jsonl --claim "..." --threats a,b \\
                                        --source https://... --provenance published --note "..."
    python scripts/evidence.py append   ... --absent      # what you looked for and did not find
    python scripts/evidence.py from-weights weights.json --file evidence.jsonl
    python scripts/evidence.py validate evidence.jsonl [--known-threats test-plan.json]
    python scripts/evidence.py summary  evidence.jsonl

One JSON object per line:

  id          E001, E002 ... assigned on append
  claim       what the source says, in one sentence, without upgrading it
  threats     threat ids the claim bears on (the ids used by the review's test plan)
  source      URL the claim was read at; for self_run / reviewed rows a URL or a file path
  captured    YYYY-MM-DD the source was read
  provenance  published | harvested | self_run | reviewed   (see PROVENANCE below)
  note        context a reader needs: the conditions the claim holds under, what it omits
  absent      true when the row records that something was looked for and not found
  kind        optional label (system_card, benchmark_score, weights_scan ...)
  pointer     optional path to the summary or notes the row came from (required for self_run)

This script records evidence. It does not weigh it: no row is scored, ranked or accepted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

PROVENANCE = {
    "published": "stated by the vendor or the benchmark's authors in a document they "
                 "published; read at the source, not checked by you",
    "harvested": "read from a third party or an automated feed (a registry API, a "
                 "leaderboard, an incident database, the press); not checked by you",
    "self_run": "measured by this organisation with a measurement skill; `pointer` names "
                "the experiment summary",
    "reviewed": "a person in this organisation examined a design, configuration, contract "
                "or search result and recorded what they saw",
}
KINDS = ("system_card", "model_card", "benchmark_score", "limitation", "data_handling",
         "hosting", "incident", "research", "weights_scan", "result", "design_review", "other")
REQUIRED = ("id", "claim", "threats", "source", "captured", "provenance", "note")
OPTIONAL = ("absent", "kind", "pointer")
THREAT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROW_ID = re.compile(r"^E(\d+)$")
URL = re.compile(r"^https?://[^\s/]+\S*$")
DEFAULT_WEIGHTS_THREAT = "supply-chain-model"


def today() -> str:
    return dt.date.today().isoformat()


def check_row(row, known_threats: set[str] | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one row."""
    if not isinstance(row, dict):
        return ["row is not a JSON object"], []
    errs, warns = [], []
    for key in REQUIRED:
        if key not in row:
            errs.append(f"missing field {key!r}")
    for key in row:
        if key not in REQUIRED + OPTIONAL:
            errs.append(f"unknown field {key!r}")
    if errs:
        return errs, warns

    if not isinstance(row["id"], str) or not ROW_ID.match(row["id"]):
        errs.append(f"id {row['id']!r} must look like E001")
    if not isinstance(row["claim"], str) or not row["claim"].strip():
        errs.append("claim is empty")
    if not isinstance(row["note"], str):
        errs.append("note must be a string")

    threats = row["threats"]
    if not isinstance(threats, list) or not all(isinstance(t, str) for t in threats):
        errs.append("threats must be a list of threat ids")
    else:
        for t in threats:
            if not THREAT_ID.match(t):
                errs.append(f"threat id {t!r} must be lower-case words joined by hyphens")
            elif known_threats is not None and t not in known_threats:
                errs.append(f"threat id {t!r} is not in the supplied threat list")
        if not threats:
            warns.append("bears on no threat: say which threat this informs, or why none")

    prov = row["provenance"]
    if prov not in PROVENANCE:
        errs.append(f"provenance {prov!r} must be one of {sorted(PROVENANCE)}")
    source = row["source"]
    if not isinstance(source, str) or not source.strip():
        errs.append("source is empty")
    elif prov in ("published", "harvested") and not URL.match(source):
        errs.append(f"source must be an http(s) URL for provenance {prov!r}")
    if prov == "self_run" and not row.get("pointer"):
        errs.append("self_run rows need `pointer`: the experiment summary the claim came from")

    try:
        captured = dt.date.fromisoformat(row["captured"])
    except (TypeError, ValueError):
        errs.append(f"captured {row['captured']!r} is not a YYYY-MM-DD date")
    else:
        if captured > dt.date.today():
            errs.append(f"captured {row['captured']} is in the future")

    absent = row.get("absent", False)
    if not isinstance(absent, bool):
        errs.append("absent must be true or false")
    elif absent and isinstance(row["note"], str) and not row["note"].strip():
        errs.append("an absent row needs a note saying where you looked")
    if "kind" in row and row["kind"] not in KINDS:
        errs.append(f"kind {row['kind']!r} must be one of {list(KINDS)}")
    if "pointer" in row and row["pointer"] is not None and not isinstance(row["pointer"], str):
        errs.append("pointer must be a string")
    return errs, warns


def read_rows(path: Path) -> tuple[list[dict], list[str]]:
    """Rows of an evidence file plus parse errors. A missing file is an empty log."""
    rows, errs = [], []
    if not path.exists():
        return rows, errs
    for n, line in enumerate(path.read_text().split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            errs.append(f"line {n}: not JSON ({exc})")
            continue
        rows.append(row)
    return rows, errs


def validate_file(path: Path, known_threats: set[str] | None = None) -> dict:
    rows, errs = read_rows(path)
    warns: list[str] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, 1):
        label = row.get("id", f"row {n}") if isinstance(row, dict) else f"row {n}"
        row_errs, row_warns = check_row(row, known_threats)
        errs += [f"{label}: {e}" for e in row_errs]
        warns += [f"{label}: {w}" for w in row_warns]
        if isinstance(row, dict) and row.get("id") in seen:
            errs.append(f"{label}: duplicate id")
        if isinstance(row, dict):
            seen.add(row.get("id"))
    return {"rows": len(rows), "errors": errs, "warnings": warns}


def next_id(rows: list[dict]) -> str:
    numbers = [int(m.group(1)) for r in rows if isinstance(r, dict)
               for m in [ROW_ID.match(str(r.get("id", "")))] if m]
    return f"E{max(numbers, default=0) + 1:03d}"


def append_rows(path: Path, new_rows: list[dict],
                known_threats: set[str] | None = None) -> list[dict]:
    """Assign ids, validate, append. Nothing is written if any new row is invalid."""
    existing, parse_errs = read_rows(path)
    if parse_errs:
        raise ValueError(f"{path} has unreadable lines; fix them first: {parse_errs}")
    out = []
    for row in new_rows:
        row = {"id": next_id(existing + out), **{k: v for k, v in row.items() if k != "id"}}
        errs, _ = check_row(row, known_threats)
        if errs:
            raise ValueError(f"row not appended ({row['claim'][:60]!r}): " + "; ".join(errs))
        out.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for row in out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    return out


def load_known_threats(path: str | None) -> set[str] | None:
    """Threat ids from a JSON file: a list of ids, a list of {id} or {threat} objects, or an
    object holding such a list under `threats`. A review's test-plan.json fits."""
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    items = data.get("threats", []) if isinstance(data, dict) else data
    ids = set()
    for item in items:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict):
            ids.add(item.get("id") or item.get("threat"))
    ids.discard(None)
    if not ids:
        raise ValueError(f"no threat ids found in {path}")
    return ids


# --- open-weights harvest -> evidence rows ------------------------------------------------

def weights_rows(result: dict, threat: str = DEFAULT_WEIGHTS_THREAT,
                 captured: str | None = None) -> list[dict]:
    """Evidence rows from the JSON weights_scan.py writes. `unscanned` and `error` become
    ABSENT rows: nothing was established, and that is the finding."""
    repo, rev = result.get("repo", "?"), result.get("revision", "main")
    where = f"{repo}@{rev}"
    base = {"threats": [threat], "source": f"https://huggingface.co/{repo}/tree/{rev}",
            "captured": captured or today(), "provenance": "harvested", "kind": "weights_scan"}
    verdict = result.get("verdict")
    n = result.get("weight_files", 0)
    coverage = result.get("scanner_coverage") or {}
    looked = ", ".join(f"{k} {v}/{n}" for k, v in sorted(coverage.items())) or "none reported"
    rows = []
    if verdict == "clean":
        rows.append({**base, "absent": False,
                     "claim": f"The scanners Hugging Face runs report no issue in the {n} weight "
                              f"file(s) of {where}.",
                     "note": f"Weight files each scanner looked at: {looked}. A clean scan means "
                             "the scanners that ran found nothing. It does not show the weights "
                             "are free of a backdoor or safe in every loader."})
    elif verdict == "unsafe":
        files = ", ".join(result.get("unsafe_files") or []) or "(not listed)"
        rows.append({**base, "absent": False,
                     "claim": f"The scanners Hugging Face runs flag file(s) in {where} as unsafe: "
                              f"{files}.",
                     "note": f"Weight files each scanner looked at: {looked}. Read the scanner "
                             "messages on the repository page before loading anything."})
    elif verdict == "unscanned":
        missing = result.get("unscanned_weight_files") or []
        if not n:
            why = "no weight files with a scan status were found"
        elif missing:
            why = f"{len(missing)} of {n} weight file(s) have no scanner verdict"
        else:
            why = "the Hub does not report its scans as finished"
        rows.append({**base, "absent": True,
                     "claim": f"No complete scan result exists for {where}: {why}.",
                     "note": f"Unscanned is not clean. Weight files each scanner looked at: "
                             f"{looked}."
                             + (f" Files with no verdict: {', '.join(missing)}." if missing else "")})
    else:
        rows.append({**base, "absent": True,
                     "claim": f"The scan status of {where} could not be read.",
                     "note": f"{result.get('error') or 'no verdict in the harvest output'}. "
                             "Nothing is known about these weights from this source."})
    if result.get("pickle_only"):
        files = ", ".join(result.get("pickle_format_files") or [])
        rows.append({**base, "absent": False,
                     "claim": f"{where} ships its weights only in pickle-based formats, which can "
                              "execute code when loaded; no safetensors or GGUF file is offered.",
                     "note": f"Files: {files}. This holds whatever the scanners report."})
    return rows


# --- summary --------------------------------------------------------------------------------

def summarize(rows: list[dict]) -> str:
    lines = [f"{len(rows)} evidence row(s)"]
    for prov in PROVENANCE:
        count = sum(1 for r in rows if r.get("provenance") == prov)
        lines.append(f"  {prov:<10} {count:>3}  {PROVENANCE[prov]}")
    absent = [r for r in rows if r.get("absent")]
    lines.append(f"absent ({len(absent)}) — looked for and not found:")
    lines += [f"  - {r['id']}: {r['claim']}" for r in absent] or ["  - none recorded"]
    by_threat: dict[str, set] = {}
    for r in rows:
        if r.get("absent"):
            continue
        for t in r.get("threats", []):
            by_threat.setdefault(t, set()).add(r.get("provenance"))
    unchecked = sorted(t for t, provs in by_threat.items()
                       if not provs & {"self_run", "reviewed"})
    lines.append(f"threats whose only evidence was not checked by you ({len(unchecked)}):")
    lines += [f"  - {t}" for t in unchecked] or ["  - none"]
    return "\n".join(lines)


# --- CLI --------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("append", help="validate one row and append it")
    a.add_argument("--file", default="evidence.jsonl")
    a.add_argument("--claim", required=True)
    a.add_argument("--threats", default="", help="comma-separated threat ids")
    a.add_argument("--source", required=True)
    a.add_argument("--provenance", required=True, choices=sorted(PROVENANCE))
    a.add_argument("--note", default="")
    a.add_argument("--captured", default=None, help="YYYY-MM-DD (default: today)")
    a.add_argument("--kind", choices=KINDS)
    a.add_argument("--pointer")
    a.add_argument("--absent", action="store_true",
                   help="the row records something looked for and not found")
    a.add_argument("--known-threats", help="JSON file of threat ids to check against")

    w = sub.add_parser("from-weights", help="turn weights_scan.py output into evidence rows")
    w.add_argument("weights_json")
    w.add_argument("--file", default="evidence.jsonl")
    w.add_argument("--threat", default=DEFAULT_WEIGHTS_THREAT)
    w.add_argument("--captured", default=None)

    v = sub.add_parser("validate", help="check every row; exit 1 on any error")
    v.add_argument("file")
    v.add_argument("--known-threats", help="JSON file of threat ids to check against")

    s = sub.add_parser("summary", help="counts by provenance, absent rows, unchecked threats")
    s.add_argument("file")

    args = p.parse_args(argv)
    try:
        if args.cmd == "append":
            row = {"claim": args.claim,
                   "threats": [t.strip() for t in args.threats.split(",") if t.strip()],
                   "source": args.source, "captured": args.captured or today(),
                   "provenance": args.provenance, "note": args.note, "absent": args.absent}
            if args.kind:
                row["kind"] = args.kind
            if args.pointer:
                row["pointer"] = args.pointer
            done = append_rows(Path(args.file), [row], load_known_threats(args.known_threats))
            print(f"appended {done[0]['id']} to {args.file}")
            return 0
        if args.cmd == "from-weights":
            result = json.loads(Path(args.weights_json).read_text())
            done = append_rows(Path(args.file), weights_rows(result, args.threat, args.captured))
            for row in done:
                print(f"appended {row['id']}{' (absent)' if row.get('absent') else ''}: "
                      f"{row['claim']}")
            return 0
        if args.cmd == "validate":
            result = validate_file(Path(args.file), load_known_threats(args.known_threats))
            for e in result["errors"]:
                print("ERROR", e)
            for wmsg in result["warnings"]:
                print("warn ", wmsg)
            print(f"{result['rows']} row(s), {len(result['errors'])} error(s), "
                  f"{len(result['warnings'])} warning(s)")
            return 1 if result["errors"] else 0
        rows, errs = read_rows(Path(args.file))
        if errs:
            print("\n".join(errs), file=sys.stderr)
            return 1
        print(summarize(rows))
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
