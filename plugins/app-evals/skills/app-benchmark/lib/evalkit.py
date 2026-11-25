#!/usr/bin/env python3
"""Small shared helpers every measurement skill uses. Stdlib only, so the vendored copy
runs in any Python.

  depth      smoke / standard / full, the same three names in every skill
  plan       print what a run will cost before it starts
  context    the deployment context a result applies to (surface, harness, safeguards...)
  samples    append rows to the shared samples.jsonl contract
  intervals  95% Wilson interval for a rate
  validity   flags that say whether a measurement can be trusted. They are NOT acceptance
             thresholds: a flag never hides the number and never says a result is good or bad.
  secrets    strip provider credentials from an environment
  family     Holm adjustment when a report makes many comparisons at once
  power      the smallest difference a run of a given size can separate from noise
  repeats    how often a case's outcome changes when it is run again
  plan       the analysis plan, registered before results exist, and departures from it
  provenance fingerprints of the corpus and of the organisation's criteria file
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Samples per benchmark. `smoke` proves the wiring and nothing else: near a 0.9 rate the 95%
# interval is about +/-12 points at n=25 and +/-6 at n=100.
DEPTHS: dict[str, int | None] = {"smoke": 25, "standard": 100, "full": None}

CONTEXT_KEYS = ("surface", "harness", "harness_version", "system_prompt", "tools",
                "safeguards", "data_sensitivity", "autonomy", "notes")


def resolve_depth(spec: str) -> int | None:
    """`smoke`, `standard`, `full`, or a positive integer. None means the whole dataset."""
    if spec in DEPTHS:
        return DEPTHS[spec]
    try:
        n = int(spec)
    except ValueError:
        raise ValueError(f"depth must be one of {sorted(DEPTHS)} or a positive integer") from None
    if n < 1:
        raise ValueError("depth must be a positive integer")
    return n


def print_plan(rows: list[dict], arms: int = 1, file=None,
               comparisons: int | None = None) -> dict:
    """rows: [{name, samples, calls, note?}]. Prints and returns per-arm totals.

    With more than one arm it also prints, per row, the smallest paired difference the run
    can separate from noise (see `power_note`), so a too-small run is visible before it
    starts. `comparisons` is how many paired tests the report will make; by default one per
    row for every arm beyond the baseline."""
    file = file or sys.stderr
    total = {"samples": sum(r["samples"] for r in rows), "calls": sum(r["calls"] for r in rows)}
    print(f"plan: {len(rows)} benchmark(s) x {arms} arm(s); per arm {total['samples']} tests / "
          f"~{total['calls']} model calls", file=file)
    family = comparisons if comparisons is not None else max(0, arms - 1) * len(rows)
    for r in rows:
        print(f"  {r['name']:<40} n={r['samples']:<6} calls~{r['calls']:<7}{r.get('note', '')}",
              file=file)
        if arms > 1 and r["samples"]:
            print(f"  {'':<40} {power_note(r['samples'], family)}", file=file)
    total["comparisons"] = family
    return total


def wilson_ci(rate: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (rate + z * z / (2 * n)) / denom
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts of a paired comparison."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_context(path: str | None = None) -> dict:
    """The `context` object of a review profile (review.json), or {} when there is none.
    Looks at the argument, then $REVIEW_FILE, then ./review.json."""
    for candidate in (path, os.environ.get("REVIEW_FILE"), "review.json"):
        if candidate and Path(candidate).is_file():
            data = json.loads(Path(candidate).read_text())
            ctx = data.get("context", {}) if isinstance(data, dict) else {}
            return {k: ctx[k] for k in CONTEXT_KEYS if ctx.get(k) is not None}
    return {}


def append_samples(path: str | Path, rows: list[dict]) -> None:
    """Append rows to samples.jsonl. Every row needs run, arm, target and sample so that
    denominators include samples with nothing to report."""
    for row in rows:
        missing = [k for k in ("arm", "target", "sample") if k not in row]
        if missing:
            raise ValueError(f"samples row missing {missing}: {row}")
    with open(path, "a") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def validity_flag(name: str, observed: float | None, limit: float, direction: str,
                  meaning: str) -> dict | None:
    """A flag when `observed` is beyond a configurable `limit` ("above" or "below").
    Reported next to the number, which is always shown."""
    if observed is None:
        return None
    tripped = observed > limit if direction == "above" else observed < limit
    return {"flag": name, "observed": observed, "limit": limit, "meaning": meaning} if tripped \
        else None


SCRUB_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "AZURE_", "AWS_")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")
SCRUB_EXACT = ("MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY")


def scrub_provider_credentials(env: dict) -> dict:
    """Drop provider credentials so an unrouted judge fails instead of billing a provider.
    Everything else is kept (including HF_TOKEN, which gated datasets need)."""
    return {k: v for k, v in env.items()
            if k not in SCRUB_EXACT
            and not (k.startswith(SCRUB_PREFIXES) and k.endswith(SCRUB_SUFFIXES))}


# --- many comparisons at once ---------------------------------------------------------------
# The conventional level at which a difference is called unlikely to be noise. A statistical
# convention for separating signal from noise, not an acceptance bar for any result.
SIGNIFICANCE = 0.05


def holm(pvalues: list) -> list:
    """Holm-Bonferroni adjusted p-values, in the input order; None entries stay None.

    A report that tests many arm x benchmark pairs at 0.05 will call some differences real by
    chance alone. Holm keeps the chance of any false call across the whole family at 0.05."""
    idx = [i for i, p in enumerate(pvalues) if p is not None]
    m = len(idx)
    adjusted: list = [None] * len(pvalues)
    running = 0.0
    for rank, i in enumerate(sorted(idx, key=lambda j: pvalues[j])):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = round(running, 6)
    return adjusted


# --- power ----------------------------------------------------------------------------------
def min_detectable(n: int, comparisons: int = 1, alpha: float = SIGNIFICANCE) -> int | None:
    """Fewest cases on which two arms must disagree, all in the same direction, for exact
    McNemar to fall below alpha / comparisons (the strictest step of Holm). Any real
    difference smaller than this cannot be told from noise at this sample size. None when
    even n disagreeing cases would not be enough."""
    target = alpha / max(1, comparisons)
    for d in range(1, n + 1):
        if mcnemar_exact(0, d) < target:
            return d
    return None


def power_note(n: int, comparisons: int = 1) -> str:
    """One line for a plan: how precise a rate is at n, and what difference n can separate."""
    lo, hi = wilson_ci(0.5, n)
    d = min_detectable(n, comparisons)
    family = f" across {comparisons} comparisons" if comparisons > 1 else ""
    sep = (f"two arms must differ on at least {d} cases ({d / n:.0%}), all one way, to be "
           f"separated{family}" if d else f"no difference is separable at n={n}{family}")
    return f"precision: a rate is within about ±{(hi - lo) / 2:.0%} at worst; {sep}"


# --- repeats --------------------------------------------------------------------------------
def repeat_consistency(rows: list[dict], group: tuple = ("arm", "target"),
                       case: str = "sample", repeat: str = "repeat") -> dict:
    """For rows that ran the same case more than once, per group: how many cases repeated,
    the share whose graded outcomes disagree between repeats (the flip rate), and the spread
    of the per-repeat good rates. Rows without a verdict are ignored."""
    by: dict = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        if r.get("good") is None:
            continue
        g = tuple(r.get(k) for k in group)
        by[g][r.get(case)][r.get(repeat, r.get("epoch", 1))] = bool(r["good"])
    out = {}
    for g, cases in by.items():
        multi = {c: reps for c, reps in cases.items() if len(reps) > 1}
        if not multi:
            continue
        flips = sum(1 for reps in multi.values() if len(set(reps.values())) > 1)
        per_rep: dict = defaultdict(list)
        for reps in multi.values():
            for k, v in reps.items():
                per_rep[k].append(v)
        rates = [round(sum(v) / len(v), 4) for _, v in sorted(per_rep.items(), key=lambda kv: str(kv[0]))]
        out["|".join(str(x) for x in g)] = {
            "cases": len(multi), "repeats": max(len(r) for r in multi.values()),
            "flip_rate": round(flips / len(multi), 4), "repeat_rates": rates,
            "spread": round(max(rates) - min(rates), 4) if rates else None}
    return out


# --- saturation -----------------------------------------------------------------------------
def ceiling_flag(good_rates: dict, limit: float) -> dict | None:
    """A validity flag when every arm's share of good outcomes is at or above `limit`.

    A saturated set still catches regressions, but differences between arms on it say
    little; a harder set that keeps the same construct would. `limit` is configurable."""
    rates = [r for r in good_rates.values() if r is not None]
    if not rates or min(rates) < limit:
        return None
    return {"flag": "near_ceiling", "observed": round(min(rates), 4), "limit": limit,
            "meaning": "every arm is at or above this share of good outcomes: the set can "
                       "catch a regression but separates arms poorly; a harder set with the "
                       "same construct would"}


# --- provenance -----------------------------------------------------------------------------
def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(paths) -> str | None:
    """sha256 over the named files (sorted by path), or None when none exist."""
    files = sorted(Path(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)
                   if Path(p).is_file())
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def corpus_record(paths, bundled: bool) -> dict:
    """What corpus a run used. A bundled corpus is public in this repository and may be in a
    model's training data; a corpus the user supplies is recorded as private."""
    return {"sha256": fingerprint(paths), "visibility": "public" if bundled else "private",
            "note": ("bundled with the skill and public: may be in training data, so read "
                     "scores as comparisons between arms") if bundled else
                    "supplied by the user; not published by this repository"}


