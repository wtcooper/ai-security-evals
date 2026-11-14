#!/usr/bin/env python3
"""Help an organisation write its own acceptance criteria, and validate the file. Stdlib only.

    python scripts/criteria.py init      --out criteria.json [--review review.json]
    python scripts/criteria.py worksheet --plan test-plan.json [--review review.json] \\
                                         [--reference <exp folder> ...] [--subject <exp folder> ...] \\
                                         [--show-subject-results] [--out worksheet.md]
    python scripts/criteria.py add       --file criteria.json --id C1 --dimension "..." \\
                                         --skill S --benchmark B --statement "..." \\
                                         --bound-type at_most --value <the organisation's number> \\
                                         --applies-to interval_upper --set-by "name, role" --timing before
    python scripts/criteria.py decline   --file criteria.json --dimension "..." --reason "..." --decided-by "..."
    python scripts/criteria.py validate  criteria.json [--evals .evals]

This script never proposes a value. `worksheet` shows, for each measured dimension, what the
number means, how wide its interval is at the depth run, and the organisation's own earlier
results as reference points. `add` records a value only when one is given on the command
line, with who set it, when, and whether results for the subject had been seen.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import expread  # noqa: E402
from evalkit import wilson_ci  # noqa: E402

TEMPLATE = SKILL / "criteria.template.json"
BOUND_TYPES = ("at_least", "at_most", "no_worse_than_reference", "qualitative")
NUMERIC_BOUNDS = ("at_least", "at_most")
APPLIES_TO = ("point_estimate", "interval_lower", "interval_upper")
TIMING = ("before", "after")


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _text(x) -> bool:
    return isinstance(x, str) and bool(x.strip())


def _date(x):
    try:
        return dt.date.fromisoformat(x)
    except (TypeError, ValueError):
        return None


# --- validation -------------------------------------------------------------------------------

def check_criterion(c) -> tuple[list[str], list[str]]:
    if not isinstance(c, dict):
        return ["not a JSON object"], []
    errs, warns = [], []
    for key in ("id", "dimension", "statement", "set_by"):
        if not _text(c.get(key)):
            errs.append(f"{key} is missing: " + {
                "id": "give the criterion an id",
                "dimension": "name what is measured",
                "statement": "state the criterion in the organisation's own words",
                "set_by": "record who set it (a named person or role)"}[key])

    measure = c.get("measure")
    if not isinstance(measure, dict) or not _text(measure.get("skill")) \
            or not (_text(measure.get("benchmark")) or _text(measure.get("metric"))):
        errs.append("measure must name the skill and a benchmark or metric, so the report can "
                    "place the criterion beside its result")

    bound = c.get("bound")
    if not isinstance(bound, dict) or bound.get("type") not in BOUND_TYPES:
        errs.append(f"bound.type must be one of {list(BOUND_TYPES)}")
    else:
        kind, value = bound["type"], bound.get("value")
        if kind in NUMERIC_BOUNDS:
            if not _number(value):
                errs.append(f"bound.value must be a number for {kind} (the organisation's own; "
                            "this tool supplies none)")
            elif not 0 <= value <= 1:
                warns.append(f"bound.value {value} is outside 0..1; rates in the result files "
                             "are fractions, so a percentage would never match")
            if bound.get("applies_to") not in APPLIES_TO:
                errs.append(f"bound.applies_to must be one of {list(APPLIES_TO)}: say whether "
                            "the bound is read on the measured rate or on an end of its interval")
        else:
            if value is not None:
                errs.append(f"bound.value must be null for {kind}")
            if kind == "no_worse_than_reference" and not _text(bound.get("reference")):
                errs.append("bound.reference must name the organisation's own earlier result")

    set_on = _date(c.get("set_on"))
    if set_on is None:
        errs.append("set_on must be a YYYY-MM-DD date")
    elif set_on > dt.date.today():
        errs.append("set_on is in the future")
    timing = c.get("set_relative_to_results")
    if timing not in TIMING:
        errs.append('set_relative_to_results must be "before" or "after": were results for this '
                    "subject seen when the criterion was set?")
    elif timing == "after":
        warns.append("set after results for this subject were seen: weaker evidence than a "
                     "criterion set before; the report will say so")

    costs = c.get("error_costs")
    if not isinstance(costs, dict) or not _text(costs.get("if_too_lenient")) \
            or not _text(costs.get("if_too_strict")):
        warns.append("error_costs is incomplete: record what it costs if the criterion lets a "
                     "bad result through, and what it costs if it blocks a good one")
    return errs, warns


def validate(doc, exps: list[dict] | None = None) -> dict:
    errs, warns = [], []
    if not isinstance(doc, dict):
        return {"errors": ["top level must be a JSON object"], "warnings": [], "criteria": 0}
    if doc.get("schema_version") != 1:
        errs.append("schema_version must be 1")
    items = doc.get("criteria")
    if not isinstance(items, list):
        return {"errors": errs + ["criteria must be a list"], "warnings": warns, "criteria": 0}
    seen = set()
    for n, c in enumerate(items, 1):
        label = c.get("id") if isinstance(c, dict) and _text(c.get("id")) else f"criterion {n}"
        c_errs, c_warns = check_criterion(c)
        errs += [f"{label}: {e}" for e in c_errs]
        warns += [f"{label}: {w}" for w in c_warns]
        if label in seen:
            errs.append(f"{label}: duplicate id")
        seen.add(label)
        if exps and isinstance(c, dict) and c.get("set_relative_to_results") == "before":
            skill = (c.get("measure") or {}).get("skill") if isinstance(c.get("measure"), dict) \
                else None
            dates = [str(e["created"])[:10] for e in exps
                     if e.get("created") and e["skill"] == skill]
            if dates and _date(c.get("set_on")) and c["set_on"] > min(dates):
                warns.append(f"{label}: recorded as set before results, but set_on "
                             f"{c['set_on']} is later than a {skill} experiment created "
                             f"{min(dates)}; confirm which results had been seen")
    for n, d in enumerate(doc.get("no_criterion") or [], 1):
        if not isinstance(d, dict) or not all(_text(d.get(k)) for k in
                                              ("dimension", "reason", "decided_by")):
            errs.append(f"no_criterion {n}: needs dimension, reason and decided_by")
    if not items and not doc.get("no_criterion"):
        warns.append("no criteria and no declined dimensions: the report will show results with "
                     "nothing beside them")
    return {"errors": errs, "warnings": warns, "criteria": len(items)}


# --- worksheet ----------------------------------------------------------------------------------

def halfwidth_pp(rate: float, n: int) -> float:
    lo, hi = wilson_ci(rate, n)
    return round((hi - lo) / 2 * 100, 1)


def dimensions_from_plan(plan: dict) -> dict:
    dims = {}
    for item in plan.get("threats", []):
        if item.get("applies") is False:
            continue
        for b in item.get("benchmarks", []):
            dim = dims.setdefault(b["id"], {
                "benchmark": b["id"], "skill": b["skill"], "depth": b.get("depth"),
                "planned_n": b.get("samples"), "reads_as": b.get("reads_as"),
                "direction": b.get("direction"),
                "note": " ".join(filter(None, [b.get("subject_note"), b.get("note")])),
                "threats": []})
            dim["threats"].append(item["threat"])
    return dims


def worksheet(plan: dict | None, review: dict | None, reference: list[dict],
              subject: list[dict], show_subject: bool, today: str | None = None) -> str:
    dims = dimensions_from_plan(plan) if plan else {}
    for exp in subject:                       # dimensions measured but absent from the plan
        for m in exp["metrics"]:
            key = m["benchmark"] or m["label"]
            dims.setdefault(key, {"benchmark": key, "skill": exp["skill"], "depth": None,
                                  "planned_n": None, "reads_as": m.get("reads_as"),
                                  "direction": m.get("direction"), "note": "", "threats": []})
    fail = (review or {}).get("failure_impact") or {}
    lines = [
        "# Criteria worksheet", "",
        f"Prepared {today or dt.date.today().isoformat()} by review-criteria. This sheet gives "
        "the organisation what it needs to write its own acceptance criteria. It contains no "
        "suggested value, and nothing in it should be read as one.", ""]
    if show_subject:
        lines += ["> **Results for the subject are shown below.** Any criterion written after "
                  "reading this sheet must be recorded with `--timing after`.", ""]
    else:
        lines += ["> Results for the subject are not shown. Criteria written from this sheet "
                  "can be recorded with `--timing before`, provided nobody setting them has "
                  "seen the subject's results elsewhere.", ""]
    if fail:
        lines += ["From review.json, what failure means in this deployment:", "",
                  f"- Worst realistic outcome: {fail.get('worst_case') or 'not stated'}",
                  f"- Who is affected: {fail.get('affected') or 'not stated'}",
                  "- Reversible: " + {True: "yes", False: "no"}.get(
                      fail.get("reversible"), str(fail.get("reversible") or "not stated")),
                  f"- How it would be noticed: {fail.get('detection') or 'not stated'}", ""]
    if not dims:
        lines += ["No measured dimension was found: give a test plan with benchmarks in it, or "
                  "experiment folders. A dimension with no measurement can still have a "
                  "qualitative criterion."]
        return "\n".join(lines) + "\n"

    for key, dim in dims.items():
        lines += [f"## `{key}` — {dim['skill']}", ""]
        if dim["threats"]:
            lines.append("Bears on: " + ", ".join(f"`{t}`" for t in dim["threats"]) + ".")
            lines.append("")
        direction = {"higher_is_better": "A higher value is better for the defender.",
                     "lower_is_better": "A lower value is better for the defender."
                     }.get(dim["direction"], "The direction of this number is not recorded: "
                                             "read the skill's summary before setting anything.")
        lines += ["**What the number means.** "
                  + (f"It is the {dim['reads_as']}. " if dim["reads_as"] else
                     "Its meaning is not recorded in the plan: read the skill's summary. ")
                  + direction + (f" {dim['note']}" if dim["note"] else ""), ""]

        ns = sorted({m["n"] for exp in subject for m in exp["metrics"]
                     if key in m["parts"] and m["n"]})
        n = ns[0] if ns else dim["planned_n"]
        if n:
            source = "as run" if ns else f"as planned at depth `{dim['depth']}`"
            lines += [f"**How wide the interval is.** With {n} tests ({source}), the 95% "
                      f"interval reaches about ±{halfwidth_pp(0.5, n)} percentage points "
                      f"around a measured rate near 50%, ±{halfwidth_pp(0.8, n)} near 80% or "
                      f"20%, and ±{halfwidth_pp(0.95, n)} near 95% or 5%. A bound that sits "
                      "closer to the measured rate than that cannot be told apart from it at "
                      "this depth: either run deeper, or say which end of the interval the "
                      "bound is read on.", ""]
        else:
            lines += ["**How wide the interval is.** The number of tests is not known yet, so "
                      "the interval cannot be stated. Settle the depth first.", ""]

        lines += ["**What each error costs here.** Answer both before choosing anything; the "
                  "answers are recorded with the criterion.", "",
                  "- If the criterion is too lenient, a result that should have stopped the "
                  "rollout passes. In this deployment that means: ______",
                  "- If the criterion is too strict, a result that was good enough blocks the "
                  "rollout, or pushes safeguards to refuse legitimate work. In this deployment "
                  "that means: ______", ""]

        lines += ["**Your own reference points.** Results for things the organisation already "
                  "runs, from its own experiment folders.", ""]
        refs = [(exp, m) for exp in reference for m in exp["metrics"] if key in m["parts"]]
        if refs:
            lines += ["| What | Result | Experiment | Created | Ran under |", "|---|---|---|---|---|"]
            for exp, m in refs:
                ctx = exp["context"] or {}
                under = "; ".join(f"{k}: {ctx[k]}" for k in ("surface", "harness")
                                  if ctx.get(k)) or "context not recorded"
                lines.append(f"| {m['label']} | {expread.fmt_metric(m)} | {exp['experiment']} | "
                             f"{str(exp['created'] or 'not recorded')[:10]} | {under} |")
            lines += ["", "These are comparable with the subject only if they were run at the "
                      "same depth and seed and under a context that matches; check each "
                      "summary."]
        else:
            lines.append("None found in the reference folders given. Without a reference "
                         "point the organisation is choosing a number with nothing of its own "
                         "to compare against; running the same benchmark on something it "
                         "already accepts would give one.")
        if show_subject:
            mine = [(exp, m) for exp in subject for m in exp["metrics"] if key in m["parts"]]
            lines += ["", "**The subject's result.**", ""]
            lines += [f"- {m['label']}: {expread.fmt_metric(m)} ({exp['experiment']})"
                      for exp, m in mine] or ["- No result found for this dimension."]
        lines += ["", "**The organisation's criterion.** ______ (set by ______ on ______; "
                  "results for the subject seen: yes / no)", ""]
    lines += ["## Dimensions with no measurement", "",
              "Threats the plan routes to a custom probe, a design review or nothing have no "
              "number. The organisation can still state a qualitative criterion for them "
              "(`--bound-type qualitative`), or record that it sets none (`decline`)."]
    return "\n".join(lines) + "\n"


# --- file edits -----------------------------------------------------------------------------------

def load(path: Path) -> dict:
    return json.loads(path.read_text())


def save(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")


def init(out: Path, review: dict | None) -> dict:
    doc = load(TEMPLATE)
    if review:
        subject = review.get("subject") or {}
        doc["review_id"] = review.get("review_id") or ""
        doc["subject"] = " ".join(str(subject.get(k)) for k in ("name", "version")
                                  if subject.get(k))
    if out.exists():
        raise ValueError(f"{out} already exists; not overwriting the organisation's criteria")
    save(out, doc)
    return doc


def add_criterion(path: Path, criterion: dict) -> dict:
    doc = load(path)
    errs, _ = check_criterion(criterion)
    if any(isinstance(c, dict) and c.get("id") == criterion.get("id")
           for c in doc.get("criteria", [])):
        errs.append(f"id {criterion.get('id')} is already used")
    if errs:
        raise ValueError("criterion not added: " + "; ".join(errs))
    doc.setdefault("criteria", []).append(criterion)
    save(path, doc)
    return criterion


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="start criteria.json from the empty template")
    i.add_argument("--out", default="criteria.json")
    i.add_argument("--review")

    w = sub.add_parser("worksheet", help="what the organisation needs to set its own criteria")
    w.add_argument("--plan")
    w.add_argument("--review")
    w.add_argument("--reference", nargs="*", default=[],
                   help="experiment folders for things the organisation already runs")
    w.add_argument("--subject", nargs="*", default=[],
                   help="experiment folders for the subject under review")
    w.add_argument("--show-subject-results", action="store_true",
                   help="print the subject's results (criteria set afterwards are `after`)")
    w.add_argument("--out")

    a = sub.add_parser("add", help="record one criterion the organisation has decided")
    a.add_argument("--file", default="criteria.json")
    a.add_argument("--id", required=True)
    a.add_argument("--dimension", required=True)
    a.add_argument("--skill", required=True)
    a.add_argument("--benchmark")
    a.add_argument("--metric")
    a.add_argument("--arm")
    a.add_argument("--statement", required=True, help="the criterion in the organisation's words")
    a.add_argument("--bound-type", required=True, choices=BOUND_TYPES)
    a.add_argument("--value", type=float, help="the organisation's number; no default exists")
    a.add_argument("--applies-to", choices=APPLIES_TO)
    a.add_argument("--reference-label", help="for no_worse_than_reference: the earlier result")
    a.add_argument("--set-by", required=True)
    a.add_argument("--set-on", help="YYYY-MM-DD (default: today)")
    a.add_argument("--timing", required=True, choices=TIMING,
                   help="before or after results for this subject were seen")
    a.add_argument("--if-too-lenient", default="")
    a.add_argument("--if-too-strict", default="")
    a.add_argument("--rationale", default="")

    d = sub.add_parser("decline", help="record that no criterion is set for a dimension")
    d.add_argument("--file", default="criteria.json")
    d.add_argument("--dimension", required=True)
    d.add_argument("--reason", required=True)
    d.add_argument("--decided-by", required=True)
    d.add_argument("--decided-on")

    v = sub.add_parser("validate", help="check criteria.json; exit 1 on any error")
    v.add_argument("file")
    v.add_argument("--evals", help="experiment directory, to cross-check before/after dates")

    args = p.parse_args(argv)
    try:
        if args.cmd == "init":
            init(Path(args.out), load(Path(args.review)) if args.review else None)
            print(f"wrote {args.out}: no criteria yet. Run `worksheet`, then `add`.")
            return 0
        if args.cmd == "worksheet":
            text = worksheet(
                load(Path(args.plan)) if args.plan else None,
                load(Path(args.review)) if args.review else None,
                [expread.read_experiment(f) for f in args.reference],
                [expread.read_experiment(f) for f in args.subject],
                args.show_subject_results)
            if args.out:
                Path(args.out).write_text(text)
                print(f"wrote {args.out}")
            else:
                print(text, end="")
            return 0
        if args.cmd == "add":
            criterion = {
                "id": args.id, "dimension": args.dimension,
                "measure": {"skill": args.skill, "benchmark": args.benchmark,
                            "metric": args.metric, "arm": args.arm},
                "statement": args.statement,
                "bound": {"type": args.bound_type, "value": args.value,
                          "applies_to": args.applies_to, "reference": args.reference_label},
                "error_costs": {"if_too_lenient": args.if_too_lenient,
                                "if_too_strict": args.if_too_strict},
                "set_by": args.set_by, "set_on": args.set_on or dt.date.today().isoformat(),
                "set_relative_to_results": args.timing, "rationale": args.rationale}
            add_criterion(Path(args.file), criterion)
            print(f"added {args.id} to {args.file} (set by {args.set_by}, {args.timing} results)")
            return 0
        if args.cmd == "decline":
            doc = load(Path(args.file))
            doc.setdefault("no_criterion", []).append({
                "dimension": args.dimension, "reason": args.reason,
                "decided_by": args.decided_by,
                "decided_on": args.decided_on or dt.date.today().isoformat()})
            save(Path(args.file), doc)
            print(f"recorded: no criterion for {args.dimension}")
            return 0
        exps = [expread.read_experiment(f) for f in expread.find_experiments(args.evals)] \
            if args.evals else None
        result = validate(load(Path(args.file)), exps)
        for e in result["errors"]:
            print("ERROR", e)
        for wmsg in result["warnings"]:
            print("warn ", wmsg)
        print(f"{result['criteria']} criteria, {len(result['errors'])} error(s), "
              f"{len(result['warnings'])} warning(s)")
        return 1 if result["errors"] else 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
