#!/usr/bin/env python3
"""Compile the review report from the files the earlier stages wrote. Stdlib only.

    python scripts/compile_report.py --review review.json [--evidence evidence.jsonl] \\
        [--evals .evals | --exp <folder> ...] [--plan test-plan.json] \\
        [--criteria criteria.json] [--out report.md]

Inputs left out are looked for next to review.json (evidence.jsonl, .evals/, test-plan.json,
criteria.json). An input that does not exist is reported as absent in the section it would
have filled; it is never papered over.

Sections, in order:
  1. What was reviewed, and in what context        (review.json)
  2. Evidence, with provenance                      (evidence.jsonl)
  3. Results                                        (experiment folders; validity flags first)
  4. Threats not covered                            (test-plan.json + the above)
  5. The organisation's criteria beside the results ONLY if criteria.json exists
  then Decision, Conditions and Sign-off, left blank for people.

The compiler copies, arranges and counts. It does not rate evidence, does not say whether a
criterion is met, and writes nothing into the decision fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import expread  # noqa: E402

CONTEXT_KEYS = ("surface", "harness", "harness_version", "system_prompt", "tools",
                "safeguards", "data_sensitivity", "autonomy", "notes")
PROVENANCE = (
    ("self_run", "Measured by this organisation"),
    ("reviewed", "Examined by a person in this organisation"),
    ("published", "Stated by the vendor or the benchmark's authors; not checked here"),
    ("harvested", "Read from a third party or an automated feed; not checked here"),
)
CHECKED_HERE = ("self_run", "reviewed")
EVIDENCE_REQUIRED = ("id", "claim", "threats", "source", "captured", "provenance")
BLANK = ""


# --- small helpers ----------------------------------------------------------------------------

def show(value) -> str:
    """A value from review.json as text. Absent is said, not hidden."""
    if value is None or value == "":
        return "not stated"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(show(v) for v in value) if value else "none"
    if isinstance(value, dict):
        return "; ".join(f"{k}: {show(v)}" for k, v in value.items()) if value else "none"
    return str(value)


def cell(value) -> str:
    return show(value).replace("|", "\\|").replace("\n", " ")


def get(doc, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def load_json(path: Path):
    """(data, problem). A missing file is (None, None): absence is not a problem to report here."""
    if not path or not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text()), None
    except ValueError as exc:
        return None, f"{path.name} is not valid JSON ({exc})"


def load_evidence(path: Path) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    for n, line in enumerate(path.read_text().split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            problems.append(f"line {n} is not JSON")
            continue
        missing = [k for k in EVIDENCE_REQUIRED if not isinstance(row, dict) or k not in row]
        if missing:
            problems.append(f"line {n} lacks {', '.join(missing)}")
            continue
        rows.append(row)
    return rows, problems


def demote(markdown: str, by: int = 3) -> str:
    """Push a summary's headings below the report's own, so the outline stays the report's."""
    out, fenced = [], False
    for line in markdown.rstrip().split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        match = None if fenced else re.match(r"^(#{1,6})(\s+.*)$", line)
        out.append("#" * min(6, len(match.group(1)) + by) + match.group(2) if match else line)
    return "\n".join(out)


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


# --- section 1 --------------------------------------------------------------------------------

def unknowns(review: dict) -> list[str]:
    """Dotted paths whose answer is the literal "unknown", plus context keys left empty."""
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str) and node.strip().lower() == "unknown":
            found.append(path)

    walk(review, "")
    ctx = review.get("context") if isinstance(review.get("context"), dict) else {}
    found += [f"context.{k} (not stated)" for k in CONTEXT_KEYS
              if k not in ("notes", "harness_version") and ctx.get(k) in (None, "")]
    return found


