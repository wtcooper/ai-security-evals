#!/usr/bin/env python3
"""Write the review record for one agent feature from the reviewer's answers.

  python scripts/write_review.py --feature computer-use --blank > answers.json   # a form to fill
  python scripts/write_review.py --feature computer-use --answers answers.json --out REVIEW_DIR

Written to REVIEW_DIR: <feature>_review.json, <feature>_review.md, and rows appended to
evidence.jsonl. Every threat in the feature's template appears in the record with one of:

  evidence_recorded   at least one piece of vendor evidence, test result or reviewer finding
  answers_only        review questions were answered but nothing with a source was recorded
  not_applicable      the reviewer said so and gave the reason
  not_assessed        nothing was supplied

Threats left `not_assessed` or `answers_only` are printed and written as evidence rows.
The record states what was looked at. It gives no rating and no recommendation, and its
decision block is always written empty for people to fill.
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
import templates  # noqa: E402
from evalkit import CONTEXT_KEYS  # noqa: E402

SCHEMA = "agent-feature-review/record/1"
# AWS Agentic AI Security Scoping Matrix (aws.amazon.com/ai/security/agentic-ai-scoping-matrix,
# read 2026-11-14). See references/deployment-context.md.
AWS_SCOPES = {1: "Scope 1: No Agency", 2: "Scope 2: Prescribed Agency",
              3: "Scope 3: Supervised Agency", 4: "Scope 4: Full Agency"}
AWS_DIMENSIONS = {
    "identity_context": "Identity Context",
    "data_memory_state": "Data, Memory & State Protection",
    "audit_logging": "Audit & Logging",
    "agent_llm_controls": "Agent & LLM Controls",
    "agency_perimeters": "Agency Perimeters & Policies",
    "orchestration": "Orchestration",
}
EMPTY_DECISION = {"decision": None, "decided_by": None, "decided_on": None, "conditions": None,
                  "note": "Left for the organisation to fill. This skill records evidence and "
                          "does not recommend an outcome."}
STATUSES = ("evidence_recorded", "answers_only", "not_applicable", "not_assessed")


def blank(feature: str) -> dict:
    """A form for the reviewer: every threat, every question, nothing filled in."""
    t = templates.load(feature)
    return {
        "feature": feature,
        "subject": {"product": "", "vendor": "", "model": "", "feature_version": ""},
        "reviewer": "", "date": "",
        "deployment": {
            "aws_scope": None,
            "agency": "", "autonomy": "", "started_by": "", "human_approval": "",
            "security_dimensions": {k: "" for k in AWS_DIMENSIONS},
            "feature_context": [{"question": q, "answer": ""} for q in t["context_questions"]],
        },
        "context": {k: "" for k in CONTEXT_KEYS},
        "threats": {th["id"]: {
            "_title": th["title"], "applies": True, "reason": "",
            "answers": [{"question": q, "answer": ""} for q in th["questions"]],
            "vendor_evidence": [], "vendor_absent": [], "tests": [], "reviewed": [],
        } for th in t["threats"]},
        "_how_to_fill": {
            "vendor_evidence": {"claim": "what the document says, in one sentence",
                                "source": "https://...", "provenance": "published | harvested",
                                "captured": "YYYY-MM-DD", "note": ""},
            "vendor_absent": {"looked_for": "what you looked for", "source": "where you looked",
                              "note": ""},
            "tests": {"claim": "the result with its interval and what it was run on",
                      "pointer": "path to the summary the number came from",
                      "benchmark": "name", "skill": "the skill that ran it", "note": ""},
            "reviewed": {"claim": "what you examined and saw", "source": "file, system or person",
                         "note": ""},
            "applies": "false needs a reason; a threat is never dropped without one",
        },
    }


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _answers(entry: dict, questions: list[str]) -> list[dict]:
    """Answers aligned to the template's questions. Accepts [{question, answer}] or [str]."""
    given = entry.get("answers") or []
    out = []
    for i, q in enumerate(questions):
        a = given[i] if i < len(given) else ""
        out.append({"question": q, "answer": _clean(a.get("answer") if isinstance(a, dict) else a)})
    return out


