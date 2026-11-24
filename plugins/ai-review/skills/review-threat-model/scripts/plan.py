#!/usr/bin/env python3
"""Build the threat-model and test-plan skeleton for a review. Stdlib only.

    python scripts/plan.py --review review.json [--depth standard] [--out-dir DIR]

Reads review.json (from review-scope), the threat template for its subject type
(references/threats.json + templates.json) and the benchmark catalogue (catalog.json), and
writes test-plan.json and test-plan.md. Every threat in the template lands in exactly one
route:

  benchmark      an available catalogued benchmark covers it: names the skill, benchmark, depth
  custom_probe   measurable, but nothing in the catalogue runs today: the reviewer builds a probe
  design_review  assessed by reading the design, configuration or contract, not by measuring
  uncovered      nothing here assesses it; the report carries it as not assessed

A threat the scope rules out (for example a tool threat when no tools are attached) stays in
the plan, marked `applies: false` with the reason. Nothing is dropped silently.

The output is a skeleton. It names what to measure and how deep; it does not say what result
would be acceptable, and it does not recommend controls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "lib"))
from evalkit import DEPTHS, resolve_depth, wilson_ci  # noqa: E402

TEMPLATE_FOR = {"model": "model", "agent": "agent-in-harness", "app": "app",
                "decision-model": "decision-model", "voice-model": "voice-model",
                "image-model": "image-model", "feature": "feature"}
ROUTES = ("benchmark", "custom_probe", "design_review", "uncovered")
ROUTE_TITLES = {
    "benchmark": "Covered by a catalogued benchmark",
    "custom_probe": "Needs a custom probe",
    "design_review": "Design review only",
    "uncovered": "Uncovered",
}
DEFAULT_TIERS = ("T0", "T1")     # T2 (supervised sandbox) is off unless asked for
UNKNOWN = "unknown"


def load_json(path: Path):
    return json.loads(Path(path).read_text())


def load_references(ref_dir: Path = SKILL / "references") -> tuple[dict, dict]:
    threats = {t["id"]: t for t in load_json(ref_dir / "threats.json")["threats"]}
    templates = load_json(ref_dir / "templates.json")["templates"]
    return threats, templates


def template_threats(template: dict, feature: str | None) -> list[dict]:
    """The ordered {threat, why} list of a template. The feature template is the threats of
    the named feature followed by the common ones."""
    if "threats" in template:
        return template["threats"]
    features = template["features"]
    chosen = features.get(feature or "other", features["other"])
    seen = {u["threat"] for u in chosen}
    return chosen + [u for u in template["common"] if u["threat"] not in seen]


def scope_facts(review: dict) -> dict:
    """What the plan needs to know from review.json. None means the profile does not say."""
    ctx = review.get("context") or {}
    tools = ctx.get("tools")
    weights = (review.get("subject") or {}).get("weights") or {}
    channels = review.get("input_channels") or []
    return {
        "tools": None if not isinstance(tools, list) else bool(tools),
        "open_weights": weights.get("open") if isinstance(weights.get("open"), bool) else None,
        "untrusted_channels": [c.get("channel") for c in channels
                               if isinstance(c, dict) and c.get("untrusted") is True],
    }


def applicability(threat: dict, facts: dict) -> tuple[bool | None, str]:
    """(applies, reason). None: review.json does not settle it; the reviewer must."""
    for need in threat.get("requires", []):
        have = facts.get(need)
        if have is False:
            return False, f"review.json lists no {need}"
        if have is None:
            return None, f"review.json does not say whether there are {need}; confirm"
    return True, ""


def interval_halfwidth_pp(n: int | None) -> dict | None:
    """Half-width of the 95% Wilson interval, in percentage points, if the observed rate were
    0.5 (the widest case) or 0.9. Says how much a number at this n can be trusted to move."""
    if not n:
        return None
    out = {}
    for label, rate in (("at_rate_0.5", 0.5), ("at_rate_0.9", 0.9)):
        lo, hi = wilson_ci(rate, n)
        out[label] = round((hi - lo) / 2 * 100, 1)
    return out


def cost_at(entry: dict, depth_n: int | None) -> dict:
    size = entry.get("dataset_size")
    if depth_n is None:
        samples = size
    else:
        samples = min(depth_n, size) if size else depth_n
    calls = entry.get("calls_per_sample")
    return {"samples": samples,
            "model_calls": samples * calls if samples and calls else None,
            "ci_halfwidth_pp": interval_halfwidth_pp(samples)}


def plan_benchmark(entry: dict, depth: str, subject_type: str) -> dict:
    return {
        "id": entry["id"], "skill": entry["skill"], "engine": entry.get("engine"),
        "depth": depth, **cost_at(entry, resolve_depth(depth)),
        "at_depth": {name: cost_at(entry, n) for name, n in DEPTHS.items()},
        "needs_judge": entry.get("needs_judge"), "needs_sandbox": entry.get("needs_sandbox"),
        "tier": entry.get("tier"), "verified": bool(entry.get("verified")),
        "reads_as": entry.get("reads_as"), "direction": entry.get("direction"),
        "subject_note": (entry.get("subject_notes") or {}).get(subject_type),
        "note": entry.get("note") or "",
    }


def build_plan(review: dict, catalog: dict, threats: dict, templates: dict,
               depth: str = "standard", tiers: tuple = DEFAULT_TIERS,
               today: str | None = None) -> dict:
    subject = review.get("subject") or {}
    stype = subject.get("type")
    if stype not in TEMPLATE_FOR:
        raise ValueError(f"subject.type {stype!r} has no threat template; expected one of "
                         f"{sorted(TEMPLATE_FOR)}")
    resolve_depth(depth)                       # raises on a bad depth before any work
    template_name = TEMPLATE_FOR[stype]
    template = templates[template_name]
    facts = scope_facts(review)
    entries = catalog.get("benchmarks", [])

    items, gaps = [], []
    for use in template_threats(template, subject.get("feature")):
        threat = threats[use["threat"]]
        covering = [e for e in entries if threat["id"] in e.get("threats", [])
                    and stype in e.get("subjects", [])
                    and e.get("measures", "subject") == "subject"]
        runnable = [e for e in covering if e.get("status") == "available"
                    and e.get("tier") in tiers]
        elsewhere = [e for e in covering if e not in runnable]
        applies, reason = applicability(threat, facts)
        if applies is None:
            gaps.append(f"{threat['id']}: {reason}")
        route = "benchmark" if runnable else threat["fallback"]
        planned = [plan_benchmark(e, depth, stype) for e in runnable]
        caveats = sorted({b["subject_note"] for b in planned if b["subject_note"]})
        items.append({
            "threat": threat["id"], "name": threat["name"],
            "description": threat["description"], "why_here": use["why"],
            "owasp_llm": threat["owasp_llm"], "owasp_agentic": threat["owasp_agentic"],
            "atlas": threat["atlas"],
            "applies": applies, "applies_reason": reason,
            "route": route,
            "route_note": " ".join(caveats) if runnable else threat["fallback_note"],
            "benchmarks": planned,
            "also_exists": [{"id": e["id"], "skill": e["skill"], "status": e.get("status"),
                             "tier": e.get("tier"), "verified": bool(e.get("verified")),
                             "why_not_planned": _why_not(e, tiers)} for e in elsewhere],
            # --- for the reviewer to fill as the review proceeds ---
            "status": "planned", "owner": "", "evidence_ids": [], "result_pointer": None,
        })

    if facts["open_weights"] is None and any(i["threat"] == "supply-chain-model" for i in items):
        gaps.append("supply-chain-model: review.json does not say whether the weights are open")
    for item in items:
        if item["threat"] == "supply-chain-model" and facts["open_weights"] is not None:
            item["route_note"] += (
                " Weights are open in review.json: run the open-weights harvest."
                if facts["open_weights"] else
                " Weights are closed in review.json: only vendor statements can be recorded.")

    active = [i for i in items if i["applies"] is not False]
    return {
        "schema_version": 1,
        "generated": today or dt.date.today().isoformat(),
        "generator": "review-threat-model/scripts/plan.py",
        "review_id": review.get("review_id"),
        "subject": {k: subject.get(k) for k in ("type", "name", "version", "vendor", "feature")},
        "template": template_name,
        "depth": depth,
        "tiers_planned": list(tiers),
        "catalog": {"updated": catalog.get("updated"), "entries": len(entries)},
        "scope": {"tools_attached": facts["tools"], "open_weights": facts["open_weights"],
                  "untrusted_channels": facts["untrusted_channels"]},
        "scope_gaps": gaps,
        "ask": template.get("ask", []),
        "guided_review": template.get("guided_review"),
        "core_benchmark": template.get("core_benchmark"),
        "threats": items,
        # Benchmarks that measure a control the user supplies (a guardrail), not the subject.
        # Never counted as coverage of a threat: the reviewer adds them if the deployment
        # relies on that control.
        "control_benchmarks": [
            {**plan_benchmark(e, depth, stype), "threats": e.get("threats", [])}
            for e in entries if e.get("measures") == "control" and stype in e.get("subjects", [])
            and e.get("status") == "available" and e.get("tier") in tiers],
        "runs": _runs(active),
        "totals": {**{r: sum(1 for i in active if i["route"] == r) for r in ROUTES},
                   "not_applicable": len(items) - len(active)},
    }


def _why_not(entry: dict, tiers: tuple) -> str:
    if entry.get("status") != "available":
        return {"planned": "the skill that would run it is planned, not available",
                "candidate": "named in research; nothing here runs it"}.get(
                    entry.get("status"), f"status {entry.get('status')}")
    return f"tier {entry.get('tier')} is not planned by default"


def _runs(active: list[dict]) -> list[dict]:
    """Benchmarks to run, each once, grouped by the skill that runs them."""
    by_skill: dict[str, dict] = {}
    for item in active:
        for b in item["benchmarks"]:
            run = by_skill.setdefault(b["skill"], {"skill": b["skill"], "depth": b["depth"],
                                                   "benchmarks": {}})
            row = run["benchmarks"].setdefault(b["id"], {
                "id": b["id"], "samples": b["samples"], "model_calls": b["model_calls"],
                "needs_judge": b["needs_judge"], "tier": b["tier"], "threats": []})
            row["threats"].append(item["threat"])
    runs = []
    for run in by_skill.values():
        rows = list(run["benchmarks"].values())
        known = [r["model_calls"] for r in rows if r["model_calls"] is not None]
        runs.append({"skill": run["skill"], "depth": run["depth"], "benchmarks": rows,
                     "samples": sum(r["samples"] or 0 for r in rows),
                     "model_calls": sum(known),
                     "model_calls_unknown_for": [r["id"] for r in rows
                                                 if r["model_calls"] is None],
                     "needs_judge": any(r["needs_judge"] for r in rows)})
    return runs


# --- markdown ---------------------------------------------------------------------------------

def _ids(item: dict) -> str:
    return "; ".join(filter(None, [", ".join(item["owasp_llm"]), ", ".join(item["owasp_agentic"]),
                                   ", ".join(item["atlas"])])) or "—"


def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _width(b: dict) -> str:
    w = b["ci_halfwidth_pp"]
    return f"±{w['at_rate_0.5']} / ±{w['at_rate_0.9']}" if w else "n unknown"


def render_markdown(plan: dict) -> str:
    s = plan["subject"]
    lines = [
        f"# Threat model and test plan — {s.get('name')} ({s.get('version')})", "",
        f"Review `{plan['review_id']}` · subject type `{s.get('type')}`"
        + (f" · feature `{s['feature']}`" if s.get("feature") else "")
        + f" · template `{plan['template']}` · depth `{plan['depth']}` · generated "
          f"{plan['generated']}", "",
        "> This is a skeleton built from the threat template for this subject type and the "
        "benchmark catalogue. The reviewer confirms each threat applies, adds threats the "
        "template lacks, and fills in owners. It states what to measure and how deep. It "
        "does not state what result would be acceptable and it recommends no controls.", "",
        "## Scope this plan was built from", "",
        f"- Tools attached: {_tri(plan['scope']['tools_attached'])}",
        f"- Open weights: {_tri(plan['scope']['open_weights'])}",
        "- Input channels an outsider can write to: "
        + (", ".join(plan["scope"]["untrusted_channels"]) or "none listed in review.json"),
    ]
    if plan["scope_gaps"]:
        lines += ["", "**review.json leaves these open; settle them before running anything:**"]
        lines += [f"- {g}" for g in plan["scope_gaps"]]
    if plan["ask"]:
        lines += ["", "Questions this subject type raises that review.json may not answer:"]
        lines += [f"- {q}" for q in plan["ask"]]

    if plan.get("guided_review"):
        g = plan["guided_review"]
        lines += ["", f"Guided review for this subject type: `{g['skill']}`. {g['note']}"]
    if plan.get("core_benchmark"):
        g = plan["core_benchmark"]
        lines += ["", f"Core benchmark for this subject type: `{g['skill']}`. {g['note']}"]

    active = [i for i in plan["threats"] if i["applies"] is not False]
    lines += ["", "## Threat model", "",
              "Framework ids are given only where they were checked against the primary source; "
              "`—` means no verified match, not that the threat is unrecognised.", "",
              "| Threat | What it is | Why here | OWASP LLM 2026; OWASP Agentic; MITRE ATLAS | Route |",
              "|---|---|---|---|---|"]
    for i in active:
        lines.append(f"| `{i['threat']}` {_cell(i['name'])} | {_cell(i['description'])} | "
                     f"{_cell(i['why_here'])} | {_ids(i)} | {i['route'].replace('_', ' ')}"
                     f"{' (with a caveat, below)' if i['route'] == 'benchmark' and i['route_note'] else ''}"
                     f"{'' if i['applies'] else ' (confirm it applies)'} |")

    t = plan["totals"]
    lines += ["", "## Test plan", "",
              f"{t['benchmark']} covered by a catalogued benchmark · {t['custom_probe']} need a "
              f"custom probe · {t['design_review']} design review only · {t['uncovered']} "
              f"uncovered · {t['not_applicable']} not applicable in this scope", ""]

    lines += [f"### 1. {ROUTE_TITLES['benchmark']}", ""]
    covered = [i for i in active if i["route"] == "benchmark"]
    if covered:
        lines += ["Interval column: half-width of the 95% interval in percentage points at this "
                  "number of tests, if the measured rate turns out near 50% / near 90%. A "
                  "difference smaller than this is not distinguishable from noise.", "",
                  "| Threat | Skill | Benchmark | Depth | Tests | Model calls | 95% interval ± | "
                  "Judge | Tier | Facts verified |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for i in covered:
            for b in i["benchmarks"]:
                lines.append(
                    f"| `{i['threat']}` | {b['skill']} | `{b['id']}` | {b['depth']} | "
                    f"{b['samples'] if b['samples'] else 'unknown'} | "
                    f"{b['model_calls'] if b['model_calls'] is not None else 'varies'} | "
                    f"{_width(b)} | {_tri(b['needs_judge'])} | {b['tier']} | "
                    f"{'yes' if b['verified'] else 'no'} |")
        caveats = sorted({i["route_note"] for i in covered if i["route_note"]})
        if caveats:
            lines += ["", "**Caveat for this subject type:** " + " ".join(caveats)]
        lines += ["", "Runs, each benchmark counted once:", ""]
        for run in plan["runs"]:
            lines.append(
                f"- **{run['skill']}** at depth `{run['depth']}`: "
                + ", ".join(f"`{r['id']}`" for r in run["benchmarks"])
                + f" — {run['samples']} tests, {_calls(run)}"
                + ("; needs a judge model that is not the subject" if run["needs_judge"] else "")
                + ". The skill prints its own cost plan before it runs.")
        notes = {b["id"]: b["note"] for i in covered for b in i["benchmarks"] if b["note"]}
        lines += ["", "What each benchmark measures, and its caveats:", ""]
        lines += [f"- `{bid}` — {note}" for bid, note in notes.items()]
    else:
        lines.append("No available catalogued benchmark covers any threat in this template "
                     "for this subject type. That is a finding: say so in the report.")

    for n, route in enumerate(("custom_probe", "design_review", "uncovered"), 2):
        lines += ["", f"### {n}. {ROUTE_TITLES[route]}", ""]
        rows = [i for i in active if i["route"] == route]
        if not rows:
            lines.append("None.")
            continue
        head = {"custom_probe": "How to probe it",
                "design_review": "What to examine",
                "uncovered": "Why nothing here assesses it"}[route]
        lines += [f"| Threat | {head} | Exists elsewhere, not runnable here today | Owner |",
                  "|---|---|---|---|"]
        for i in rows:
            other = "; ".join(f"`{e['id']}` ({e['skill']}: {e['why_not_planned']})"
                              for e in i["also_exists"]) or "—"
            lines.append(f"| `{i['threat']}` {_cell(i['name'])} | {_cell(i['route_note'])} | "
                         f"{_cell(other)} | |")

    lines += ["", "### Benchmarks for a control the deployment relies on", ""]
    if plan.get("control_benchmarks"):
        lines += ["These measure a control the user supplies, not the subject, so they are not "
                  "counted as coverage above and are not in the runs. Add one only if the "
                  "safeguards recorded in review.json include that control.", ""]
        lines += [f"- `{b['id']}` ({b['skill']}): {b['samples']} tests at depth `{b['depth']}`; "
                  f"bears on {', '.join(f'`{t}`' for t in b['threats'])}. {b['note']}"
                  for b in plan["control_benchmarks"]]
    else:
        lines.append("None catalogued for this subject type.")

    lines += ["", "### Not applicable in this scope", ""]
    ruled_out = [i for i in plan["threats"] if i["applies"] is False]
    lines += [f"- `{i['threat']}` {i['name']} — {i['applies_reason']}." for i in ruled_out] \
        or ["None ruled out by review.json."]

    lines += ["", "## What this plan does not do", "",
              "- It lists the threats in the template for this subject type. A threat specific "
              "to this deployment that the template lacks must be added by the reviewer.",
              "- A benchmark in section 1 measures the threat on a public test set. It does not "
              "show the threat is absent in this deployment.",
              "- Sections 2 to 4 are not measured by any skill here. Until a probe is built or "
              "a review is written up, those threats are not assessed, and the report says so.",
              "- It sets no acceptance criteria. Those are the organisation's, written with "
              "review-criteria.", ""]
    return "\n".join(lines)


def _calls(run: dict) -> str:
    """Model calls of a run, saying so when a benchmark's calls per test are not fixed."""
    unknown = run["model_calls_unknown_for"]
    if unknown and not run["model_calls"]:
        return "model calls not fixed (they depend on the run)"
    return f"about {run['model_calls']} model calls" + (
        f" plus an unknown number for {', '.join(unknown)}" if unknown else "")