def section_scope(review: dict) -> list[str]:
    s = review.get("subject") or {}
    ctx = review.get("context") if isinstance(review.get("context"), dict) else {}
    lines = ["| | |", "|---|---|",
             f"| Subject | {cell(s.get('name'))} |",
             f"| Type | {cell(s.get('type'))}"
             + (f" (feature: {cell(s.get('feature'))})" if s.get("feature") else "") + " |",
             f"| Version | {cell(s.get('version'))} |",
             f"| Vendor | {cell(s.get('vendor'))} |"]
    if isinstance(s.get("weights"), dict):
        lines.append(f"| Weights | open: {cell(s['weights'].get('open'))}"
                     + (f"; repository: {cell(s['weights'].get('repo'))}"
                        if s["weights"].get("repo") else "") + " |")
    lines += ["", "### Deployment context", "",
              "Every result in this report applies to this context and to no other.", "",
              "| Context | As recorded in review.json |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {cell(ctx.get(k))} |" for k in CONTEXT_KEYS]

    lines += ["", "### Who controls each input channel", ""]
    channels = [c for c in review.get("input_channels") or [] if isinstance(c, dict)]
    if channels:
        lines += ["| Channel | Controlled by | Someone outside the organisation can write to it |",
                  "|---|---|---|"]
        lines += [f"| {cell(c.get('channel'))} | {cell(c.get('controlled_by'))} | "
                  f"{cell(c.get('untrusted'))} |" for c in channels]
    else:
        lines.append("No input channels are recorded in review.json.")

    cap = review.get("capabilities") or {}
    fail = review.get("failure_impact") or {}
    budget = review.get("time_budget") or {}
    lines += ["", "### What it can do", "",
              f"- Can read: {show(cap.get('can_read'))}",
              f"- Can do: {show(cap.get('can_do'))}",
              f"- Approval: {show(cap.get('approval'))}",
              f"- Keeps state between sessions: {show(cap.get('memory'))}",
              "", "### What happens on failure", "",
              f"- Worst realistic outcome: {show(fail.get('worst_case'))}",
              f"- Who is affected: {show(fail.get('affected'))}",
              f"- Reversible: {show(fail.get('reversible'))}",
              f"- How it would be noticed: {show(fail.get('detection'))}",
              "", "### Time budget", "",
              f"- Decision due: {show(budget.get('decision_due'))}",
              f"- Reviewer hours available: {show(budget.get('hours_available'))}"]
    if budget.get("notes"):
        lines.append(f"- Notes: {show(budget.get('notes'))}")

    lines += ["", "### Excluded at scoping", ""]
    out = review.get("out_of_scope")
    if out:
        lines += [f"- {show(o.get('item'))} — {show(o.get('reason'))}"
                  for o in out if isinstance(o, dict)]
    elif out == []:
        lines.append("Nothing was excluded.")
    else:
        lines.append("review.json does not say what was excluded.")

    lines += ["", "### Not established at scoping", ""]
    gaps = unknowns(review)
    lines += [f"- `{g}`" for g in gaps] or ["Every scoping answer was given."]
    return lines


# --- section 2 --------------------------------------------------------------------------------

