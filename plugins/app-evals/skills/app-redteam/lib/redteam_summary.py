#!/usr/bin/env python3
"""Summarise an adaptive red-team run, including repeats.

    npx promptfoo redteam eval -c objectives.generated.yaml --repeat 3 --output results.json
    python redteam_summary.py results.json [--json summary.json]

One adaptive run is a single sample of a noisy process, so the attack success rate is
reported over every (objective, repeat) attempt with a 95% Wilson interval, next to how many
objectives were broken at least once and how many gave different outcomes across repeats.
Attempts that errored (attacker, grader or target failure) are excluded and counted.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

_ERROR_REASON = 2  # promptfoo ResultFailureReason.ERROR


def wilson_ci(k, n, z=1.959964):
    if n <= 0:
        return [0.0, 1.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _iter_results(doc):
    r = doc.get("results", doc)
    if isinstance(r, dict):
        r = r.get("results", r)
    if isinstance(r, list):
        yield from r


def _errored(res):
    fr = res.get("failureReason")
    if fr is not None:
        return fr == _ERROR_REASON
    gr = res.get("gradingResult") or {}
    return bool(gr.get("error")) or (bool(res.get("error")) and not gr)


def _objective(res):
    tc = res.get("testCase") or res.get("test") or {}
    meta = tc.get("metadata") or res.get("metadata") or {}
    vars_ = res.get("vars") or tc.get("vars") or {}
    return str(meta.get("goal") or vars_.get("prompt") or vars_.get("query") or "?")


def summarize(doc):
    """Attack succeeded = the grader FAILED the response (the target did what was asked)."""
    per = defaultdict(list)
    errors = 0
    for res in _iter_results(doc):
        if _errored(res):
            errors += 1
            continue
        passed = res.get("success")
        if passed is None:
            passed = (res.get("gradingResult") or {}).get("pass")
        if passed is None:
            errors += 1
            continue
        per[_objective(res)].append(not passed)
    attempts = sum(len(v) for v in per.values())
    successes = sum(sum(v) for v in per.values())
    repeats = max((len(v) for v in per.values()), default=0)
    return {
        "objectives": len(per), "attempts": attempts, "errors_excluded": errors,
        "max_repeats": repeats,
        "attack_success_rate": round(successes / attempts, 4) if attempts else None,
        "ci95": wilson_ci(successes, attempts) if attempts else None,
        "objectives_broken_at_least_once": sum(1 for v in per.values() if any(v)),
        "objectives_with_mixed_outcomes": sum(1 for v in per.values() if any(v) and not all(v)),
        "by_objective": {k: {"succeeded": sum(v), "attempts": len(v)}
                         for k, v in sorted(per.items(), key=lambda kv: (-sum(kv[1]), kv[0]))},
    }


def render(m):
    lines = [f"Attempts: {m['attempts']} over {m['objectives']} objectives "
             f"(up to {m['max_repeats']} repeat(s) each), errors excluded: {m['errors_excluded']}"]
    if not m["attempts"]:
        lines.append("WARNING: nothing was scored. Check the attacker, grader and target; an "
                     "all-error run is not a clean result.")
        return "\n".join(lines)
    lo, hi = m["ci95"]
    lines += [f"Attack success rate: {m['attack_success_rate']:.2f} [95% interval {lo:.2f}–{hi:.2f}]",
              f"Objectives broken at least once: {m['objectives_broken_at_least_once']} of "
              f"{m['objectives']}",
              f"Objectives with different outcomes across repeats: "
              f"{m['objectives_with_mixed_outcomes']}"]
    if m["max_repeats"] < 2:
        lines.append("NOTE: one attempt per objective. Adaptive attacks are noisy; re-run with "
                     "--repeat 3 before quoting the rate.")
    lines.append("By objective (succeeded / attempts):")
    for goal, v in m["by_objective"].items():
        lines.append(f"    {v['succeeded']}/{v['attempts']}  {goal[:100]}")
    return "\n".join(lines)


def main(argv):
    args = list(argv)
    json_out = None
    if "--json" in args:
        i = args.index("--json")
        json_out = args[i + 1]
        del args[i:i + 2]
    if not args:
        print("usage: python redteam_summary.py <promptfoo-results.json> [--json summary.json]",
              file=sys.stderr)
        return 2
    metrics = summarize(json.loads(open(args[0]).read()))
    if json_out:
        with open(json_out, "w") as fh:
            json.dump(metrics, fh, indent=2)
    print(render(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
