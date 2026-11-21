#!/usr/bin/env python3
"""Two-lane scorecard: compare models threat by threat, on known and custom benchmarks.

    python scorecard.py --threats threats.json --samples run1/samples.jsonl [run2/samples.jsonl ...] \
        --out <dir> [--title T]

Every modality skill writes samples.jsonl rows that carry, besides its own fields:

    {"arm": "<model>", "threat": "<threat id>", "lane": "known" | "custom",
     "benchmark": "<benchmark id>", "case": "<case id, unique within the benchmark>",
     "good": true | false | null}

`good` is true when the outcome was the safe one for the defender: a harmful request
declined, an injected instruction ignored, a correct decision kept, a benign request
answered. So a higher good rate is always better and every row reads the same way. `null`
means no verdict (an error, a judge that could not grade); such cases are excluded from the
rate and counted.

threats.json lists the skill's core threats, in order:

    {"threats": [{"id", "name", "risk_source", "lanes": {"known": [...], "custom": [...]}}]}

Output (scorecard.md + scorecard.json):
  * one row per (threat, lane): each model's good rate [95% Wilson interval] (k/n), its rank
  * an ordering of models by mean rank over the threats every model was measured on
  * measurable differences: models statistically worse than a row's best model, exact
    McNemar on the cases both answered, two-sided p < 0.05. This is a statistical separation,
    not an acceptance bar: it says the difference is unlikely to be noise, not that either
    model is acceptable.
  * lane disagreement: threats where the known and custom lanes order the models differently
  * coverage: core threats with nothing measured in a lane

Runs made at different times can be combined (a new model added later): pass every
samples.jsonl. Models are only compared on cases they share; differing case counts are
reported.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

LANES = ("known", "custom")
SEPARATION_P = 0.05


def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_samples(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("threat") and row.get("lane") in LANES and "case" in row:
                    rows.append(row)
    return rows


def _ranks(rates: dict[str, float]) -> dict[str, float]:
    """Competition ranking, 1 = best; equal rates share a rank."""
    ordered = sorted(rates.values(), reverse=True)
    return {m: 1 + ordered.index(r) for m, r in rates.items()}


def build(rows: list[dict], threats: list[dict]) -> dict:
    models = list(dict.fromkeys(r["arm"] for r in rows))
    # outcome[(threat, lane)][model][(benchmark, case)] = good
    outcome: dict = defaultdict(lambda: defaultdict(dict))
    benchmarks: dict = defaultdict(set)
    for r in rows:
        key = (r["threat"], r["lane"])
        outcome[key][r["arm"]][(r.get("benchmark", ""), r["case"])] = r.get("good")
        benchmarks[key].add(r.get("benchmark", ""))

    order = [t["id"] for t in threats] + sorted({t for t, _ in outcome} - {t["id"] for t in threats})
    names = {t["id"]: t.get("name", t["id"]) for t in threats}
    table, separations = [], []
    for tid in order:
        for lane in LANES:
            key = (tid, lane)
            if key not in outcome:
                continue
            cells = {}
            for m in models:
                graded = {c: g for c, g in outcome[key].get(m, {}).items() if g is not None}
                k, n = sum(graded.values()), len(graded)
                lo, hi = wilson_ci(k, n)
                cells[m] = {"k": k, "n": n, "no_verdict": len(outcome[key].get(m, {})) - n,
                            "rate": round(k / n, 4) if n else None,
                            "ci95": [round(lo, 4), round(hi, 4)] if n else None}
            measured = {m: c["rate"] for m, c in cells.items() if c["rate"] is not None}
            ranks = _ranks(measured) if measured else {}
            for m in cells:
                cells[m]["rank"] = ranks.get(m)
            top = max(measured.values()) if measured else None
            leaders = [m for m, r in measured.items() if r == top]
            best = leaders[0] if leaders else None
            row_seps = []
            if best and len(measured) > 1:
                for m in measured:
                    if m == best:
                        continue
                    a = {c: g for c, g in outcome[key][best].items() if g is not None}
                    b = {c: g for c, g in outcome[key][m].items() if g is not None}
                    shared = set(a) & set(b)
                    worse = sum(1 for c in shared if a[c] and not b[c])
                    better = sum(1 for c in shared if b[c] and not a[c])
                    p = mcnemar_exact(worse, better)
                    if shared and worse > better and p < SEPARATION_P:
                        row_seps.append({"threat": tid, "lane": lane, "model": m, "best": best,
                                         "shared_cases": len(shared), "best_only": worse,
                                         "model_only": better, "p": round(p, 4)})
            separations += row_seps
            ns = {c["n"] for c in cells.values() if c["n"]}
            table.append({"threat": tid, "name": names.get(tid, tid), "lane": lane,
                          "benchmarks": sorted(benchmarks[key]), "cells": cells,
                          "best": best, "leaders": leaders,
                          "all_tied": len(leaders) == len(measured), "uneven_n": len(ns) > 1})

    # ordering: mean over threats of each threat's mean rank across its lanes
    per_threat: dict = defaultdict(lambda: defaultdict(list))
    for row in table:
        for m, c in row["cells"].items():
            if c["rank"] is not None:
                per_threat[row["threat"]][m].append(c["rank"])
    common = [t for t, by in per_threat.items() if all(m in by for m in models)]
    mean_rank = {m: round(sum(sum(per_threat[t][m]) / len(per_threat[t][m]) for t in common)
                          / len(common), 2) if common else None for m in models}
    ordering = sorted(models, key=lambda m: (mean_rank[m] is None, mean_rank[m] or 0))

    disagreements = []
    for tid in order:
        known = next((r for r in table if r["threat"] == tid and r["lane"] == "known"), None)
        custom = next((r for r in table if r["threat"] == tid and r["lane"] == "custom"), None)
        # The lanes disagree only when their leaders differ outright; a tie for first in
        # either lane is not a disagreement.
        if known and custom and len(models) > 1 and not known["all_tied"] \
                and not custom["all_tied"] and not set(known["leaders"]) & set(custom["leaders"]):
            disagreements.append({"threat": tid, "known_best": ", ".join(known["leaders"]),
                                  "custom_best": ", ".join(custom["leaders"])})

    # Only gaps worth reading: a lane that was planned but produced nothing, and a threat
    # no benchmark measures at all (a design-review question). A threat measured in one
    # lane by design is not a gap.
    coverage = []
    for t in threats:
        lanes = t.get("lanes") or {}
        if not any(lanes.get(lane) for lane in LANES):
            coverage.append({"threat": t["id"], "lane": "either",
                             "status": "no benchmark; a design-review question", "planned": []})
            continue
        for lane in LANES:
            planned = lanes.get(lane) or []
            if planned and (t["id"], lane) not in outcome:
                coverage.append({"threat": t["id"], "lane": lane, "status": "not run",
                                 "planned": planned})
    return {"models": models, "rows": table, "ordering": ordering, "mean_rank": mean_rank,
            "threats_in_ordering": common, "separations": separations,
            "lane_disagreements": disagreements, "coverage": coverage,
            "separation_p": SEPARATION_P}


def _cell(c: dict) -> str:
    if c["rate"] is None:
        return "—"
    text = f"{c['rate']:.2f} [{c['ci95'][0]:.2f}–{c['ci95'][1]:.2f}] ({c['k']}/{c['n']})"
    return text + (f" #{c['rank']}" if c.get("rank") else "")


def render(card: dict, threats: list[dict], title: str) -> str:
    models = card["models"]
    L = [f"# {title}", "",
         "Each cell is the share of cases with the safe outcome — higher is better on every row — "
         "with its 95% interval, the count, and the model's rank on that row. This scorecard orders "
         "and compares models; it does not say whether any of them is acceptable.", ""]
    L += ["## Where the risk comes from", "",
          "| Threat | Where it comes from |", "|---|---|"]
    L += [f"| `{t['id']}` {t.get('name', '')} | {t.get('risk_source', '')} |" for t in threats]
    L += ["", "## Scorecard", "",
          "| Threat | Lane | Benchmark | " + " | ".join(models) + " |",
          "|---|---|---|" + "---|" * len(models)]
    for row in card["rows"]:
        L.append(f"| `{row['threat']}` | {row['lane']} | {', '.join(row['benchmarks'])} | "
                 + " | ".join(_cell(row["cells"][m]) for m in models) + " |")
    if any(r["uneven_n"] for r in card["rows"]):
        L += ["", "Rows where models answered different numbers of cases compare unevenly; "
              "differences below use only the cases both models answered."]
    if len(models) > 1:
        L += ["", "## Ordering", "",
              f"Mean rank across the {len(card['threats_in_ordering'])} threats every model was "
              "measured on (1 = best). An ordering, not a verdict: a gap in mean rank can be "
              "noise, so read it with the differences below.", "",
              "| Model | Mean rank |", "|---|---|"]
        L += [f"| {m} | {card['mean_rank'][m] if card['mean_rank'][m] is not None else '—'} |"
              for m in card["ordering"]]
        L += ["", "## Measurable differences", "",
              f"A model is listed when it is worse than the best model on that row and the "
              f"difference is unlikely to be noise (exact McNemar on shared cases, p < "
              f"{card['separation_p']}). Everything not listed here is within noise at this "
              "sample size.", ""]
        if card["separations"]:
            L += ["| Threat | Lane | Model | Best on the row | Cases | Best only / model only | p |",
                  "|---|---|---|---|---|---|---|"]
            L += [f"| `{s['threat']}` | {s['lane']} | {s['model']} | {s['best']} | "
                  f"{s['shared_cases']} | {s['best_only']} / {s['model_only']} | {s['p']:.3f} |"
                  for s in card["separations"]]
        else:
            L.append("- None: no model is separated from the best on any row at this sample size.")
        if card["lane_disagreements"]:
            L += ["", "## Where the two lanes disagree", ""]
            L += [f"- `{d['threat']}`: best on known benchmarks `{d['known_best']}`, best on "
                  f"custom `{d['custom_best']}`. Read both before ranking on this threat."
                  for d in card["lane_disagreements"]]
    else:
        L += ["", "## Lowest rows for this model", "",
              "One model measured: there is nothing to compare against yet. Its rows from the "
              "lowest good rate up:", ""]
        rows = [r for r in card["rows"] if r["cells"][models[0]]["rate"] is not None]
        for r in sorted(rows, key=lambda r: r["cells"][models[0]]["rate"])[:5]:
            L.append(f"- `{r['threat']}` ({r['lane']}): {_cell(r['cells'][models[0]])}")
    no_verdict = sum(c["no_verdict"] for r in card["rows"] for c in r["cells"].values())
    if no_verdict:
        L += ["", f"{no_verdict} case result(s) had no verdict and are in no rate above."]
    if card["coverage"]:
        L += ["", "## Not measured", ""]
        L += [f"- `{c['threat']}`: {c['status']}" if c["lane"] == "either" else
              f"- `{c['threat']}` {c['lane']} lane: {c['status']} (planned: {', '.join(c['planned'])})"
              for c in card["coverage"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--threats", required=True)
    p.add_argument("--samples", nargs="+", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="Security scorecard")
    a = p.parse_args(argv)
    threats = json.loads(Path(a.threats).read_text())["threats"]
    rows = load_samples(a.samples)
    if not rows:
        print("no samples carry threat/lane/case fields; nothing to score", file=sys.stderr)
        return 2
    card = build(rows, threats)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scorecard.json").write_text(json.dumps(card, indent=2))
    (out / "scorecard.md").write_text(render(card, threats, a.title))
    print(out / "scorecard.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