def section_evidence(rows: list[dict] | None, problems: list[str]) -> list[str]:
    if rows is None:
        return ["No evidence.jsonl was supplied. Nothing is recorded about vendor documents, "
                "published scores, data handling, incidents or research. Read that as not "
                "assessed, not as nothing found."]
    lines = []
    counts = {key: sum(1 for r in rows if r.get("provenance") == key and not r.get("absent"))
              for key, _ in PROVENANCE}
    absent = [r for r in rows if r.get("absent")]
    lines += [f"{len(rows)} row(s): " + ", ".join(f"{counts[k]} {k}" for k, _ in PROVENANCE)
              + f", and {len(absent)} recording something looked for and not found.", "",
              "Provenance says who established a claim. `published` and `harvested` claims "
              "were read, not checked.", ""]
    if problems:
        lines += ["**Rows that could not be read and are not shown:** " + "; ".join(problems), ""]

    lines += ["### Looked for and not found", ""]
    if absent:
        lines += ["| Id | What is absent | Bears on | Where it was looked for | Date | Note |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {cell(r['id'])} | {cell(r['claim'])} | {cell(r['threats'])} | "
                  f"{cell(r['source'])} | {cell(r['captured'])} | {cell(r.get('note'))} |"
                  for r in absent]
    else:
        lines.append("No row records an absence. Either everything looked for was found, or "
                     "absences were not written down; the evidence log cannot tell which.")

    for key, title in PROVENANCE:
        group = [r for r in rows if r.get("provenance") == key and not r.get("absent")]
        lines += ["", f"### {title} (`{key}`)", ""]
        if not group:
            lines.append("None.")
            continue
        lines += ["| Id | Claim | Bears on | Source | Date | Note |", "|---|---|---|---|---|---|"]
        lines += [f"| {cell(r['id'])} | {cell(r['claim'])} | {cell(r['threats'])} | "
                  f"{cell(r.get('pointer') or r['source'])} | {cell(r['captured'])} | "
                  f"{cell(r.get('note'))} |" for r in group]
    other = [r for r in rows if r.get("provenance") not in dict(PROVENANCE)]
    if other:
        lines += ["", "### Rows with an unrecognised provenance", ""]
        lines += [f"- {show(r.get('id'))}: `{show(r.get('provenance'))}` — {show(r.get('claim'))}"
                  for r in other]
    return lines


# --- section 3 --------------------------------------------------------------------------------

def context_differences(exp: dict, review: dict) -> list[str]:
    """Where an experiment ran under a context other than the one being reviewed."""
    want = review.get("context") if isinstance(review.get("context"), dict) else {}
    got = exp["context"] or {}
    if exp["manifest"] is not None and not any(v not in (None, "", [], {}) for v in got.values()):
        return ["its manifest records no context, so where this result applies is not recorded"]
    return [f"context differs from review.json on `{k}`: ran with {show(got[k])}; the review "
            f"is of {show(want[k])}"
            for k in CONTEXT_KEYS
            if k != "notes" and got.get(k) not in (None, "") and want.get(k) not in (None, "")
            and got[k] != want[k]]


def read_first(exp: dict, review: dict) -> list[str]:
    """Everything to read before this experiment's numbers. Skill-reported flags come first,
    then what the compiler itself noticed about the folder."""
    notes = []
    for f in exp["failures"]:
        notes.append(f"**No result** — {f['where'] or 'a row'}: status `{f['status']}`"
                     + (f" ({f['error']})" if f.get("error") else "")
                     + ". This is not a zero and not a pass.")
    for f in exp["flags"]:
        seen = "" if f.get("observed") is None else \
            f" (observed {f['observed']}, validity limit {f['limit']})"
        notes.append(f"**Validity flag from the skill** — {f['where'] or 'run'}: `{f['flag']}`"
                     f"{seen}" + (f". {f['meaning']}" if f.get("meaning") else ""))
    notes += [f"**Report check** — {p}" for p in exp["problems"]]
    notes += [f"**Report check** — {d}" for d in context_differences(exp, review)]
    if exp["summary_md"] is not None and not exp["json_sources"] \
            and not exp["summary_validity_lines"]:
        notes.append("**Report check** — the summary has no validity section and no "
                     "machine-readable results, so whether its numbers can be trusted was not "
                     "stated by the skill")
    return notes


