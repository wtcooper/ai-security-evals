#!/usr/bin/env python3
"""Rebuild the summary of a coding-guidance-benchmark run from its samples.jsonl.

    python report.py <EXP>/results [--baseline baseline] [--json <EXP>/summary.json] \
        [--ceiling 0.95] > <EXP>/summary.md

The runner already writes summary.md and summary.json with the same functions; use this to
re-read a run, or to name a different arm as the baseline.

On top of lib/stats.py's per-arm rates and paired differences, this adds what concerns the
measurement as a whole: every McNemar p Holm-adjusted across the report, how often a task's
outcome flipped between repeats, a near-ceiling flag per metric, and the analysis plan the
run registered (plan.json) with any departure from it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import arms as arms_lib  # noqa: E402
import evalkit  # noqa: E402
import stats  # noqa: E402

CEILING = 0.95          # validity limit for the near-ceiling flag; --ceiling changes it
SHOW_FLIPPED = 10       # flipped task ids listed per arm in summary.md (all are in the JSON)
PAIRED_HEADER = ("| Arm | Metric | Tasks | Difference [95% bootstrap over tasks] | "
                 "Good under arm only | Good under baseline only | Exact McNemar p |")


def load(results: Path) -> tuple[list[dict], dict]:
    samples = results / "samples.jsonl" if results.is_dir() else results
    rows = [json.loads(line) for line in samples.read_text().splitlines() if line.strip()]
    run_path = samples.parent / "run.json"
    run = json.loads(run_path.read_text()) if run_path.is_file() else {}
    return rows, run


def _repeat(row: dict) -> int:
    """The repeat index: `repeat`, or `sample` in rows written before `repeat` existed."""
    return int(row.get("repeat", row.get("sample", 0)))


def build(rows: list[dict], run: dict, baseline: str = arms_lib.BASELINE,
          ceiling: float = CEILING) -> dict:
    """stats.summarise, plus Holm-adjusted p-values, repeat flips and near-ceiling flags."""
    summary = stats.summarise(rows, run.get("arms"), baseline, run.get("seed", 0))
    # Holm across every McNemar test the report prints: every cell, arm and metric.
    family = [c[m] for cell in summary["cells"] for c in cell["comparisons"]
              for m in stats.METRICS if c[m].get("mcnemar_p") is not None]
    for test, adj in zip(family, evalkit.holm([t["mcnemar_p"] for t in family])):
        test["mcnemar_p_holm"] = adj
    summary["comparison_family"] = len(family)
    summary["ceiling"] = ceiling
    for cell in summary["cells"]:
        mine = [r for r in rows if (r.get("harness"), r.get("model"))
                == (cell["harness"], cell["model"])]
        cell["repeats"], cell["flipped_tasks"] = {}, {}
        for metric in stats.METRICS:
            view = [{"arm": r["arm"], "target": metric, "sample": r["target"],
                     "repeat": _repeat(r), "good": r.get(metric)} for r in mine]
            for key, value in evalkit.repeat_consistency(view).items():
                arm = key.split("|", 1)[0]
                cell["repeats"].setdefault(arm, {})[metric] = value
        for arm in sorted({r["arm"] for r in mine}):
            outcomes: dict = {}
            for r in mine:
                if r["arm"] == arm and r.get("correct_and_secure") is not None:
                    outcomes.setdefault(r["target"], set()).add(bool(r["correct_and_secure"]))
            flipped = sorted(t for t, seen in outcomes.items() if len(seen) > 1)
            if flipped:
                cell["flipped_tasks"][arm] = flipped
        cell["ceiling_flags"] = []
        for metric in stats.METRICS:
            flag = evalkit.ceiling_flag({a["arm"]: a[metric]["rate"] for a in cell["arms"]},
                                        ceiling)
            if flag:
                cell["ceiling_flags"].append({"metric": metric, **flag})
    return summary


def observed(summary: dict, run: dict, rows: list[dict]) -> dict:
    """What ran and was reported, in the plan's terms, for the departures check."""
    return {"arms": sorted({r["arm"] for r in rows}), "baseline": summary["baseline"],
            "depth": run.get("depth"), "seed": run.get("seed"), "repeats": run.get("repeats"),
            "measures": list(stats.METRICS)}


def _section_end(lines: list[str], start: int) -> int:
    """Index of the next `## ` heading after `start`, or the end."""
    return next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
                len(lines))


