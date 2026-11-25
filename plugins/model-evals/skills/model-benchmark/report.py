#!/usr/bin/env python3
"""Compare models from one or more model-benchmark runs.

    python report.py <EXP>/results/results.json [earlier/results.json ...] \
        [--baseline <model>] [--json <EXP>/summary.json] > <EXP>/summary.md

Pass results from an earlier run to compare a new model against it; the report refuses to
compare runs made at a different depth or seed, because they did not see the same samples.

After the shared report, a breakdown of the multi-turn rows (mt_misuse, mt_legitimate) by
topic, persona, tactic and situation, and by each judge criterion, read from the samples.jsonl
beside each results.json, with 95% Wilson intervals. No thresholds.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import evalkit  # noqa: E402
import inspect_report  # noqa: E402
import inspect_suite as suite  # noqa: E402
import mt_checks  # noqa: E402

SLICES = ("topic", *mt_checks.FACTORS)
CRITERIA = (*mt_checks.DIMENSIONS, "opening_not_followed")


def result_paths(argv: list[str]) -> list[str]:
    paths, it = [], iter(argv)
    for arg in it:
        if arg in ("--baseline", "--json", "--title"):
            next(it, None)
        else:
            paths.append(arg)
    return paths


def multiturn_rows(paths: list[str]) -> list[dict]:
    rows = []
    for p in paths:
        samples = Path(p).with_name("samples.jsonl")
        if samples.is_file():
            rows += [r for r in map(json.loads, filter(str.strip, samples.read_text().splitlines()))
                     if r.get("target") in mt_checks.CHECK_IDS]
    return rows


def share(values: list) -> str:
    """'rate [lo–hi] k/n' over the values that are not None."""
    graded = [bool(v) for v in values if v is not None]
    if not graded:
        return "— 0/0"
    k, n = sum(graded), len(graded)
    lo, hi = evalkit.wilson_ci(k / n, n)
    return f"{k / n:.2f} [{lo:.2f}–{hi:.2f}] {k}/{n}"


def breakdown(rows: list[dict]) -> str:
    if not rows:
        return ""
    topic_of = mt_checks.topics()
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    head = "| " + " | ".join(arms) + " |"
    rule = "|---" * len(arms) + "|"
    out = ["", "## Multi-turn lane: breakdown", "",
           "Each row is one conversation (one sample in one epoch). The good share is computed "
           "over conversations with a verdict; conversations without one (a score other than "
           "1 or 10, or an opening the auditor did not send verbatim) are counted as "
           "unresolved and left out. Cells are small: read the intervals. At standard and full "
           "depth the slices are crossed by design (situation varies only at full), so a "
           "difference between levels of one slice is not explained by another; unresolved "
           "conversations and smoke runs break that balance. No thresholds.", ""]
    for check in mt_checks.CHECK_IDS:
        mine = [r for r in rows if r["target"] == check]
        if not mine:
            continue
        c = suite.BY_ID[check]
        out += [f"### `{check}` — {c.reads_as}", ""]
        unresolved = []
        for a in arms:
            ar = [r for r in mine if r["arm"] == a]
            skipped = sum(1 for r in ar if (r.get("criteria") or {}).get("opening_not_followed"))
            unresolved.append(f"`{a}` {sum(r['good'] is None for r in ar)}/{len(ar)} "
                              f"(opening not followed: {skipped})")
        out += ["Unresolved: " + "; ".join(unresolved) + ".", "",
                "| Slice | Level " + head, "|---|---" + rule]
        for sl in SLICES:
            levels: dict = defaultdict(lambda: defaultdict(list))
            for r in mine:
                spec = str(r["sample"]).split(":")[0]
                level = (topic_of.get(spec, spec) if sl == "topic"
                         else (r.get("factors") or {}).get(sl, "?"))
                levels[level][r["arm"]].append(r["good"])
            for level in sorted(levels):
                out.append(f"| {sl} | {level} | "
                           + " | ".join(share(levels[level][a]) for a in arms) + " |")
        out += ["", "Criteria: share of conversations where the judge answered yes, over the "
                "conversations where it answered 1 or 10.", "",
                "| Criterion " + head, "|---" + rule]
        for crit in CRITERIA:
            out.append(f"| {crit} | " + " | ".join(
                share([(r.get("criteria") or {}).get(crit) for r in mine if r["arm"] == a])
                for a in arms) + " |")
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    mt_checks.register(suite)   # the shared report lists only checks the suite knows
    rc = inspect_report.main([*argv, "--title", "model-benchmark summary"])
    if rc == 0:
        print(breakdown(multiturn_rows(result_paths(argv))), end="")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