def criteria_record(path: str | Path | None = None) -> dict | None:
    """The organisation's own criteria file (from review-criteria), fingerprinted when the
    plan is registered, so a report can show the criteria predate the results."""
    for candidate in (path, os.environ.get("CRITERIA_FILE"), "criteria.json"):
        if candidate and Path(candidate).is_file():
            return {"path": str(candidate), "sha256": fingerprint(candidate)}
    return None


def judge_id(model: str | None, rubric_version: str | None = None) -> str | None:
    """How a judge is named in samples rows: the model, and the rubric version when the skill
    versions its rubric. Scores from different judges are not compared."""
    if not model:
        return None
    return f"{model}|rubric:{rubric_version}" if rubric_version else model


# --- analysis plan --------------------------------------------------------------------------
PLAN_FILE = "plan.json"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _has_results(exp: Path) -> bool:
    s = exp / "samples.jsonl"
    return s.is_file() and s.stat().st_size > 0


def register_plan(exp_dir: str | Path, plan: dict, reason: str | None = None) -> dict:
    """Write the analysis plan to <exp>/plan.json before any result exists, and keep it.

    `plan` names what the run will measure and how it will be read, for example arms,
    baseline, measures (benchmarks or threats), depth, seed, repeats, judge, corpus, slices,
    and the organisation's criteria file if it has one (`criteria_record`). Thresholds are
    never part of it unless the organisation's own criteria file holds them.

    Registering the same plan again changes nothing. A different plan is kept as an
    amendment, with the reason given (or a note that none was), and whether results already
    existed: the report lists every amendment as a departure from the registered plan."""
    exp = Path(exp_dir)
    exp.mkdir(parents=True, exist_ok=True)
    path = exp / PLAN_FILE
    after = _has_results(exp)
    if path.is_file():
        doc = json.loads(path.read_text())
        current = doc["amendments"][-1]["plan"] if doc.get("amendments") else doc["plan"]
        if _canonical(current) == _canonical(plan):
            return doc
        doc.setdefault("amendments", []).append({
            "at": _now(), "after_results": after, "plan": plan,
            "reason": reason or "changed at run time; no reason given"})
    else:
        doc = {"registered_at": _now(), "registered_before_results": not after,
               "sha256": _sha256_bytes(_canonical(plan).encode()), "plan": plan,
               "amendments": []}
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def load_plan(exp_dir: str | Path) -> dict | None:
    path = Path(exp_dir) / PLAN_FILE
    return json.loads(path.read_text()) if path.is_file() else None