def section_results(exps: list[dict], review: dict, evals_note: str) -> list[str]:
    if not exps:
        return [f"No experiment folders were found ({evals_note}). Nothing was measured for "
                "this review; every threat rests on evidence from section 2 alone."]
    lines = [f"{len(exps)} experiment folder(s) from {len({e['skill'] for e in exps})} "
             "skill(s). Each summary below is the measuring skill's own text, unedited.", "",
             "### Read before any number", "",
             "Validity flags say whether a measurement can be trusted. They are not "
             "judgements of whether a result is good or bad, and no number is hidden "
             "because of one.", ""]
    any_note = False
    for exp in exps:
        notes = read_first(exp, review)
        for note in notes:
            any_note = True
            lines.append(f"- `{exp['skill']}` / `{exp['experiment']}`: {note}")
    if not any_note:
        lines.append("- No skill reported a validity flag or a missing result, and the "
                     "compiler found nothing wrong with the folders.")

    for exp in exps:
        manifest = exp["manifest"] or {}
        model = get(manifest, "model.id")
        lines += ["", f"### {exp['skill']} — {exp['label']}", "",
                  f"Folder `{exp['skill']}/{exp['experiment']}`"
                  + (f" · created {exp['created']}" if exp["created"] else "")
                  + (f" · model `{model}`" if model else "")
                  + (f" · engine `{manifest['engine']}`" if manifest.get("engine") else "")]
        ctx = {k: v for k, v in (exp["context"] or {}).items() if v not in (None, "", [], {})}
        want = review.get("context") if isinstance(review.get("context"), dict) else {}
        same = bool(ctx) and all(ctx.get(k) == want.get(k) for k in CONTEXT_KEYS
                                 if k != "notes" and (ctx.get(k) or want.get(k)))
        lines += ["", "Ran under: " + (
            "the context recorded in section 1, according to its manifest." if same else
            "; ".join(f"{k.replace('_', ' ')}: {show(v)}" for k, v in ctx.items())
            or "no context recorded")]
        notes = read_first(exp, review)
        lines += ["", "**Read first:**", ""]
        lines += [f"- {n}" for n in notes] or ["- Nothing flagged for this experiment."]
        if exp["summary_validity_lines"] and not (exp["flags"] or exp["failures"]):
            lines += ["", "**The summary's own validity section says:**", ""]
            lines += [ln if ln.lstrip().startswith(("-", "*", ">", "|")) else f"- {ln}"
                      for ln in exp["summary_validity_lines"]]
        lines += ["", "**Summary as written by the skill:**", ""]
        lines.append(demote(exp["summary_md"]) if exp["summary_md"] is not None
                     else "_No summary.md in this folder._")
    return lines


# --- section 4 --------------------------------------------------------------------------------

def benchmark_results(bench_id: str, skill: str, exps: list[dict]) -> tuple[list[str], list[str]]:
    """(experiments holding a result for the benchmark, experiments where it failed)."""
    ok, failed = [], []
    for exp in exps:
        if exp["skill"] != skill:
            continue
        hits = [m for m in exp["metrics"] if bench_id in m["parts"]]
        if any(m.get("status") in (None, "ok") for m in hits):
            ok.append(exp["experiment"])
        elif hits or any(bench_id in (f.get("where") or "") for f in exp["failures"]):
            failed.append(exp["experiment"])
        elif not exp["json_sources"] and exp["summary_md"] and bench_id in exp["summary_md"]:
            ok.append(exp["experiment"] + " (named in summary.md; no machine-readable result)")
    return ok, failed


def coverage(plan: dict, rows: list[dict], exps: list[dict]) -> list[dict]:
    out = []
    for item in plan.get("threats", []):
        tid = item["threat"]
        ev = [r for r in rows if tid in (r.get("threats") or []) and not r.get("absent")]
        checked = [r["id"] for r in ev if r.get("provenance") in CHECKED_HERE]
        unchecked = [r["id"] for r in ev if r.get("provenance") not in CHECKED_HERE]
        absent = [r["id"] for r in rows if tid in (r.get("threats") or []) and r.get("absent")]
        measured, missing, failed, flagged = [], [], [], []
        for b in item.get("benchmarks", []):
            ok, bad = benchmark_results(b["id"], b["skill"], exps)
            (measured if ok else failed if bad else missing).append(b["id"])
            if ok and any(b["id"] in (f.get("where") or "") for e in exps
                          if e["skill"] == b["skill"] for f in e["flags"]):
                flagged.append(b["id"])
        if item.get("applies") is False:
            state = "ruled out at scoping"
        elif measured:
            state = "measured"
        elif checked:
            state = "examined"
        elif unchecked:
            state = "claims only"
        else:
            state = "not assessed"
        out.append({"threat": tid, "name": item.get("name", ""), "route": item.get("route"),
                    "applies": item.get("applies"), "applies_reason": item.get("applies_reason"),
                    "route_note": item.get("route_note", ""), "measured": measured,
                    "missing": missing, "failed": failed, "flagged": flagged,
                    "checked": checked,
                    "unchecked": unchecked, "absent": absent, "state": state})
    return out


