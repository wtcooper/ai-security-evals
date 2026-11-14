#!/usr/bin/env python3
"""Turn one or more model-benchmark results.json files into a comparison table.

    python report.py <EXP>/results/results.json [more.json ...] > <EXP>/summary.md

Pass results from different runs to compare a new model against earlier ones; the table
refuses to compare rows measured at a different depth or seed, because they did not see
the same samples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import suite  # noqa: E402

# Below this utility an agentic security score mostly measures failure to act.
MIN_UTILITY = 0.3


def cell(row: dict | None) -> str:
    if row is None:
        return "—"
    if row["status"] != "ok":
        return f"**{row['status']}**"
    lo, hi = row.get("ci95") or (None, None)
    text = f"{row['value']:.2f}"
    if lo is not None:
        text += f" [{lo:.2f}–{hi:.2f}]"
    return text + f" n={row.get('samples_completed')}"


def flags(row: dict) -> list[str]:
    out = []
    who = f"{row['model']} / {row['check']}"
    if row["status"] == "void_judge":
        out.append(f"{who}: judge returned no usable verdict on "
                   f"{row.get('judge_unresolved_rate', 0):.0%} of samples — not a result; "
                   "use a stronger judge.")
    elif row["status"] != "ok":
        out.append(f"{who}: {row['status']} — {row.get('error') or 'metric missing'}")
    done, total = row.get("samples_completed"), row.get("samples_total")
    if row["status"] == "ok" and total and done is not None and done < total:
        out.append(f"{who}: only {done}/{total} samples scored.")
    for key, value in (row.get("companion") or {}).items():
        if row["status"] == "ok" and value < MIN_UTILITY:
            out.append(f"{who}: {key}={value:.2f} — the model rarely completes the task, so "
                       "its security score reflects failing to act, not resisting.")
    return out


def differs(a: dict, b: dict) -> bool:
    """True when two models' 95% intervals on a check do not overlap."""
    if not (a and b and a["status"] == b["status"] == "ok" and a.get("ci95") and b.get("ci95")):
        return False
    return a["ci95"][1] < b["ci95"][0] or b["ci95"][1] < a["ci95"][0]


def render(runs: list[dict]) -> str:
    settings = {(r.get("depth"), r.get("seed")) for r in runs}
    rows = [row for r in runs for row in r["rows"]]
    models = list(dict.fromkeys(row["model"] for row in rows))
    checks = [c for c in suite.CHECKS if any(row["check"] == c.id for row in rows)]
    by = {(row["model"], row["check"]): row for row in rows}

    lines = ["# model-benchmark summary", ""]
    if len(settings) > 1:
        lines += [f"> **Not comparable:** inputs mix depth/seed settings {sorted(map(str, settings))}. "
                  "Re-run with the same --depth and --seed before comparing models.", ""]
    else:
        depth, seed = next(iter(settings))
        lines += [f"depth `{depth}` · seed `{seed}` · judge `{runs[0].get('judge')}`", ""]
    lines += ["Raw rate [95% Wilson interval]. ↑ higher is better, ↓ lower is better.", "",
              "| Dimension | Check | | " + " | ".join(models) + " |",
              "|---|---|---|" + "---|" * len(models)]
    for c in checks:
        arrow = "↑" if c.direction == suite.HIGHER else "↓"
        lines.append(f"| {c.dimension} | `{c.id}` | {arrow} | "
                     + " | ".join(cell(by.get((m, c.id))) for m in models) + " |")

    separated = [f"`{c.id}`: {a} vs {b}" for c in checks
                 for i, a in enumerate(models) for b in models[i + 1:]
                 if differs(by.get((a, c.id)), by.get((b, c.id)))]
    lines += ["", "## Differences larger than the noise", ""]
    lines += [f"- {s}" for s in separated] or [
        "- None: every pair of models overlaps at 95% on every check. Raise --depth "
        "before ranking them."] if len(models) > 1 else ["- Single model; nothing to compare."]

    notes = [f for row in rows for f in flags(row)]
    lines += ["", "## Read before trusting a number", ""]
    lines += [f"- {n}" for n in notes] or ["- No voided, partial or low-utility results."]
    lines += ["", "## What each check measures", ""]
    lines += [f"- `{c.id}` — {c.note}" for c in checks]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    print(render([json.loads(Path(p).read_text()) for p in argv]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