def plan_deviations(doc: dict | None, observed: dict) -> list[str]:
    """What differs between the plan as first registered and what was run or reported.
    Only keys the plan names are compared; lists are compared as sets."""
    if not doc:
        return []
    plan, out = doc["plan"], []
    for key, planned in plan.items():
        if key not in observed:
            continue
        seen = observed[key]
        same = (set(map(str, planned)) == set(map(str, seen))
                if isinstance(planned, list) and isinstance(seen, list) else planned == seen)
        if not same:
            out.append(f"`{key}`: planned {planned!r}, observed {seen!r}")
    for a in doc.get("amendments", []):
        when = "after results existed" if a.get("after_results") else "before results"
        out.append(f"plan amended {a['at']} ({when}): {a['reason']}")
    return out


def plan_section(doc: dict | None, observed: dict) -> list[str]:
    """Markdown lines for a report's analysis-plan section."""
    if not doc:
        return ["## Analysis plan", "",
                "- No plan was registered before this run, so the comparisons below were "
                "chosen without one on record."]
    when = ("before any result existed" if doc.get("registered_before_results")
            else "after results already existed")
    lines = ["## Analysis plan", "",
             f"Registered {doc['registered_at']}, {when} (sha256 `{doc['sha256'][:12]}`).", ""]
    devs = plan_deviations(doc, observed)
    lines += [f"- {d}" for d in devs] if devs else \
        ["- No departures: the run and this report match the registered plan."]
    crit = doc["plan"].get("criteria")
    if crit:
        lines += ["", f"The organisation's criteria file `{crit.get('path')}` was fingerprinted "
                  f"at registration (sha256 `{str(crit.get('sha256'))[:12]}`)."]
    return lines