def section_not_covered(plan: dict | None, rows: list[dict], exps: list[dict],
                        review: dict) -> list[str]:
    if plan is None:
        lines = ["No test plan (test-plan.json) was supplied, so this report cannot say which "
                 "threats were considered and which were left out. That is itself a gap: the "
                 "threat model stage was not run or its output was not kept."]
        by_threat: dict[str, set] = {}
        for r in rows:
            for t in r.get("threats") or []:
                by_threat.setdefault(t, set()).add("absent" if r.get("absent")
                                                   else r.get("provenance"))
        if by_threat:
            lines += ["", "Threat ids named in the evidence log, and what stands behind each:", ""]
            lines += [f"- `{t}`: {', '.join(sorted(str(p) for p in provs))}"
                      for t, provs in sorted(by_threat.items())]
        return lines

    cov = coverage(plan, rows, exps)
    lines = [f"From the test plan for template `{plan.get('template')}` "
             f"({len(cov)} threats). A threat is listed here when nothing in this review "
             "measured or examined it.", ""]

    def block(title: str, items: list[dict], text) -> None:
        lines.extend(["", f"### {title}", ""])
        lines.extend([f"- `{c['threat']}` {c['name']} — {text(c)}" for c in items] or ["None."])

    not_run = [c for c in cov if c["applies"] is not False and c["route"] == "benchmark"
               and not c["measured"]]
    block("Planned for measurement, no result found", not_run,
          lambda c: "; ".join(filter(None, [
              "not run: " + ", ".join(f"`{b}`" for b in c["missing"]) if c["missing"] else "",
              "ran without producing a score: " + ", ".join(f"`{b}`" for b in c["failed"])
              if c["failed"] else ""])))
    partial = [c for c in cov if c["measured"] and (c["missing"] or c["failed"])]
    block("Measured in part", partial,
          lambda c: "result for " + ", ".join(f"`{b}`" for b in c["measured"])
          + "; none for " + ", ".join(f"`{b}`" for b in c["missing"] + c["failed"]))
    todo = [c for c in cov if c["applies"] is not False
            and c["route"] in ("custom_probe", "design_review") and not c["checked"]]
    block("Custom probe or design review planned, nothing recorded", todo,
          lambda c: f"{c['route'].replace('_', ' ')}; no `self_run` or `reviewed` evidence row "
                    "names this threat"
                    + (f"; vendor or third-party claims only ({', '.join(c['unchecked'])})"
                       if c["unchecked"] else ""))
    uncovered = [c for c in cov if c["applies"] is not False and c["route"] == "uncovered"
                 and not c["checked"]]
    block("Uncovered by the plan", uncovered,
          lambda c: c["route_note"] or "no catalogued benchmark, probe or review route")
    unconfirmed = [c for c in cov if c["applies"] is None]
    block("Applicability never confirmed", unconfirmed,
          lambda c: c["applies_reason"] or "review.json did not settle whether it applies")
    ruled_out = [c for c in cov if c["applies"] is False]
    block("Ruled out at scoping", ruled_out, lambda c: c["applies_reason"] or "no reason given")

    lines += ["", "### Every threat in the plan", "",
              "State: `measured` a planned benchmark has a result · `examined` a `self_run` or "
              "`reviewed` evidence row names it · `claims only` only vendor or third-party "
              "claims · `not assessed` nothing. `measured` means a number exists, not that "
              "the threat is absent. ⚑ a validity flag applies to that result (section 3).", "",
              "| Threat | Planned route | Results found | Evidence checked here | "
              "Claims not checked here | Recorded as absent | State |",
              "|---|---|---|---|---|---|---|"]
    for c in cov:
        lines.append(f"| `{c['threat']}` | {str(c['route']).replace('_', ' ')} | "
                     + (", ".join(b + (" ⚑" if b in c["flagged"] else "")
                                  for b in c["measured"]) or "—")
                     + f" | {', '.join(c['checked']) or '—'} | "
                     f"{', '.join(c['unchecked']) or '—'} | {', '.join(c['absent']) or '—'} | "
                     f"{c['state']} |")

    planned = {c["threat"] for c in cov}
    extra = sorted({t for r in rows for t in r.get("threats") or []} - planned)
    if extra:
        lines += ["", "Threat ids in the evidence log that the plan does not contain: "
                  + ", ".join(f"`{t}`" for t in extra) + "."]
    out = review.get("out_of_scope")
    if out:
        lines += ["", "Excluded at scoping and therefore not assessed at all: "
                  + "; ".join(show(o.get("item")) for o in out if isinstance(o, dict)) + "."]
    return lines


