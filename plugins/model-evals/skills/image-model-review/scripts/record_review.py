#!/usr/bin/env python3
"""Assemble the image-model review record: what the vendor publishes, what was probed, what
the provenance check found, and every threat that was not assessed.

  python scripts/record_review.py answers.json --out REVIEW_DIR

`answers.json` is the reviewer's harvest (see examples/review_answers.example.json and
references/evidence-harvest.md). The script also reads REVIEW_DIR/probe_summary.json and
REVIEW_DIR/provenance.json when record_probes.py and provenance_check.py have written them.

Written to REVIEW_DIR: image_review.json, image_review.md, and rows appended to
evidence.jsonl. A harvest item marked `absent` becomes an evidence row with `absent: true`,
and so does every threat with nothing recorded against it. The decision block is written empty: people fill it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lib"))
import _evidence  # noqa: E402
from evalkit import CONTEXT_KEYS  # noqa: E402

SCHEMA = "image-model-review/record/1"
TEMPLATE = HERE.parent / "templates" / "threats.json"
HARVEST_STATUS = ("found", "absent", "not_checked")
NO_BENCHMARK = ("No standardized benchmark was found for the security concerns of image "
                "generation (search dated 2026-11-14, see references/threats.md). Probe counts in "
                "this record come from a hand-built set and are not comparable across reviews.")
EMPTY_DECISION = {"decision": None, "decided_by": None, "decided_on": None, "conditions": None,
                  "note": "Left for the organisation to fill. This skill records evidence and "
                          "does not recommend an outcome."}


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.is_file() else None


def build(answers: dict, template: dict, probes: dict | None, provenance: dict | None,
          date: str, pointer: str = "image_review.json") -> tuple[dict, list[dict]]:
    """Returns (record, evidence rows for the harvest and for what was not assessed)."""
    items = {h["id"]: h for h in template["harvest_items"]}
    threats = {t["id"]: t for t in template["threats"]}
    rows: list[dict] = []

    harvest_by_threat: dict[str, list[dict]] = {t: [] for t in threats}
    seen_items = set()
    for h in answers.get("harvest", []):
        item, status = h.get("item"), h.get("status", "not_checked")
        if item not in items:
            raise ValueError(f"harvest item {item!r} is not in the template ({sorted(items)})")
        if status not in HARVEST_STATUS:
            raise ValueError(f"harvest {item}: status must be one of {HARVEST_STATUS}")
        if status == "not_checked":
            continue
        seen_items.add(item)
        ids = items[item]["threats"]
        captured = h.get("captured") or date
        if status == "found":
            if not h.get("claim") or not h.get("source"):
                raise ValueError(f"harvest {item}: a found item needs a claim and a source")
            general = "" if ids else " Bears on no single threat: it describes the vendor's material as a whole."
            r = _evidence.row(h["claim"], ids, h["source"], h.get("provenance", "published"),
                              captured,
                              f"{item} {items[item]['title']}. {h.get('note', '')}".strip() + general,
                              kind=h.get("kind"))
        else:
            looked = h.get("source") or "(the reviewer did not say where they looked)"
            r = _evidence.row(f"Not found in the vendor's published material: {items[item]['title']}.",
                              ids, looked, "reviewed", captured,
                              f"{item}. Looked at: {looked}. {h.get('note', '')}".strip(),
                              absent=True)
        rows.append(r)
        for t in ids:
            harvest_by_threat[t].append({"item": item, "status": status, "claim": r["claim"],
                                         "source": r["source"]})

    reviewed_by_threat: dict[str, list[dict]] = {t: [] for t in threats}
    for rv in answers.get("reviewed", []):
        unknown = [t for t in rv.get("threat_ids", []) if t not in threats]
        if unknown:
            raise ValueError(f"reviewed entry names unknown threat id(s) {unknown}")
        r = _evidence.row(rv["claim"], rv["threat_ids"], rv.get("source") or "reviewer statement",
                          rv.get("provenance", "reviewed"), rv.get("captured") or date,
                          rv.get("note", ""), kind=rv.get("kind", "design_review"),
                          pointer=rv.get("pointer"))
        rows.append(r)
        for t in rv["threat_ids"]:
            reviewed_by_threat[t].append({"claim": r["claim"], "source": r["source"]})

    not_applicable = answers.get("not_applicable", {})
    for tid, reason in not_applicable.items():
        if tid not in threats:
            raise ValueError(f"not_applicable names unknown threat id {tid!r}")
        if not str(reason).strip():
            raise ValueError(f"not_applicable {tid}: give the reason")

    prov = provenance["summary"] if provenance else None
    out_threats, not_assessed = [], []
    for tid, t in threats.items():
        groups = [g for g in (probes or {}).get("groups", [])
                  if tid in g["threat_ids"] and g["n"] > 0]
        check = None
        if prov and tid == "img-07":
            check = {"as_delivered": prov["original"]}
        if prov and tid == "img-08":
            done = {k: v for k, v in {**prov["after_transform"], **prov["after_pipeline"]}.items()
                    if v["n"]}
            check = {"after": done} if done else None
        found = [h for h in harvest_by_threat[tid] if h["status"] == "found"]
        assessed_by = [name for name, hit in (
            ("vendor_evidence", found), ("probes", groups), ("provenance_check", check),
            ("reviewer_note", reviewed_by_threat[tid])) if hit]
        if tid in not_applicable:
            status = "not_applicable"
        elif assessed_by:
            status = "evidence_recorded"
        else:
            status = "not_assessed"
            not_assessed.append(tid)
        entry = {"id": tid, "title": t["title"], "atlas": t["atlas"], "owasp_llm": t["owasp_llm"],
                 "status": status, "assessed_by": assessed_by,
                 "vendor_evidence": harvest_by_threat[tid],
                 "probes": [{k: g[k] for k in ("category", "kind", "n", "produced", "partial",
                                               "blocked", "errors", "validity_flags")}
                            for g in groups],
                 "provenance_check": check, "reviewer_notes": reviewed_by_threat[tid]}
        if status == "not_applicable":
            entry["reason"] = not_applicable[tid]
        if status == "not_assessed":
            absent = [h["item"] for h in harvest_by_threat[tid] if h["status"] == "absent"]
            entry["reason"] = ("no vendor evidence found" + (f" ({', '.join(absent)} looked for "
                               "and absent)" if absent else "") + ", no probes recorded, no check run")
            rows.append(_evidence.row(f"Not assessed: {tid} {t['title']}.", [tid], pointer,
                                      "reviewed", date, f"Nothing was established: {entry['reason']}.",
                                      absent=True, kind="other", pointer=pointer))
        out_threats.append(entry)

    ctx = answers.get("context", {})
    record = {
        "schema": SCHEMA, "date": date, "subject": answers.get("subject", {}),
        "reviewer": answers.get("reviewer"),
        "context": {k: ctx[k] for k in CONTEXT_KEYS if ctx.get(k) is not None},
        "threats": out_threats, "not_assessed": not_assessed,
        "not_applicable": not_applicable,
        "vendor_evidence_absent": sorted({h["item"] for h in answers.get("harvest", [])
                                          if h.get("status") == "absent"}),
        "harvest_not_checked": sorted(set(items) - seen_items),
        "provenance_cannot_detect": provenance["cannot_detect"] if provenance else None,
        "inputs": {"probe_summary": bool(probes), "provenance_check": bool(provenance)},
        "no_standardized_benchmark": NO_BENCHMARK,
        "decision": dict(EMPTY_DECISION),
    }
    return record, rows


def _rate(x: dict, n: int) -> str:
    if not n or x.get("rate") is None:
        return "none counted"
    return (f"{x.get('count', x.get('present'))} of {n} ({100 * x['rate']:.0f}%, 95% CI "
            f"{100 * x['ci95'][0]:.0f}-{100 * x['ci95'][1]:.0f}%)")


def render(record: dict, template: dict) -> str:
    items = {h["id"]: h["title"] for h in template["harvest_items"]}
    s = record["subject"]
    lines = [f"# Image model review — {s.get('vendor', '?')} {s.get('model', '?')} "
             f"{s.get('version', '')}".rstrip(), "",
             f"Date: {record['date']} · Reviewer: {record['reviewer'] or '(not given)'} · "
             f"Surfaces: {', '.join(s.get('surfaces', [])) or '(not given)'}", "",
             record["no_standardized_benchmark"], ""]
    if record["context"]:
        lines += ["## Deployment context", ""] + [f"- {k}: {v}" for k, v in record["context"].items()] + [""]
    lines += ["## Threats", "", "| Id | Threat | Status | Recorded from |", "|---|---|---|---|"]
    for t in record["threats"]:
        lines.append(f"| {t['id']} | {t['title']} | {t['status']} | "
                     f"{', '.join(t['assessed_by']) or '-'} |")
    lines += ["", "## Not assessed", ""]
    lines += [f"- {t['id']} {t['title']}: {t['reason']}" for t in record["threats"]
              if t["status"] == "not_assessed"] or ["- none"]
    if record["not_applicable"]:
        lines += ["", "Marked not applicable by the reviewer:"]
        lines += [f"- {k}: {v}" for k, v in record["not_applicable"].items()]
    lines += ["", "Vendor material looked for and not found: "
              + ("; ".join(f"{i} {items[i]}" for i in record["vendor_evidence_absent"]) or "none"),
              "Harvest items not checked: "
              + ("; ".join(f"{i} {items[i]}" for i in record["harvest_not_checked"]) or "none")]
    if not record["inputs"]["probe_summary"]:
        lines.append("No probe outcomes were recorded (record_probes.py was not run).")
    if not record["inputs"]["provenance_check"]:
        lines.append("No provenance check was run (provenance_check.py was not run).")
    if record["provenance_cannot_detect"]:
        lines += ["", "The provenance check does not detect:"]
        lines += [f"- {c}" for c in record["provenance_cannot_detect"]]
    lines += ["", "## Detail", ""]
    for t in record["threats"]:
        if t["status"] != "evidence_recorded":
            continue
        ids = ", ".join(t["atlas"] + t["owasp_llm"])
        lines.append(f"### {t['id']} {t['title']}" + (f" ({ids})" if ids else ""))
        for h in t["vendor_evidence"]:
            lines.append(f"- vendor, {h['item']} {h['status']}: {h['claim']} [{h['source']}]")
        for g in t["probes"]:
            flags = "".join(f" (validity flag {f['flag']}: n under {f['limit']})"
                            for f in g["validity_flags"])
            key = "blocked" if g["kind"] == "benign" else "produced"
            lines.append(f"- probes, {g['category']} ({g['kind']}): {key} {_rate(g[key], g['n'])}"
                         f"{flags}")
        if t["provenance_check"]:
            for name, r in (t["provenance_check"].get("after") or {}).items():
                lines.append(f"- provenance check, after {name}: still present in {_rate(r, r['n'])}")
            if "as_delivered" in t["provenance_check"]:
                r = t["provenance_check"]["as_delivered"]
                lines.append(f"- provenance check, as delivered: embedded C2PA manifest store "
                             f"present in {_rate(r, r['n'])}")
        for n in t["reviewer_notes"]:
            lines.append(f"- reviewer: {n['claim']} [{n['source']}]")
        lines.append("")
    lines += ["## Decision", "", "Left for the organisation. Not filled by this skill.", "",
              "- Decision:", "- Decided by:", "- Date:", "- Conditions:", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("answers", help="the reviewer's harvest answers (JSON)")
    ap.add_argument("--out", required=True, help="review folder")
    ap.add_argument("--probes", help="probe_summary.json (default OUT/probe_summary.json)")
    ap.add_argument("--provenance", help="provenance.json (default OUT/provenance.json)")
    ap.add_argument("--evidence", help="evidence.jsonl to append to (default OUT/evidence.jsonl)")
    ap.add_argument("--threat-map", help="JSON mapping this skill's threat ids to the ids of "
                                         "the review's test plan")
    ap.add_argument("--date", default=None, help="review date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    template = json.loads(TEMPLATE.read_text())
    answers = json.loads(Path(args.answers).read_text())
    date = args.date or answers.get("date") or _evidence.today()
    try:
        record, rows = build(answers, template,
                             _load(Path(args.probes) if args.probes else out / "probe_summary.json"),
                             _load(Path(args.provenance) if args.provenance else out / "provenance.json"),
                             date, str(out / "image_review.json"))
    except (ValueError, KeyError) as exc:
        ap.error(f"{args.answers}: {exc}")
    (out / "image_review.json").write_text(json.dumps(record, indent=2) + "\n")
    (out / "image_review.md").write_text(render(record, template))
    path = Path(args.evidence) if args.evidence else out / "evidence.jsonl"
    added = _evidence.append(path, rows, _evidence.load_threat_map(args.threat_map))
    counts = {s: sum(t["status"] == s for t in record["threats"])
              for s in ("evidence_recorded", "not_assessed", "not_applicable")}
    print(f"threats: {counts['evidence_recorded']} with evidence recorded, "
          f"{counts['not_assessed']} not assessed, {counts['not_applicable']} not applicable")
    for t in record["threats"]:
        if t["status"] == "not_assessed":
            print(f"  NOT ASSESSED {t['id']} {t['title']}: {t['reason']}")
    print(f"vendor material looked for and absent: "
          f"{', '.join(record['vendor_evidence_absent']) or 'none'}")
    print(f"harvest items not checked: {', '.join(record['harvest_not_checked']) or 'none'}")
    print(f"evidence: {added} new row(s) in {path}")
    print(f"wrote {out / 'image_review.json'} and {out / 'image_review.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
