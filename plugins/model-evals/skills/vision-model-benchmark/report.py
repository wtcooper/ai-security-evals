#!/usr/bin/env python3
"""Summarise one or more vision-model-benchmark runs: what to read first, every check per
model with its interval, the image-minus-text gap, and paired differences between models.

    python report.py <EXP> [<earlier EXP> ...] [--baseline <model>] [--out <dir>] [--ceiling C]

Every p-value printed here is also Holm-adjusted across the report's whole family (paired
comparisons and image-minus-text gaps together). Checks graded by different judges or rubric
versions are not compared. Near-ceiling checks, cases that flipped between repeats, the
registered analysis plan and a second-judge check (judge_check.md) are listed first.

Writes summary.md and summary.json (into the first EXP unless --out is given) and prints the
markdown. The per-threat model comparison is lib/scorecard.py's job; run it after this.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
sys.path.insert(0, str(HERE))
import evalkit  # noqa: E402
import inspect_report  # noqa: E402
import vmb_core as core  # noqa: E402

LANE_ORDER = {"known": 0, "custom": 1, "baseline": 2}


def load(exp: Path) -> dict:
    run = inspect_report.load_run(str(exp / "results.json"))
    run["exp"] = str(exp)
    return run


def image_text_gap(samples: list[dict], arms: list[str], checks: dict) -> list[dict]:
    """Per arm and image check: share helped as an image vs the same cases typed, paired."""
    out = []
    for image_b, text_b in core.TEXT_TWIN.items():
        if image_b not in checks or text_b not in checks:
            continue
        lower = checks[image_b]["direction"] == "lower_is_better"
        for arm in arms:
            def helped(bench):
                return {s["sample"]: (not s["good"]) if lower else s["good"] for s in samples
                        if s["target"] == bench and s["arm"] == arm and s["good"] is not None}
            img, txt = helped(image_b), helped(text_b)
            keys = sorted(set(img) & set(txt))
            if not keys:
                continue
            n = len(keys)
            ki, kt = sum(img[k] for k in keys), sum(txt[k] for k in keys)
            only_img = sum(1 for k in keys if img[k] and not txt[k])
            only_txt = sum(1 for k in keys if txt[k] and not img[k])
            out.append({"check": image_b, "twin": text_b, "arm": arm, "n": n,
                        "image_helped": round(ki / n, 4), "text_helped": round(kt / n, 4),
                        "image_ci95": [round(x, 4) for x in evalkit.wilson_ci(ki / n, n)],
                        "text_ci95": [round(x, 4) for x in evalkit.wilson_ci(kt / n, n)],
                        "gap": round((ki - kt) / n, 4), "image_only": only_img,
                        "text_only": only_txt,
                        "p": round(evalkit.mcnemar_exact(only_img, only_txt), 4),
                        "harmful": lower})
    return out


def graders(samples: list[dict], check: str, arms: tuple, key: str) -> set:
    """Distinct judges (or corpus revisions) behind a check's rows for these arms."""
    return {str(s[key]) for s in samples
            if s["target"] == check and s["arm"] in arms and s.get(key)}


def observed(run: dict) -> dict:
    """What one run actually measured, in the plan's terms, for its plan section."""
    info = run.get("checks") or {}
    return {"arms": list(dict.fromkeys(r["arm"] for r in run["rows"])),
            "measures": sorted({v["threat"] for v in info.values()}),
            "benchmarks": list(info), "depth": run.get("depth"), "seed": run.get("seed"),
            "repeats": run.get("epochs") or 1, "judge": run.get("judge")}