# --- section 5 --------------------------------------------------------------------------------

def bound_text(bound) -> str:
    if not isinstance(bound, dict) or not bound.get("type"):
        return "not stated"
    kind = bound["type"]
    if kind in ("at_least", "at_most"):
        text = f"{kind.replace('_', ' ')} {show(bound.get('value'))}"
        return text + (f", read on the {str(bound['applies_to']).replace('_', ' ')}"
                       if bound.get("applies_to") else "")
    if kind == "no_worse_than_reference":
        return f"no worse than the organisation's reference `{show(bound.get('reference'))}`"
    return kind.replace("_", " ")


def section_criteria(criteria, problem: str | None, exps: list[dict]) -> list[str]:
    lines = ["These criteria are the organisation's own, taken from criteria.json. Each is "
             "placed beside the matching result. This report does not evaluate them: whether "
             "a criterion is met is for the organisation to state, in the last column or in "
             "the decision below.", ""]
    if problem:
        return lines + [f"criteria.json exists but could not be read: {problem}."]
    items = criteria.get("criteria") if isinstance(criteria, dict) else None
    if not isinstance(items, list) or not items:
        return lines + ["criteria.json exists and contains no criteria."]

    earliest = min((e["created"] for e in exps if e.get("created")), default=None)
    after = [c for c in items if isinstance(c, dict)
             and c.get("set_relative_to_results") == "after"]
    if after:
        lines += [f"**{len(after)} of {len(items)} criteria were set after results for this "
                  "subject had been seen** (" + ", ".join(show(c.get("id")) for c in after)
                  + "). A criterion chosen after the result is weaker evidence than one "
                  "chosen before.", ""]
    lines += ["| Id | Dimension | Criterion, in the organisation's words | Bound | Set by | "
              "Set on | Before or after results | Matching result | Met? (organisation) |",
              "|---|---|---|---|---|---|---|---|---|"]
    matched_labels = set()
    notes = []
    for c in items:
        if not isinstance(c, dict):
            continue
        measure = c.get("measure") if isinstance(c.get("measure"), dict) else {}
        found = [(e, m) for e in exps for m in expread.match_metrics(e, measure)]
        matched_labels |= {(e["experiment"], m["label"]) for e, m in found}
        result = "<br>".join(f"{m['label']}: {expread.fmt_metric(m)} ({e['experiment']})"
                             for e, m in found) or "no matching result found"
        lines.append(f"| {cell(c.get('id'))} | {cell(c.get('dimension'))} | "
                     f"{cell(c.get('statement'))} | {cell(bound_text(c.get('bound')))} | "
                     f"{cell(c.get('set_by'))} | {cell(c.get('set_on'))} | "
                     f"{cell(c.get('set_relative_to_results'))} | {result} | {BLANK} |")
        if c.get("set_relative_to_results") == "before" and earliest and c.get("set_on") \
                and str(c["set_on"]) > str(earliest)[:10]:
            notes.append(f"{show(c.get('id'))} is recorded as set before results, but is "
                         f"dated {c['set_on']}, after the earliest experiment in this report "
                         f"was created ({str(earliest)[:10]}).")
    if notes:
        lines += ["", "**Timing to confirm:**", ""] + [f"- {n}" for n in notes]

    unmatched = [f"{m['label']} ({e['skill']})" for e in exps for m in e["metrics"]
                 if (e["experiment"], m["label"]) not in matched_labels]
    lines += ["", "### Measured, with no criterion set", ""]
    lines += [f"- {u}" for u in sorted(set(unmatched))] or ["None."]
    declined = criteria.get("no_criterion") if isinstance(criteria, dict) else None
    if declined:
        lines += ["", "### Dimensions the organisation chose to set no criterion for", ""]
        lines += [f"- {show(d.get('dimension'))} — {show(d.get('reason'))} "
                  f"({show(d.get('decided_by'))}, {show(d.get('decided_on'))})"
                  for d in declined if isinstance(d, dict)]
    return lines