def render(summary: dict, run: dict, plan: dict | None, rows: list[dict]) -> str:
    """stats.render with the additions of `build`, each placed in the section it belongs to."""
    lines = stats.render(summary, run).split("\n")

    # Read first: near-ceiling flags, then the analysis plan as its own section.
    top = lines.index("## Read first")
    end = _section_end(lines, top)
    notes = [f"- `{c['harness']}` / `{c['model']}`: `{f['metric'].replace('_', ' ')}` is near "
             f"the ceiling (validity flag `{f['flag']}`: every arm at or above {f['limit']}, "
             f"lowest {f['observed']:.2f}). The tasks can catch a regression but separate arms "
             "poorly; a harder task set would."
             for c in summary["cells"] for f in c["ceiling_flags"]]
    if notes and "- Nothing to flag." in lines[top:end]:
        lines.remove("- Nothing to flag.")
        end -= 1
    lines[end - 1:end - 1] = notes
    end += len(notes)
    lines[end:end] = evalkit.plan_section(plan, observed(summary, run, rows)) + [""]

    # Each cell: a Holm column on the paired table, and a Repeats table before Cost.
    cells = iter(summary["cells"])
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## Harness "):
            cell = next(cells)
        if line == PAIRED_HEADER:
            tests = [c[m] for c in cell["comparisons"] for m in stats.METRICS]
            out += [line + " p (Holm) |", lines[i + 1] + "---|"]
            for k, test in enumerate(tests):
                adj = test.get("mcnemar_p_holm")
                out.append(lines[i + 2 + k] + (" n/a |" if adj is None else f" {adj:.4f} |"))
            i += 2 + len(tests)
            continue
        if line.startswith("A per-task outcome is good when a strict majority"):
            out += [line + " `p (Holm)` is adjusted across all "
                    f"{summary['comparison_family']} McNemar tests in this report (every arm, "
                    "metric and harness/model cell); call a difference unlikely to be noise "
                    f"only when it is below {evalkit.SIGNIFICANCE}. That is a statistical "
                    "separation, not a verdict on the arm."]
            i += 1
            continue
        if line == "### Cost" and cell["repeats"]:
            out += repeats_section(cell)
        out.append(line)
        i += 1
    return "\n".join(out)


def repeats_section(cell: dict) -> list[str]:
    L = ["### Repeats: how often a task's outcome flipped", "",
         "Over tasks run more than once under the arm: the share whose outcome was not the same "
         "in every repeat (flip rate), the rate in each repeat, and the spread between them. A "
         "flip rate of the same size under the baseline and the placebo is the noise floor.", "",
         "| Arm | Metric | Tasks repeated | Repeats | Flip rate | Rate per repeat | Spread |",
         "|---|---|---|---|---|---|---|"]
    order = [a["arm"] for a in cell["arms"]]
    for arm in order:
        for metric, c in cell["repeats"].get(arm, {}).items():
            L.append(f"| {arm} | {metric.replace('_', ' ')} | {c['cases']} | {c['repeats']} | "
                     f"{c['flip_rate']:.2f} | {', '.join(f'{x:.2f}' for x in c['repeat_rates'])} "
                     f"| {c['spread']:.2f} |")
    for arm in order:
        flipped = cell["flipped_tasks"].get(arm)
        if flipped:
            more = len(flipped) - SHOW_FLIPPED
            L.append("")
            L.append(f"Tasks whose correct-and-secure outcome flipped under `{arm}`: "
                     + ", ".join(f"`{t}`" for t in flipped[:SHOW_FLIPPED])
                     + (f" and {more} more (all in summary.json)" if more > 0 else "") + ".")
    return L + [""]


def summary_json(summary: dict, run: dict, plan: dict | None, rows: list[dict]) -> dict:
    return {"run": {k: v for k, v in run.items() if k not in ("tasks", "header")}, **summary,
            "plan_deviations": evalkit.plan_deviations(plan, observed(summary, run, rows))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("results", help="the run's output directory, or its samples.jsonl")
    p.add_argument("--baseline", default=arms_lib.BASELINE, help="arm to compare the others against")
    p.add_argument("--json", help="also write the summary as JSON here")
    p.add_argument("--ceiling", type=float, default=CEILING,
                   help="validity flag: every arm at or above this rate on a metric "
                        "(default %(default)s)")
    args = p.parse_args(argv)
    rows, run = load(Path(args.results))
    if not rows:
        print("no rows in samples.jsonl", file=sys.stderr)
        return 1
    results = Path(args.results)
    plan = evalkit.load_plan(results if results.is_dir() else results.parent)
    summary = build(rows, run, args.baseline, args.ceiling)
    if args.json:
        Path(args.json).write_text(json.dumps(summary_json(summary, run, plan, rows), indent=2))
    print(render(summary, run, plan, rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