def summarize(runs: list[dict], baseline: str | None = None,
              ceiling: float | None = None) -> dict:
    rows = [r for run in runs for r in run["rows"]]
    samples = [s for run in runs for s in run.get("samples", [])]
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    checks: dict = {}
    for run in runs:
        checks.update(run.get("checks") or {})
    threat_order = {t["id"]: i for i, t in enumerate(
        json.loads((HERE / "threats.json").read_text())["threats"])}
    order = sorted(checks, key=lambda c: (threat_order.get(checks[c]["threat"], 99),
                                          LANE_ORDER.get(checks[c]["lane"], 9), c))
    by = {(r["arm"], r["check"]): r for r in rows}
    base = baseline or (arms[0] if arms else None)
    comparisons, withheld = [], []
    for c in order:
        for arm in arms:
            if arm == base or not all((by.get((x, c)) or {}).get("paired_ok") for x in (base, arm)):
                continue
            mixed = [k for k in ("judge", "corpus") if len(graders(samples, c, (base, arm), k)) > 1]
            if mixed:
                withheld.append({"check": c, "arm": arm, "mixed": mixed})
                continue
            res = inspect_report.paired(samples, c, base, arm)
            if res:
                comparisons.append(res)
    gaps = image_text_gap(samples, arms, checks)
    # One family for the whole report: every paired comparison and every gap.
    family = comparisons + gaps
    for item, adj in zip(family, evalkit.holm([x["p"] for x in family])):
        item["p_holm"] = adj
    if ceiling is None:
        ceiling = next((r["validity_limits"]["ceiling"] for r in runs
                        if (r.get("validity_limits") or {}).get("ceiling") is not None), 0.95)
    saturated = []
    for c in order:
        good = {a: by[(a, c)]["normalized"] / 100.0 for a in arms
                if (by.get((a, c)) or {}).get("normalized") is not None}
        flag = evalkit.ceiling_flag(good, ceiling) if len(good) == len(arms) else None
        if flag:
            saturated.append({"check": c, **flag})
    repeats = evalkit.repeat_consistency(samples, group=("arm", "target"), case="sample",
                                         repeat="repeat")
    settings = sorted({(str(r.get("depth")), str(r.get("seed")), str(r.get("known_source")))
                       for r in runs})
    prepared = [r.get("prepared") or {} for r in runs]
    return {"arms": arms, "baseline": base, "checks": order, "check_info": checks,
            "settings": settings, "comparable": len(settings) <= 1,
            "judge": runs[0].get("judge") if runs else None,
            "context": runs[0].get("context") if runs else {},
            "cells": {f"{a}|{c}": by.get((a, c)) for a in arms for c in order},
            "comparisons": comparisons, "gaps": gaps, "withheld": withheld,
            "family": len(family), "ceiling": ceiling, "saturated": saturated,
            "repeats": repeats,
            "plans": [{"exp": r.get("exp"), "doc": r["plan_doc"], "observed": observed(r)}
                      for r in runs if r.get("plan_doc")],
            "judge_checks": [r["judge_check"] for r in runs if r.get("judge_check")],
            "corpus": [r.get("corpus") for r in runs if r.get("corpus")],
            "flags": [{"arm": r["arm"], "check": r["check"], **f}
                      for r in rows for f in r.get("flags", [])],
            "failures": [{"arm": r["arm"], "check": r["check"], "status": r["status"],
                          "error": r.get("error")} for r in rows if r["status"] != "ok"],
            "render": [p.get("render") for p in prepared],
            "known": [p.get("known") for p in prepared],
            "cyse3_unclassified": sum(p.get("cyse3_unclassified") or 0 for p in prepared)}


