"""Turn runner output into summary.md / summary.json: a table of arms, a paired comparison
against a baseline arm, and the validity flags, which are listed before any number is read.

No acceptance thresholds: the report says what was measured and how certain it is.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evalkit  # noqa: E402
import inspect_suite as suite  # noqa: E402


def load_run(results_path: str) -> dict:
    """results.json plus the samples.jsonl beside it."""
    path = Path(results_path)
    run = json.loads(path.read_text())
    samples = path.with_name("samples.jsonl")
    run["samples"] = ([json.loads(line) for line in samples.read_text().splitlines() if line]
                      if samples.is_file() else [])
    return run


def cell(row: dict | None) -> str:
    if row is None:
        return "—"
    if row["status"] != "ok":
        return f"**{row['status']}**"
    text = f"{row['value']:.2f}"
    if row.get("ci95"):
        text += f" [{row['ci95'][0]:.2f}–{row['ci95'][1]:.2f}]"
    text += f" n={row.get('samples_completed')}"
    return text + (" ⚑" if row.get("flags") else "")


def paired(samples: list[dict], check: str, base: str, other: str) -> dict | None:
    """Paired comparison of two arms on the samples both graded. `delta` is the change in the
    good-outcome rate (other minus baseline); positive means the other arm did better."""
    def outcomes(arm):
        return {(s["sample"], s.get("epoch", 1)): s["good"] for s in samples
                if s["target"] == check and s["arm"] == arm and s["good"] is not None}
    a, b = outcomes(base), outcomes(other)
    keys = sorted(set(a) & set(b))
    if not keys:
        return None
    worse = sum(1 for k in keys if a[k] and not b[k])    # baseline good, other not
    better = sum(1 for k in keys if b[k] and not a[k])   # other good, baseline not
    return {"check": check, "baseline": base, "arm": other, "n": len(keys),
            "delta": round((better - worse) / len(keys), 4), "better": better, "worse": worse,
            "p": round(evalkit.mcnemar_exact(worse, better), 4)}


def summarize(runs: list[dict], baseline: str | None = None) -> dict:
    rows = [row for r in runs for row in r["rows"]]
    samples = [s for r in runs for s in r.get("samples", [])]
    arms = list(dict.fromkeys(row["arm"] for row in rows))
    checks = [c for c in suite.CHECKS if any(row["check"] == c.id for row in rows)]
    by = {(row["arm"], row["check"]): row for row in rows}
    base = baseline or (arms[0] if arms else None)
    comparisons = []
    for c in checks:
        for arm in arms:
            usable = all(by.get((x, c.id), {}).get("paired_ok") for x in (base, arm))
            if arm != base and usable:
                result = paired(samples, c.id, base, arm)
                if result:
                    comparisons.append(result)
    settings = sorted({(str(r.get("depth")), str(r.get("seed"))) for r in runs})
    return {"arms": arms, "baseline": base, "checks": [c.id for c in checks],
            "settings": settings, "comparable": len(settings) <= 1,
            "judge": runs[0].get("judge") if runs else None,
            "context": runs[0].get("context") if runs else {},
            "cells": {f"{a}|{c.id}": by.get((a, c.id)) for a in arms for c in checks},
            "comparisons": comparisons,
            "flags": [{"arm": row["arm"], "check": row["check"], **f}
                      for row in rows for f in row.get("flags", [])],
            "failures": [{"arm": row["arm"], "check": row["check"], "status": row["status"],
                          "error": row.get("error")} for row in rows if row["status"] != "ok"]}


def render(runs: list[dict], baseline: str | None = None, title: str = "summary") -> str:
    s = summarize(runs, baseline)
    by_id = suite.BY_ID
    lines = [f"# {title}", ""]
    if not s["comparable"]:
        lines += [f"> **Not comparable:** inputs mix depth/seed settings {s['settings']}. "
                  "Re-run with the same --depth and --seed before comparing arms.", ""]
    else:
        depth, seed = s["settings"][0] if s["settings"] else ("?", "?")
        lines += [f"depth `{depth}` · seed `{seed}` · judge `{s['judge']}`", ""]
    ctx = {k: v for k, v in (s["context"] or {}).items() if v}
    if ctx:
        lines += ["Context: " + " · ".join(f"{k} `{v}`" for k, v in ctx.items()), ""]

    lines += ["## Read first: what did not produce a trustworthy number", ""]
    notes = [f"- `{f['arm']}` / `{f['check']}`: **{f['status']}** — {f['error'] or 'no score'}"
             for f in s["failures"]]
    for f in s["flags"]:
        seen = "" if f.get("observed") is None else (
            f" (observed {f['observed']}, validity limit {f['limit']})")
        notes.append(f"- `{f['arm']}` / `{f['check']}`: validity flag `{f['flag']}`{seen} — "
                     f"{f['meaning']}.")
    lines += notes or ["- Nothing: every check produced a score and raised no validity flag."]

    lines += ["", "## Results", "",
              "Raw rate [95% Wilson interval] n. ↑ higher is better, ↓ lower is better. "
              "⚑ a validity flag applies (listed above).", "",
              "| Dimension | Check | Reads as | | " + " | ".join(s["arms"]) + " |",
              "|---|---|---|---|" + "---|" * len(s["arms"])]
    for cid in s["checks"]:
        c = by_id[cid]
        arrow = "↑" if c.direction == suite.HIGHER else "↓"
        lines.append(f"| {c.dimension} | `{c.id}` | {c.reads_as} | {arrow} | "
                     + " | ".join(cell(s["cells"][f"{a}|{cid}"]) for a in s["arms"]) + " |")

    lines += ["", f"## Paired comparison against `{s['baseline']}`", ""]
    if len(s["arms"]) < 2:
        lines.append("- Single arm; nothing to compare.")
    elif not s["comparisons"]:
        lines.append("- No paired comparison available (no samples graded in both arms).")
    else:
        lines += ["Same samples in both arms. Δ is the change in the share of good outcomes "
                  "(arm minus baseline; positive = the arm did better). p is exact McNemar on "
                  "the samples where the two arms disagree.", "",
                  "| Check | Arm | n | Δ good outcomes | arm better / worse | p |",
                  "|---|---|---|---|---|---|"]
        for c in s["comparisons"]:
            lines.append(f"| `{c['check']}` | {c['arm']} | {c['n']} | {c['delta']:+.2f} | "
                         f"{c['better']} / {c['worse']} | {c['p']:.3f} |")

    lines += ["", "## What each check measures", ""]
    lines += [f"- `{cid}` — {by_id[cid].reads_as}. {by_id[cid].note}" for cid in s["checks"]]
    lines += ["", "Public benchmarks are in training data: read scores as comparative between "
              "arms, not as absolute levels."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """report <results.json> [more.json ...] [--baseline ARM] [--json OUT] [--title T]"""
    paths, baseline, json_out, title = [], None, None, "summary"
    it = iter(argv)
    for arg in it:
        if arg == "--baseline":
            baseline = next(it)
        elif arg == "--json":
            json_out = next(it)
        elif arg == "--title":
            title = next(it)
        else:
            paths.append(arg)
    if not paths:
        print(main.__doc__, file=sys.stderr)
        return 2
    runs = [load_run(p) for p in paths]
    if json_out:
        Path(json_out).write_text(json.dumps(summarize(runs, baseline), indent=2))
    print(render(runs, baseline, title), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
