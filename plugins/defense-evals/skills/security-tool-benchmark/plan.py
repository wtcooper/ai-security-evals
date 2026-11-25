#!/usr/bin/env python3
"""Register an experiment's analysis plan before any tool runs, and show what the run can
detect. Every kind uses it once per experiment, right after `new_experiment.sh`.

  python3 plan.py "$EXP" --kind code|extension|pentest --arms <tool1>,<tool2> \
      [--baseline <tool1>] --benchmark <set> --depth smoke|standard|full --targets N \
      [--repeats 1 | --repeats <llm-tool>=3,<tool2>=1] [--corpus <ground_truth|labels>.jsonl] \
      [--private] [--seed 0] [--ceiling 0.95] [--max-minutes 30] [--scope <EXP>/scope.txt] \
      [--reason "<why the plan changed>"]

Writes <EXP>/plan.json (lib/evalkit.register_plan) and prints targets x tools x repeats with,
per set, the smallest paired difference the run can separate. Registering the same plan again
changes nothing; a different plan is kept as an amendment, which every report lists.

The kind reports (code/match.py, extension/score_assets.py, pentest/score.py) import
`read_first` and `plan_lines` from here, so validity notes and the plan section read the same
in all three. Nothing here is an acceptance threshold.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import evalkit  # noqa: E402

SCORING = {"code": "ground-truth match (code/match.py)",
           "extension": "labelled assets (extension/score_assets.py)",
           "pentest": "per-target oracle (pentest/validate.py)"}
DEFAULT_REPEATS = {"code": 1, "extension": 5, "pentest": 3}


def parse_repeats(spec: str | None, arms: list[str], kind: str) -> dict:
    """`3` for every arm, or `tool=3,other=1` (unnamed arms get the kind's default)."""
    default = DEFAULT_REPEATS[kind]
    if spec and "=" not in spec:
        return {a: int(spec) for a in arms}
    out = {a: default for a in arms}
    for part in (spec or "").split(","):
        if part.strip():
            name, n = part.split("=", 1)
            if name not in out:
                raise ValueError(f"--repeats names {name!r}, which is not an arm")
            out[name] = int(n)
    return out


def build_plan(a: argparse.Namespace) -> dict:
    arms = [x for x in a.arms.split(",") if x]
    plan = {"kind": a.kind, "arms": arms, "baseline": a.baseline or arms[0],
            "measures": [a.benchmark], "depth": a.depth, "targets": a.targets,
            "seed": a.seed, "repeats": parse_repeats(a.repeats, arms, a.kind),
            "judge": None, "scoring": SCORING[a.kind], "ceiling": a.ceiling,
            "corpus": None, "criteria": evalkit.criteria_record()}
    if a.corpus:
        plan["corpus"] = evalkit.corpus_record(a.corpus, bundled=not a.private)
        if not a.private:
            plan["corpus"]["note"] = ("a public set: a model-backed tool may have seen it in "
                                      "training, so read the contamination strata")
    if a.kind == "pentest":
        plan["max_minutes"] = a.max_minutes
        scope = Path(a.scope) if a.scope else Path(a.exp) / "scope.txt"
        plan["scope"] = {"path": str(scope), "sha256": evalkit.fingerprint(scope)}
    return plan


def preview(plan: dict, file=None) -> dict:
    """Cost before compute: tool runs per arm, and what a run this size can separate."""
    file = file or sys.stderr
    n, reps = plan["targets"], plan["repeats"]
    rows = [{"name": m, "samples": n, "calls": n * max(reps.values()),
             "note": "  (tool runs, at most)"} for m in plan["measures"]]
    total = evalkit.print_plan(rows, arms=len(plan["arms"]), file=file)
    print("  tool runs per arm: " + ", ".join(f"{a} {n * r}" for a, r in reps.items())
          + (f"; each pentest run is capped at {plan['max_minutes']} min"
             if plan.get("max_minutes") else ""), file=file)
    return total


# --- shared by the three kind reports -------------------------------------------------------
def find_plan(*paths) -> Path | None:
    """The experiment folder holding plan.json: an explicit folder or file, else the folder of
    the first input that has one beside it."""
    for p in paths:
        if not p:
            continue
        d = Path(p) if Path(p).is_dir() else Path(p).parent
        if (d / evalkit.PLAN_FILE).is_file():
            return d
    return None


def read_first(good_rates: dict, limit: float, repeats: dict | None = None,
               extra: list[str] | None = None, unit: str = "cases") -> list[str]:
    """Markdown lines for a 'Read first' section. `good_rates` is {measure: {arm: rate}};
    a `near_ceiling` validity flag is raised per measure where every arm is at or above
    `limit` (only when two or more arms are compared). `repeats` is the output of
    evalkit.repeat_consistency keyed by arm. Flags never hide a number."""
    notes = list(extra or [])
    for measure, rates in good_rates.items():
        flag = evalkit.ceiling_flag(rates, limit) if len(rates) > 1 else None
        if flag:
            notes.append(f"- `{measure}`: validity flag `near_ceiling` (lowest arm "
                         f"{flag['observed']:.2f}, limit {limit}) — {flag['meaning']}.")
    for arm, r in (repeats or {}).items():
        per = ", ".join(f"{x:.2f}" for x in r["repeat_rates"])
        notes.append(f"- `{arm}`: {r['flip_rate']:.0%} of {r['cases']} {unit} changed outcome "
                     f"across {r['repeats']} runs (per-run rate {per}).")
    return ["## Read first", ""] + (notes or ["- Nothing: no validity flag was raised."]) + [""]


def plan_lines(exp, observed: dict) -> list[str]:
    """The '## Analysis plan' section, or a line saying none was registered."""
    doc = evalkit.load_plan(exp) if exp else None
    return [""] + evalkit.plan_section(doc, observed) + [""]


def observed_from_runs(runs: list[dict]) -> dict:
    """What actually ran, from <EXP>/runs.jsonl: arms, distinct targets, repeats per arm."""
    if not runs:
        return {}
    reps: dict = {}
    for r in runs:
        reps[r["arm"]] = max(reps.get(r["arm"], 0), int(r.get("tool_run") or 1))
    out = {"arms": sorted(reps), "targets": len({r["target"] for r in runs}), "repeats": reps}
    limits = {r.get("max_minutes") for r in runs if "max_minutes" in r}
    if len(limits) == 1:
        out["max_minutes"] = limits.pop()
    return out


def load_jsonl(path) -> list[dict]:
    p = Path(path) if path else None
    if not p or not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exp")
    ap.add_argument("--kind", required=True, choices=sorted(SCORING))
    ap.add_argument("--arms", required=True, help="comma list of tool arms")
    ap.add_argument("--baseline", default=None, help="default: the first arm")
    ap.add_argument("--benchmark", required=True, help="the target set (one per experiment)")
    ap.add_argument("--depth", default="standard", help="smoke | standard | full")
    ap.add_argument("--targets", type=int, required=True,
                    help="targets (or assets) per arm; a fixed snapshot counts as its own target")
    ap.add_argument("--repeats", default=None, help="N, or tool=N,... (default per kind: "
                    + ", ".join(f"{k} {v}" for k, v in DEFAULT_REPEATS.items()) + ")")
    ap.add_argument("--corpus", nargs="*", default=None,
                    help="ground_truth.jsonl / labels.jsonl to fingerprint")
    ap.add_argument("--private", action="store_true",
                    help="the corpus is the user's own, not a public set")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--ceiling", type=float, default=0.95,
                    help="validity limit for the near_ceiling flag in the reports")
    ap.add_argument("--max-minutes", type=float, default=30,
                    help="pentest: wall-clock limit per tool run")
    ap.add_argument("--scope", default=None, help="pentest: scope file (default <EXP>/scope.txt)")
    ap.add_argument("--reason", default=None, help="why a registered plan is being changed")
    a = ap.parse_args(argv)
    plan = build_plan(a)
    preview(plan)
    doc = evalkit.register_plan(a.exp, plan, reason=a.reason)
    state = (f"amended ({len(doc['amendments'])} amendment(s))" if doc.get("amendments")
             else "registered")
    print(f"plan {state}: {Path(a.exp) / evalkit.PLAN_FILE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