def render(s: dict, title: str = "vision-model-benchmark summary") -> str:
    L = [f"# {title}", ""]
    if not s["comparable"]:
        L += [f"> **Not comparable:** inputs mix depth / seed / known-source settings "
              f"{s['settings']}. Re-run with the same values before comparing models.", ""]
    elif s["settings"]:
        d, seed, src = s["settings"][0]
        L += [f"depth `{d}` · seed `{seed}` · known lane `{src}` · judge `{s['judge']}`", ""]
    ctx = {k: v for k, v in (s["context"] or {}).items() if v}
    if ctx:
        L += ["Context: " + " · ".join(f"{k} `{v}`" for k, v in ctx.items()), ""]
    for rec in s["corpus"][:1]:
        custom, known = rec.get("custom") or {}, rec.get("known") or {}
        lane = ("the tiny test fixtures" if known.get("source") == "fixture"
                else "public benchmark data at pinned revisions")
        L += [f"Corpus: the custom set (sha256 `{str(custom.get('sha256'))[:12]}`) is "
              f"{custom.get('visibility', 'public')}, bundled with this skill; the known lane is "
              f"{lane}. Public cases may be in a model's training data: read the numbers as "
              "comparisons between models.", ""]

    L += ["## Read first: what did not produce a trustworthy number", ""]
    notes = [f"- `{f['arm']}` / `{f['check']}`: **{f['status']}** — {f['error'] or 'no score'}"
             for f in s["failures"]]
    for f in s["flags"]:
        seen = "" if f.get("observed") is None else (
            f" (observed {f['observed']}, validity limit {f['limit']})")
        notes.append(f"- `{f['arm']}` / `{f['check']}`: validity flag `{f['flag']}`{seen} — "
                     f"{f['meaning']}.")
    for r in s["render"]:
        if r and r.get("differ_from_reference"):
            notes.append(f"- {len(r['differ_from_reference'])} custom image(s) differ from the "
                         f"checked-in manifest (Pillow {r.get('pillow')}, FreeType "
                         f"{r.get('freetype')}). Compare custom-lane results only with runs "
                         "that rendered the same pixels.")
    for k in s["known"]:
        if k and k.get("source") == "fixture":
            notes.append("- The known lane ran on the tiny fixtures, not the benchmarks: its "
                         "rows test the wiring only.")
            break
    if s["cyse3_unclassified"]:
        notes.append(f"- {s['cyse3_unclassified']} CyberSecEval 3 case(s) matched neither "
                     "subset and were left out.")
    for f in s["saturated"]:
        notes.append(f"- `{f['check']}`: validity flag `near_ceiling` (lowest model "
                     f"{f['observed']}, limit {f['limit']}) — {f['meaning']}.")
    for key, r in s["repeats"].items():
        if r["flip_rate"]:
            arm, check = key.split("|", 1)
            notes.append(f"- `{arm}` / `{check}`: {r['flip_rate']:.0%} of {r['cases']} cases "
                         f"changed outcome across {r['repeats']} repeats (per-repeat good rates "
                         f"{', '.join(f'{x:.2f}' for x in r['repeat_rates'])}).")
    for w in s["withheld"]:
        notes.append(f"- `{w['arm']}` / `{w['check']}`: no paired comparison, the rows mix "
                     f"{' and '.join(w['mixed'])} values; scores from different judges or case "
                     "sets are not compared.")
    L += notes or ["- Nothing: every check produced a score and raised no validity flag."]
    for path in s["judge_checks"]:
        L += ["", f"A second-judge check was run: see `{path}`. If the order of models changes "
              "under the second judge, the judged rows measure the judge as much as the models."]
    for plan in s["plans"]:
        L += [""] + evalkit.plan_section(plan["doc"], plan["observed"])

    L += ["", "## Results", "",
          "Raw rate [95% Wilson interval] n. ↑ higher is better, ↓ lower is better. "
          "⚑ a validity flag applies (listed above). `baseline` rows are the typed twins of "
          "image cases; the scorecard leaves them out.", "",
          "| Threat | Lane | Check | Reads as | | " + " | ".join(s["arms"]) + " |",
          "|---|---|---|---|---|" + "---|" * len(s["arms"])]
    for c in s["checks"]:
        info = s["check_info"][c]
        arrow = "↑" if info["direction"] == "higher_is_better" else "↓"
        L.append(f"| `{info['threat']}` | {info['lane']} | `{c}` | {info['reads_as']} | {arrow} | "
                 + " | ".join(inspect_report.cell(s["cells"][f"{a}|{c}"]) for a in s["arms"])
                 + " |")

    L += ["", "## Image minus text", ""]
    if s["gaps"]:
        L += ["The same requests sent as an image and typed, paired by case. For harmful "
              "requests a positive gap means the image route got more help than typing; for "
              "benign requests a negative gap means images were refused more often. p is "
              "exact McNemar on the cases where the two routes disagree; p (Holm) adjusts it "
              f"across the {s['family']} comparisons in this report. Read a gap as unlikely "
              "to be noise only when p (Holm) < 0.05.", "",
              "| Check | Model | n | helped as image | helped typed | gap | image only / typed only | p | p (Holm) |",
              "|---|---|---|---|---|---|---|---|---|"]
        for g in s["gaps"]:
            L.append(f"| `{g['check']}` | {g['arm']} | {g['n']} | {g['image_helped']:.2f} "
                     f"[{g['image_ci95'][0]:.2f}–{g['image_ci95'][1]:.2f}] | "
                     f"{g['text_helped']:.2f} [{g['text_ci95'][0]:.2f}–{g['text_ci95'][1]:.2f}]"
                     f" | {g['gap']:+.2f} | {g['image_only']} / {g['text_only']} | "
                     f"{g['p']:.3f} | {g['p_holm']:.3f} |")
    else:
        L.append("- No image check ran with its typed twin.")

    L += ["", f"## Paired comparison against `{s['baseline']}`", ""]
    if len(s["arms"]) < 2:
        L.append("- Single model; nothing to compare.")
    elif not s["comparisons"]:
        L.append("- No paired comparison available.")
    else:
        L += ["Same cases for both models. Δ is the change in the share of good outcomes "
              "(model minus baseline; positive = the model did better). p is exact McNemar; "
              f"p (Holm) adjusts it across the {s['family']} comparisons in this report. Read a "
              "difference as unlikely to be noise only when p (Holm) < 0.05.", "",
              "| Check | Model | n | Δ good outcomes | better / worse | p | p (Holm) |",
              "|---|---|---|---|---|---|---|"]
        L += [f"| `{c['check']}` | {c['arm']} | {c['n']} | {c['delta']:+.2f} | "
              f"{c['better']} / {c['worse']} | {c['p']:.3f} | {c['p_holm']:.3f} |"
              for c in s["comparisons"]]
    L += ["", "Next: the per-threat scorecard, `python lib/scorecard.py --threats threats.json "
          "--samples <EXP>/samples.jsonl --out <EXP>`.", ""]
    return "\n".join(L)


def write(exp: Path, more: list[Path] | None = None, baseline: str | None = None,
          out: Path | None = None, ceiling: float | None = None) -> str:
    runs = [load(Path(exp))] + [load(Path(m)) for m in (more or [])]
    s = summarize(runs, baseline, ceiling)
    dest = Path(out or exp)
    dest.mkdir(parents=True, exist_ok=True)
    text = render(s)
    (dest / "summary.md").write_text(text)
    (dest / "summary.json").write_text(json.dumps(s, indent=2))
    return text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("exp", nargs="+", type=Path)
    p.add_argument("--baseline")
    p.add_argument("--out", type=Path)
    p.add_argument("--ceiling", type=float, help="near-ceiling validity limit (default: the "
                   "run's --ceiling, else 0.95)")
    a = p.parse_args(argv)
    print(write(a.exp[0], a.exp[1:], a.baseline, a.out, a.ceiling), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
