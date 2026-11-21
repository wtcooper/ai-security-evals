#!/usr/bin/env python3
"""Record what the vendor publishes about this model, before anything is run.

  python scripts/record_harvest.py answers.json --out EXP [--evidence PATH] [--threat-map MAP]

`answers.json` holds one entry per harvest item (templates/harvest.json, explained in
references/evidence-harvest.md): `found` with a claim and a URL, `absent` with where you
looked, or `not_checked`. Writes EXP/harvest.md and EXP/harvest.json, and appends one
evidence row per found or absent item to evidence.jsonl (the review-evidence format). An
absent item is a finding, not a gap: it becomes a row with `absent: true`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _evidence  # noqa: E402

TEMPLATE = HERE.parent / "templates" / "harvest.json"
STATUS = ("found", "absent", "not_checked")


def build(answers: dict, template: dict, date: str) -> tuple[dict, list[dict]]:
    items = {h["id"]: h for h in template["items"]}
    rows, recorded = [], {}
    for h in answers.get("harvest", []):
        item, status = h.get("item"), h.get("status", "not_checked")
        if item not in items:
            raise ValueError(f"harvest item {item!r} is not in the template ({sorted(items)})")
        if status not in STATUS:
            raise ValueError(f"harvest {item}: status must be one of {STATUS}")
        if status == "not_checked":
            continue
        ids, title = items[item]["threats"], items[item]["title"]
        captured = h.get("captured") or date
        if status == "found":
            if not h.get("claim") or not h.get("source"):
                raise ValueError(f"harvest {item}: a found item needs a claim and a source")
            r = _evidence.row(h["claim"], ids, h["source"], h.get("provenance", "published"),
                              captured, f"{item} {title}. {h.get('note', '')}".strip(),
                              kind=h.get("kind"))
        else:
            looked = h.get("source") or "(where you looked was not given)"
            r = _evidence.row(f"Not found in the vendor's published material: {title}.", ids,
                              looked, "reviewed", captured,
                              f"{item}. Looked at: {looked}. {h.get('note', '')}".strip(), absent=True)
        rows.append(r)
        recorded[item] = {"status": status, "claim": r["claim"], "source": r["source"]}
    record = {"schema": template["schema"], "date": date, "subject": answers.get("subject", {}),
              "items": [{"id": i, "title": items[i]["title"], "threats": items[i]["threats"],
                         "bears_on": ", ".join(items[i]["threats"]) or items[i].get("bears_on", ""),
                         **recorded.get(i, {"status": "not_checked"})} for i in items]}
    return record, rows


def render(record: dict) -> str:
    s = record["subject"]
    lines = [f"# Vendor evidence — {s.get('vendor', '?')} {s.get('model', '?')} {s.get('version', '')}".rstrip(),
             "", f"Harvested {record['date']}. What the vendor publishes, in its own terms; nothing "
             "here was measured by this skill.", "",
             "| Item | Status | Bears on | Claim or where looked |", "|---|---|---|---|"]
    for i in record["items"]:
        detail = (f"{i['claim']} [{i['source']}]" if i["status"] == "found"
                  else f"looked at {i['source']}" if i["status"] == "absent" else "nobody looked")
        lines.append(f"| {i['id']} {i['title']} | {i['status']} | "
                     f"{i['bears_on']} | {detail} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("answers")
    ap.add_argument("--out", required=True, help="experiment or review folder")
    ap.add_argument("--evidence", help="evidence.jsonl to append to (default OUT/evidence.jsonl)")
    ap.add_argument("--threat-map", help="JSON mapping this skill's threat ids to a test plan's ids")
    ap.add_argument("--date", help="harvest date YYYY-MM-DD (default: the answers' date, then today)")
    args = ap.parse_args(argv)
    answers = json.loads(Path(args.answers).read_text())
    date = args.date or answers.get("date") or _evidence.today()
    try:
        record, rows = build(answers, json.loads(TEMPLATE.read_text()), date)
    except ValueError as exc:
        ap.error(f"{args.answers}: {exc}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "harvest.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "harvest.md").write_text(render(record))
    path = Path(args.evidence) if args.evidence else out / "evidence.jsonl"
    added = _evidence.append(path, rows, _evidence.load_threat_map(args.threat_map))
    counts = {k: sum(i["status"] == k for i in record["items"]) for k in STATUS}
    print(f"harvest: {counts['found']} found, {counts['absent']} absent, "
          f"{counts['not_checked']} not checked; evidence: {added} new row(s) in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