# --- people's sections --------------------------------------------------------------------------

def sections_for_people() -> list[tuple[str, list[str]]]:
    return [
        ("Decision", [
            "To be completed by the accountable person. Nothing in this report fills it in.", "",
            "- Decision: ", "- Decided by (name, role): ", "- Date: ",
            "- Sections of this report relied on: "]),
        ("Conditions", [
            "To be completed by the accountable person: any conditions attached to the "
            "decision, each with an owner and a date.", "",
            "| # | Condition | Owner | Due |", "|---|---|---|---|",
            "| | | | |", "| | | | |", "| | | | |"]),
        ("Sign-off", [
            "| Role | Name | Signature | Date |", "|---|---|---|---|",
            "| | | | |", "| | | | |", "| | | | |"]),
    ]


# --- assembly -----------------------------------------------------------------------------------

def compile_report(review: dict, *, evidence: list[dict] | None = None,
                   evidence_problems: list[str] | None = None, exps: list[dict] | None = None,
                   plan: dict | None = None, criteria=None, criteria_exists: bool = False,
                   criteria_problem: str | None = None, inputs: list[tuple] | None = None,
                   evals_note: str = "none given", today: str | None = None) -> str:
    exps = exps or []
    s = review.get("subject") or {}
    sections: list[tuple[str, list[str]]] = [
        ("What was reviewed, and in what context", section_scope(review)),
        ("Evidence, with provenance", section_evidence(evidence, evidence_problems or [])),
        ("Results", section_results(exps, review, evals_note)),
        ("Threats not covered", section_not_covered(plan, evidence or [], exps, review)),
    ]
    if criteria_exists:
        sections.append(("The organisation's criteria beside the results",
                         section_criteria(criteria, criteria_problem, exps)))
    sections += sections_for_people()

    lines = [f"# AI security review — {show(s.get('name'))} ({show(s.get('version'))})", "",
             f"Compiled {today or dt.date.today().isoformat()} by review-report from the files "
             "listed at the end. This report records what was reviewed, the evidence gathered "
             "and what was measured. It contains no verdict: the decision, any conditions and "
             "the sign-off are left blank for the accountable people.", "",
             "| | |", "|---|---|",
             f"| Review | {cell(review.get('review_id'))} |",
             f"| Requested by | {cell(review.get('requested_by'))} |",
             f"| Reviewer | {cell(review.get('reviewer'))} |",
             f"| Opened | {cell(review.get('opened'))} |",
             f"| Decision due | {cell(get(review, 'time_budget.decision_due'))} |"]
    if not criteria_exists:
        lines += ["", "No criteria.json was supplied. This report therefore shows no acceptance "
                  "criteria, and none are implied by anything in it."]
    for n, (title, body) in enumerate(sections, 1):
        lines += ["", f"## {n}. {title}", ""] + body

    lines += ["", "## Inputs to this report", "", "| Input | File | SHA-256 (first 12) |",
              "|---|---|---|"]
    lines += [f"| {name} | {path if path else 'not supplied'} | {digest or '—'} |"
              for name, path, digest in inputs or []]
    if exps:
        lines += ["", "Experiment folders read:", ""]
        lines += [f"- `{e['skill']}/{e['experiment']}`"
                  + (f" ({', '.join(e['json_sources'])})" if e["json_sources"]
                     else " (no machine-readable results)") for e in exps]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--review", required=True)
    p.add_argument("--evidence")
    p.add_argument("--evals", help="directory holding <skill>/<experiment>/ folders")
    p.add_argument("--exp", action="append", default=[],
                   help="one experiment folder; repeatable; used instead of --evals")
    p.add_argument("--plan")
    p.add_argument("--criteria")
    p.add_argument("--out")
    p.add_argument("--date", help="date printed in the report (default: today)")
    args = p.parse_args(argv)

    review_path = Path(args.review)
    review, problem = load_json(review_path)
    if not isinstance(review, dict):
        print(f"error: cannot read {args.review}: {problem or 'not found or not an object'}",
              file=sys.stderr)
        return 1
    base = review_path.resolve().parent

    def pick(given: str | None, default: str) -> Path | None:
        path = Path(given) if given else base / default
        if given and not path.exists():
            print(f"warning: {given} does not exist; reported as not supplied", file=sys.stderr)
        return path if path.exists() else None

    evidence_path = pick(args.evidence, "evidence.jsonl")
    plan_path = pick(args.plan, "test-plan.json")
    criteria_path = pick(args.criteria, "criteria.json")
    evals_path = pick(args.evals, ".evals")

    evidence, evidence_problems = (load_evidence(evidence_path) if evidence_path
                                   else (None, []))
    plan, plan_problem = load_json(plan_path) if plan_path else (None, None)
    if plan_problem:
        print(f"warning: {plan_problem}; reported as not supplied", file=sys.stderr)
    if not isinstance(plan, dict):
        plan = None
    criteria, criteria_problem = load_json(criteria_path) if criteria_path else (None, None)

    folders = [Path(f) for f in args.exp] or (expread.find_experiments(evals_path)
                                              if evals_path else [])
    exps = [expread.read_experiment(f) for f in folders]
    evals_note = (f"{len(args.exp)} given with --exp" if args.exp
                  else f"looked in {evals_path}" if evals_path else "no experiment directory")

    out = Path(args.out) if args.out else base / "report.md"

    def rel(path: Path | None) -> str | None:
        return os.path.relpath(path.resolve(), out.resolve().parent) if path else None

    inputs = [(name, rel(path), sha12(path) if path and path.is_file() else None)
              for name, path in (("review.json", review_path), ("evidence.jsonl", evidence_path),
                                 ("test-plan.json", plan_path), ("criteria.json", criteria_path))]
    text = compile_report(
        review, evidence=evidence, evidence_problems=evidence_problems, exps=exps, plan=plan,
        criteria=criteria, criteria_exists=criteria_path is not None,
        criteria_problem=criteria_problem, inputs=inputs, evals_note=evals_note, today=args.date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    flagged = sum(1 for e in exps if e["flags"] or e["failures"] or e["problems"])
    print(f"wrote {out}: {len(evidence or [])} evidence row(s), {len(exps)} experiment(s) "
          f"({flagged} with something to read first), plan "
          f"{'supplied' if plan else 'not supplied'}, criteria "
          f"{'supplied' if criteria_path else 'not supplied'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