def build(feature: str, answers: dict, date: str, pointer: str) -> tuple[dict, list[dict]]:
    """Returns (record, evidence rows). Raises ValueError on answers that cannot be recorded."""
    t, fw, bm = templates.load(feature), templates.frameworks(), templates.benchmarks()
    if answers.get("feature") not in (None, "", feature):
        raise ValueError(f"answers are for feature {answers['feature']!r}, not {feature!r}")
    known = {th["id"] for th in t["threats"]}
    supplied = answers.get("threats") or {}
    unknown = sorted(set(supplied) - known)
    if unknown:
        raise ValueError(f"answers name threat id(s) not in the {feature} template: {unknown}")

    dep = answers.get("deployment") or {}
    scope = dep.get("aws_scope")
    if scope not in (None, "", 1, 2, 3, 4):
        raise ValueError(f"deployment.aws_scope must be 1, 2, 3, 4 or empty, got {scope!r}")
    scope = scope or None
    dims = dep.get("security_dimensions") or {}
    bad = sorted(set(dims) - set(AWS_DIMENSIONS))
    if bad:
        raise ValueError(f"unknown security dimension(s) {bad}; use {list(AWS_DIMENSIONS)}")
    feature_ctx = dep.get("feature_context") or []
    deployment = {
        "aws_scope": scope, "aws_scope_name": AWS_SCOPES.get(scope),
        "agency": _clean(dep.get("agency")), "autonomy": _clean(dep.get("autonomy")),
        "started_by": _clean(dep.get("started_by")),
        "human_approval": _clean(dep.get("human_approval")),
        "security_dimensions": {k: _clean(dims.get(k)) for k in AWS_DIMENSIONS},
        "feature_context": [
            {"question": q,
             "answer": _clean((feature_ctx[i].get("answer") if isinstance(feature_ctx[i], dict)
                               else feature_ctx[i]) if i < len(feature_ctx) else "")}
            for i, q in enumerate(t["context_questions"])],
    }
    context_gaps = [name for name, value in (
        ("AWS scope", scope), ("agency", deployment["agency"]),
        ("autonomy", deployment["autonomy"]), ("what starts a run", deployment["started_by"]),
        ("human approval", deployment["human_approval"])) if not value]
    context_gaps += [f"dimension: {AWS_DIMENSIONS[k]}" for k, v in
                     deployment["security_dimensions"].items() if not v]
    context_gaps += [f"feature question: {c['question']}" for c in deployment["feature_context"]
                     if not c["answer"]]

    rows: list[dict] = []
    threats = []
    for th in t["threats"]:
        tid = th["id"]
        entry = supplied.get(tid) or {}
        qa = _answers(entry, th["questions"])
        answered = sum(bool(a["answer"]) for a in qa)
        evidence = []

        for ev in entry.get("vendor_evidence") or []:
            r = _evidence.row(ev.get("claim", ""), [tid], ev.get("source", ""),
                              ev.get("provenance", "published"), ev.get("captured") or date,
                              ev.get("note", ""), kind=ev.get("kind"))
            rows.append(r)
            evidence.append({"type": "vendor_evidence", "claim": r["claim"], "source": r["source"],
                             "provenance": r["provenance"]})
        absent = []
        for ab in entry.get("vendor_absent") or []:
            looked = _clean(ab.get("source")) or "(the reviewer did not say where they looked)"
            what = _clean(ab.get("looked_for"))
            if not what:
                raise ValueError(f"{tid}: a vendor_absent entry needs `looked_for`")
            r = _evidence.row(f"Not found in the vendor's published material: {what.rstrip('.')}.",
                              [tid], looked, "reviewed", ab.get("captured") or date,
                              f"Looked at: {looked}. {_clean(ab.get('note'))}".strip(), absent=True)
            rows.append(r)
            absent.append({"looked_for": what, "source": looked})
        tested_with = []
        for test in entry.get("tests") or []:
            if not test.get("pointer"):
                raise ValueError(f"{tid}: a test needs `pointer`, the summary the result came from")
            via = " via ".join(x for x in (_clean(test.get("benchmark")), _clean(test.get("skill"))) if x)
            r = _evidence.row(test.get("claim", ""), [tid], test["pointer"], "self_run",
                              test.get("captured") or date,
                              f"{via}. {_clean(test.get('note'))}".strip(". ").strip() or "self-run test",
                              kind="result", pointer=test["pointer"])
            rows.append(r)
            evidence.append({"type": "test", "claim": r["claim"], "source": r["source"],
                             "provenance": "self_run", "benchmark": _clean(test.get("benchmark")),
                             "skill": _clean(test.get("skill"))})
            if test.get("benchmark"):
                tested_with.append(_clean(test["benchmark"]))
        for rv in entry.get("reviewed") or []:
            r = _evidence.row(rv.get("claim", ""), [tid], _clean(rv.get("source")) or "reviewer statement",
                              "reviewed", rv.get("captured") or date, rv.get("note", ""),
                              kind="design_review")
            rows.append(r)
            evidence.append({"type": "reviewed", "claim": r["claim"], "source": r["source"],
                             "provenance": "reviewed"})

        applies = entry.get("applies", True)
        reason = _clean(entry.get("reason"))
        if applies is False and not reason:
            raise ValueError(f"{tid}: `applies` is false but no reason is given")
        if applies is False:
            status = "not_applicable"
        elif evidence:
            status = "evidence_recorded"
        elif answered:
            status = "answers_only"
            reason = (f"{answered} of {len(qa)} review questions answered; no vendor evidence, "
                      "test result or reviewer finding with a source was recorded")
            rows.append(_evidence.row(
                f"Reviewer's answers recorded for {tid} {th['title']} "
                f"({answered} of {len(qa)} questions), with no source cited.",
                [tid], pointer, "reviewed", date,
                "Answers are in the review record. Nothing was measured and no document was cited.",
                kind="design_review", pointer=pointer))
        else:
            status = "not_assessed"
            reason = "no answers and no evidence supplied" + (
                "; vendor material was looked for and not found" if absent else "")
            rows.append(_evidence.row(f"Not assessed: {tid} {th['title']}.", [tid], pointer,
                                      "reviewed", date, f"Nothing was established: {reason}.",
                                      absent=True, kind="other", pointer=pointer))

        names = {k: bm[k]["name"] for k in th["benchmarks"]}
        ran = {k for k, name in names.items()
               if any(x.lower() in (k.lower(), name.lower()) for x in tested_with)}
        threats.append({
            "id": tid, "title": th["title"], "status": status, "reason": reason,
            "owasp_llm": th["owasp_llm"], "owasp_agentic": th["owasp_agentic"], "atlas": th["atlas"],
            "answers": qa, "questions_unanswered": len(qa) - answered,
            "evidence": evidence, "vendor_absent": absent,
            "benchmarks_available": [{"name": names[k], "route": bm[k]["route"],
                                      "run": k in ran} for k in th["benchmarks"]],
            "own_tests_available": th["own_tests"],
            "no_standard_test": th["no_standard_test"],
        })

    ctx = answers.get("context") or {}
    by_status = {s: [x["id"] for x in threats if x["status"] == s] for s in STATUSES}
    record = {
        "schema": SCHEMA, "feature": feature, "feature_title": t["title"], "date": date,
        "subject": answers.get("subject") or {}, "reviewer": answers.get("reviewer") or None,
        "trust_boundary": t["trust_boundary"],
        "deployment": deployment, "deployment_context_missing": context_gaps,
        "context": {k: ctx[k] for k in CONTEXT_KEYS if ctx.get(k)},
        "threats": threats, "by_status": by_status,
        "not_assessed": by_status["not_assessed"], "answers_only": by_status["answers_only"],
        "benchmarks_not_run": sorted({b["name"] for x in threats if x["status"] != "not_applicable"
                                      for b in x["benchmarks_available"] if not b["run"]}),
        "framework_sources": fw["sources"],
        "decision": dict(EMPTY_DECISION),
    }
    return record, rows