def _tri(value) -> str:
    return {True: "yes", False: "no", None: "not stated"}.get(value, str(value))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--review", required=True, help="review.json from review-scope")
    p.add_argument("--catalog", default=str(SKILL / "catalog.json"),
                   help="benchmark catalogue (default: the copy shipped with this skill)")
    p.add_argument("--depth", default="standard",
                   help="smoke | standard | full | N — the depth written into the plan")
    p.add_argument("--include-t2", action="store_true",
                   help="also plan tier T2 (supervised sandbox) benchmarks")
    p.add_argument("--out-dir", help="where to write test-plan.json and test-plan.md "
                                     "(default: next to review.json)")
    args = p.parse_args(argv)
    try:
        review = load_json(Path(args.review))
        catalog = load_json(Path(args.catalog))
        threats, templates = load_references()
        tiers = DEFAULT_TIERS + (("T2",) if args.include_t2 else ())
        plan = build_plan(review, catalog, threats, templates, args.depth, tiers)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out_dir) if args.out_dir else Path(args.review).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "test-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    (out / "test-plan.md").write_text(render_markdown(plan))
    t = plan["totals"]
    print(f"template {plan['template']}: {len(plan['threats'])} threats — "
          f"{t['benchmark']} benchmark, {t['custom_probe']} custom probe, "
          f"{t['design_review']} design review, {t['uncovered']} uncovered, "
          f"{t['not_applicable']} not applicable")
    for run in plan["runs"]:
        print(f"  {run['skill']} @ {run['depth']}: {len(run['benchmarks'])} benchmark(s), "
              f"{run['samples']} tests, {_calls(run)}")
    for gap in plan["scope_gaps"]:
        print(f"  open question: {gap}")
    print(out / "test-plan.json")
    print(out / "test-plan.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