# --- command line, for skills whose runs are driven from the shell (promptfoo) ----------------
def main(argv: list[str] | None = None) -> int:
    """python evalkit.py plan <exp> --arms a,b --measures x,y [--baseline a] [--depth N]
                              [--seed S] [--repeats N] [--judge J] [--corpus FILE ...]
                              [--bundled] [--reason TEXT]
    python evalkit.py power <n> [--comparisons M]
    python evalkit.py show-plan <exp>"""
    import argparse
    ap = argparse.ArgumentParser(prog="evalkit.py", description="plan registration and power")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="register the analysis plan for an experiment folder")
    pl.add_argument("exp")
    pl.add_argument("--arms", required=True)
    pl.add_argument("--measures", required=True)
    pl.add_argument("--baseline")
    pl.add_argument("--depth")
    pl.add_argument("--seed")
    pl.add_argument("--repeats", type=int, default=1)
    pl.add_argument("--judge")
    pl.add_argument("--corpus", nargs="*", default=[])
    pl.add_argument("--bundled", action="store_true", help="the corpus ships with the skill")
    pl.add_argument("--reason")
    pw = sub.add_parser("power", help="precision and smallest separable difference at n")
    pw.add_argument("n", type=int)
    pw.add_argument("--comparisons", type=int, default=1)
    sp = sub.add_parser("show-plan", help="print the registered plan section")
    sp.add_argument("exp")
    a = ap.parse_args(argv)
    if a.cmd == "power":
        print(power_note(a.n, a.comparisons))
        return 0
    if a.cmd == "show-plan":
        print("\n".join(plan_section(load_plan(a.exp), {})))
        return 0
    plan = {"arms": [x for x in a.arms.split(",") if x], "measures": [x for x in a.measures.split(",") if x],
            "baseline": a.baseline, "depth": a.depth, "seed": a.seed, "repeats": a.repeats,
            "judge": a.judge, "corpus": corpus_record(a.corpus, a.bundled) if a.corpus else None,
            "criteria": criteria_record()}
    doc = register_plan(a.exp, plan, a.reason)
    print(Path(a.exp) / PLAN_FILE, "registered", doc["registered_at"],
          f"({len(doc.get('amendments', []))} amendment(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