def render(record: dict) -> str:
    fw = templates.frameworks()
    s, d = record["subject"], record["deployment"]
    name = " ".join(x for x in (s.get("vendor"), s.get("product"), s.get("feature_version")) if x)
    out = [f"# Agent feature review — {record['feature_title']}", "",
           f"Subject: {name or '(not given)'} · model: {s.get('model') or '(not given)'} · "
           f"date: {record['date']} · reviewer: {record['reviewer'] or '(not given)'}", "",
           "This record states what was examined and what was not. It gives no rating and no "
           "recommendation.", "", "## What the feature changes", ""]
    out += [f"- {line}" for line in record["trust_boundary"]]
    out += ["", "## Deployment context", "",
            f"- Scope (AWS Agentic AI Security Scoping Matrix): "
            f"{d['aws_scope_name'] or 'not recorded'}",
            f"- Agency (what it is permitted and enabled to do): {d['agency'] or 'not recorded'}",
            f"- Autonomy (how far it acts without a person): {d['autonomy'] or 'not recorded'}",
            f"- What starts a run: {d['started_by'] or 'not recorded'}",
            f"- Human approval: {d['human_approval'] or 'not recorded'}"]
    out += [f"- {AWS_DIMENSIONS[k]}: {v or 'not recorded'}"
            for k, v in d["security_dimensions"].items()]
    out += [f"- {c['question']} {c['answer'] or 'not recorded'}" for c in d["feature_context"]]
    out += [f"- {k}: {v}" for k, v in record["context"].items()]
    out += ["", "## Threats", "", "| Id | Threat | Status | Evidence rows | Questions unanswered |",
            "|---|---|---|---|---|"]
    out += [f"| {x['id']} | {x['title']} | {x['status']} | {len(x['evidence'])} | "
            f"{x['questions_unanswered']} of {len(x['answers'])} |" for x in record["threats"]]

    def listing(status: str) -> list[str]:
        return [f"- {x['id']} {x['title']}: {x['reason']}" for x in record["threats"]
                if x["status"] == status] or ["- none"]

    out += ["", "## Not assessed", ""] + listing("not_assessed")
    out += ["", "Answered by the reviewer without evidence:", ""] + listing("answers_only")
    out += ["", "Marked not applicable by the reviewer:", ""] + listing("not_applicable")
    out += ["", "Deployment context not recorded: "
            + ("; ".join(record["deployment_context_missing"]) or "none")]
    absent = [f"- {x['id']}: {a['looked_for']} (looked at: {a['source']})"
              for x in record["threats"] for a in x["vendor_absent"]]
    out += ["", "Vendor material looked for and not found:", ""] + (absent or ["- none recorded"])
    out += ["", "Benchmarks that exist for these threats and were not run in this review: "
            + ("; ".join(record["benchmarks_not_run"]) or "none")]
    out += ["", "No standardized test exists for:", ""]
    out += [f"- {x['id']}: {g}" for x in record["threats"] if x["status"] != "not_applicable"
            for g in x["no_standard_test"]]
    out += ["", "## Detail", ""]
    for x in record["threats"]:
        ids = " · ".join(f"{i} {fw[key][i]}" for key in ("owasp_llm", "owasp_agentic", "atlas")
                         for i in x[key])
        out += [f"### {x['id']} {x['title']} — {x['status']}", "", ids or "No framework id.", ""]
        if x["status"] == "not_applicable":
            out += [f"Not applicable: {x['reason']}", ""]
            continue
        out += [f"- Q: {a['question']}\n  A: {a['answer'] or '(not answered)'}" for a in x["answers"]]
        out += [f"- {e['type']} ({e['provenance']}): {e['claim']} [{e['source']}]"
                for e in x["evidence"]]
        out += [f"- vendor material not found: {a['looked_for']} [{a['source']}]"
                for a in x["vendor_absent"]]
        out += [f"- benchmark available, {'run' if b['run'] else 'not run'}: {b['name']}. "
                f"{b['route']}" for b in x["benchmarks_available"]]
        out.append("")
    out += ["## Decision", "", "Left for the organisation. Not filled by this skill.", "",
            "- Decision:", "- Decided by:", "- Date:", "- Conditions:", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--feature", help="one of: " + ", ".join(templates.features()))
    ap.add_argument("--list", action="store_true", help="list the feature types and exit")
    ap.add_argument("--blank", action="store_true", help="print an empty answers form and exit")
    ap.add_argument("--answers", help="the reviewer's answers (JSON)")
    ap.add_argument("--out", help="review folder")
    ap.add_argument("--evidence", help="evidence.jsonl to append to (default OUT/evidence.jsonl)")
    ap.add_argument("--threat-map", help="JSON mapping this skill's threat ids to the ids of "
                                         "the review's test plan")
    ap.add_argument("--date", default=None, help="review date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)

    if args.list:
        return templates.main(["--list"])
    if not args.feature:
        ap.error("--feature is required")
    if args.feature not in templates.features():
        ap.error(f"unknown feature {args.feature!r}; choose from {templates.features()}")
    if args.blank:
        print(json.dumps(blank(args.feature), indent=2))
        return 0
    if not args.answers or not args.out:
        ap.error("--answers and --out are required (or use --blank)")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    answers = json.loads(Path(args.answers).read_text())
    date = args.date or answers.get("date") or _evidence.today()
    stem = out / f"{args.feature}_review"
    try:
        record, rows = build(args.feature, answers, date, f"{stem}.json")
    except ValueError as exc:
        ap.error(f"{args.answers}: {exc}")
    Path(f"{stem}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    Path(f"{stem}.md").write_text(render(record))
    path = Path(args.evidence) if args.evidence else out / "evidence.jsonl"
    added = _evidence.append(path, rows, _evidence.load_threat_map(args.threat_map))

    by = record["by_status"]
    print(f"{args.feature}: {len(record['threats'])} threats — "
          + ", ".join(f"{len(by[s])} {s}" for s in STATUSES))
    for x in record["threats"]:
        if x["status"] == "not_assessed":
            print(f"  NOT ASSESSED  {x['id']} {x['title']}")
    for x in record["threats"]:
        if x["status"] == "answers_only":
            print(f"  ANSWERS ONLY  {x['id']} {x['title']} ({x['reason']})")
    if record["deployment_context_missing"]:
        print(f"deployment context not recorded: {len(record['deployment_context_missing'])} "
              f"item(s): {'; '.join(record['deployment_context_missing'][:4])}"
              + (" ..." if len(record["deployment_context_missing"]) > 4 else ""))
    print(f"benchmarks available and not run: {'; '.join(record['benchmarks_not_run']) or 'none'}")
    print(f"evidence: {added} new row(s) in {path}")
    print(f"wrote {stem}.json and {stem}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
