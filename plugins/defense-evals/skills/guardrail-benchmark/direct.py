#!/usr/bin/env python3
"""Direct mode across guardrails: register the plan before the runs, then compare them.

  python direct.py plan "<EXP>" --arms vendor-a,vendor-b [--baseline vendor-a] --depth standard \
      [--seed 20260809] [--channel input] [--ceiling 0.95] [--reason "<why it changed>"]
  npx promptfoo eval -c promptfooconfig.yaml --filter-sample 150 --filter-sample-seed 20260809 \
      --output "<EXP>/results/<arm>.json"        # once per guardrail: same depth, same seed
  python direct.py compare "<EXP>" [--baseline vendor-a] [--ceiling 0.95] \
      [--json "<EXP>/summary.json"] > "<EXP>/summary.md"

`plan` writes <EXP>/plan.json (arms, baseline, depth, seed, channel, the bundled corpus's
fingerprint, the organisation's criteria file if there is one) and prints, per guardrail, the
attack and benign cases and requests, the smallest paired difference that many cases can
separate, and the eval command for each arm.

`compare` reads one promptfoo output per guardrail (<EXP>/results/<arm>.json), scores each with
lib/summarize.py, and compares every guardrail with the baseline on the cases both scored:
exact McNemar on attacks caught and on benign cases let through, each p shown raw and
Holm-adjusted across the whole report. It opens with what to read first (warnings, a
`near_ceiling` validity flag when every guardrail is at or above --ceiling, arms that did not
see the same cases) and ends with the registered plan. No acceptance thresholds.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import evalkit  # noqa: E402
import summarize as sm  # noqa: E402

CORPUS = sorted((HERE / "corpus").glob("*.json"))
FILTER_SAMPLE = {"smoke": 30, "standard": 150, "full": None}
MEASURES = {"attacks": "catch rate (attacks blocked)", "benign": "benign let through (1 − FPR)"}


def corpus_counts() -> dict:
    counts = {"attacks": 0, "benign": 0}
    for path in CORPUS:
        for case in json.loads(path.read_text()):
            meta = case.get("metadata") or {}
            harmful = meta.get("type") in sm.HARMFUL_TYPES or meta.get("label") == "harmful"
            counts["attacks" if harmful else "benign"] += 1
    return counts


def cmd_plan(a) -> int:
    arms = [x for x in a.arms.split(",") if x]
    n = FILTER_SAMPLE[a.depth] if a.depth in FILTER_SAMPLE else int(a.depth)
    total = corpus_counts()
    whole = sum(total.values())
    share = (n / whole) if n and n < whole else 1.0
    rows = [{"name": f"{k}: {MEASURES[k]}", "samples": round(v * share), "calls": round(v * share),
             "note": "  requests to the guardrail, no model"} for k, v in total.items()]
    evalkit.print_plan(rows, arms=len(arms))
    flt = f" --filter-sample {n} --filter-sample-seed {a.seed}" if n and n < whole else ""
    for arm in arms:
        print(f"  {arm}: npx promptfoo eval -c promptfooconfig.yaml{flt} "
              f"--output \"{Path(a.exp) / 'results' / (arm + '.json')}\"", file=sys.stderr)
    plan = {"mode": "direct", "arms": arms, "baseline": a.baseline or arms[0],
            "measures": list(MEASURES), "depth": a.depth, "filter_sample": n, "seed": a.seed,
            "repeats": 1, "judge": None, "channel": a.channel, "ceiling": a.ceiling,
            "corpus": evalkit.corpus_record(CORPUS, bundled=True),
            "criteria": evalkit.criteria_record()}
    doc = evalkit.register_plan(a.exp, plan, reason=a.reason)
    print(f"plan {'amended' if doc.get('amendments') else 'registered'}: "
          f"{Path(a.exp) / evalkit.PLAN_FILE}", file=sys.stderr)
    return 0


def outcomes(doc) -> dict:
    """{case id: (measure, good)} for every case summarize.py scores (errors are left out)."""
    out = {}
    for res in sm._iter_results(doc):
        meta = sm._metadata(res)
        if (not meta and not sm._vars(res)) or sm._errored(res) or sm._empty_response(res):
            continue
        harmful = meta.get("type") in sm.HARMFUL_TYPES or meta.get("label") == "harmful"
        cid = meta.get("id") or json.dumps(sm._vars(res), sort_keys=True)
        out[cid] = ("attacks" if harmful else "benign", sm._passed(res))
    return out


def compare(runs: dict, baseline: str, ceiling: float) -> dict:
    """runs: {arm: promptfoo output}. Per-arm metrics, paired comparisons, flags."""
    arms = list(runs)
    metrics = {a: sm.summarize(doc) for a, doc in runs.items()}
    cases = {a: outcomes(doc) for a, doc in runs.items()}
    comps = []
    for arm in arms:
        if arm == baseline:
            continue
        for measure in MEASURES:
            keys = sorted(k for k, (m, _) in cases[baseline].items()
                          if m == measure and k in cases[arm])
            if not keys:
                continue
            worse = sum(1 for k in keys if cases[baseline][k][1] and not cases[arm][k][1])
            better = sum(1 for k in keys if cases[arm][k][1] and not cases[baseline][k][1])
            comps.append({"arm": arm, "measure": measure, "n": len(keys), "better": better,
                          "worse": worse, "delta": round((better - worse) / len(keys), 4),
                          "p": round(evalkit.mcnemar_exact(worse, better), 4)})
    for c, adj in zip(comps, evalkit.holm([c["p"] for c in comps])):
        c["p_holm"] = adj
    good = {"attacks": {a: m["recall"] for a, m in metrics.items() if m["counts"]["harmful"]},
            "benign": {a: 1 - m["fpr"] for a, m in metrics.items() if m["counts"]["benign"]}}
    flags = [{"measure": k, **f} for k, rates in good.items() if len(rates) > 1
             for f in [evalkit.ceiling_flag(rates, ceiling)] if f]
    ids = {a: set(c) for a, c in cases.items()}
    shared = set.intersection(*ids.values()) if ids else set()
    return {"arms": arms, "baseline": baseline, "metrics": metrics, "comparisons": comps,
            "flags": flags, "same_cases": all(v == shared for v in ids.values()),
            "shared_cases": len(shared), "cases_per_arm": {a: len(v) for a, v in ids.items()}}


def _ci(rate, ci, n) -> str:
    return f"{rate:.2f} [{ci[0]:.2f}–{ci[1]:.2f}] n={n}" if n else "—"


def render(s: dict, exp: Path) -> str:
    L = [f"# guardrail-benchmark (direct) comparison — {exp.resolve().name}", "",
         "## Read first", ""]
    notes = []
    for arm, m in s["metrics"].items():
        notes += [f"- `{arm}`: {w}" for w in m["warnings"]]
        if m["counts"]["errors"]:
            notes.append(f"- `{arm}`: {m['counts']['errors']} case(s) errored and are in no rate.")
    if not s["same_cases"]:
        notes.append(f"- The guardrails did not score the same cases ({s['cases_per_arm']}); the "
                     f"paired comparison uses the {s['shared_cases']} cases all of them scored. "
                     "Re-run with the same --filter-sample and --filter-sample-seed.")
    for f in s["flags"]:
        notes.append(f"- `{MEASURES[f['measure']]}`: validity flag `near_ceiling` (lowest arm "
                     f"{f['observed']:.2f}, limit {f['limit']}) — {f['meaning']}.")
    L += notes or ["- Nothing: every guardrail scored the same cases with no warning or flag."]
    L += ["", "## Per guardrail", "",
          "Rate [95% Wilson interval] n. Catch rate is on attacks; false-block rate on benign "
          "cases. Read the two together.", "",
          "| guardrail | catch rate | false-block rate (FPR) | precision | errors |",
          "|---|---|---|---|---|"]
    for arm, m in s["metrics"].items():
        c = m["counts"]
        L.append(f"| {arm} | {_ci(m['recall'], m['ci95']['recall'], c['harmful'])} | "
                 f"{_ci(m['fpr'], m['ci95']['fpr'], c['benign'])} | {m['precision']:.2f} | "
                 f"{c['errors']} |")
    fams = sorted({f for m in s["metrics"].values() for f in m["by_technique_family"]})
    if fams:
        L += ["", "### Catch rate by technique family (n)", "",
              "| family | " + " | ".join(s["arms"]) + " |", "|---|" + "---|" * len(s["arms"])]
        for fam in fams:
            cells = [(lambda v: f"{v['recall']:.2f} ({v['n']})" if v else "—")(
                s["metrics"][a]["by_technique_family"].get(fam)) for a in s["arms"]]
            L.append(f"| {fam} | " + " | ".join(cells) + " |")
    L += ["", f"## Paired comparison against `{s['baseline']}`", ""]
    if not s["comparisons"]:
        L.append("- Nothing to compare (one guardrail, or no case scored by both).")
    else:
        L += ["Same cases for both guardrails. Δ is the change in the share of good outcomes "
              "(attack blocked, or benign case let through; arm minus baseline). p is exact "
              "McNemar on the cases where the two disagree; p (Holm) adjusts it for the "
              f"{len(s['comparisons'])} comparisons in this report. Read a difference as unlikely "
              "to be noise only when p (Holm) < 0.05.", "",
              "| guardrail | measure | n | Δ good outcomes | better / worse | p | p (Holm) |",
              "|---|---|---|---|---|---|---|"]
        for c in s["comparisons"]:
            L.append(f"| {c['arm']} | {MEASURES[c['measure']]} | {c['n']} | {c['delta']:+.2f} | "
                     f"{c['better']} / {c['worse']} | {c['p']:.3f} | {c['p_holm']:.3f} |")
    L += [""] + evalkit.plan_section(evalkit.load_plan(exp), {"arms": s["arms"]})
    L += ["", "The bundled corpus is public and may be in a vendor's training data: read the "
          "numbers as a comparison between guardrails on the same cases."]
    return "\n".join(L) + "\n"


def cmd_compare(a) -> int:
    exp = Path(a.exp)
    files = sorted((exp / "results").glob("*.json"))
    if not files:
        print(f"no promptfoo outputs in {exp / 'results'} (one <arm>.json per guardrail)",
              file=sys.stderr)
        return 2
    planned = (evalkit.load_plan(exp) or {}).get("plan", {}).get("arms") or []
    order = {name: i for i, name in enumerate(planned)}
    runs = {f.stem: json.loads(f.read_text())
            for f in sorted(files, key=lambda f: (order.get(f.stem, len(order)), f.stem))}
    baseline = a.baseline or (evalkit.load_plan(exp) or {}).get("plan", {}).get("baseline") \
        or next(iter(runs))
    if baseline not in runs:
        print(f"baseline {baseline!r} has no output in {exp / 'results'}", file=sys.stderr)
        return 2
    ceiling = a.ceiling if a.ceiling is not None else \
        (evalkit.load_plan(exp) or {}).get("plan", {}).get("ceiling", 0.95)
    s = compare(runs, baseline, ceiling)
    if a.json:
        Path(a.json).write_text(json.dumps(s, indent=2) + "\n")
    print(render(s, exp), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan", help="register the plan and print the cost")
    pl.add_argument("exp")
    pl.add_argument("--arms", required=True, help="comma list of guardrail labels")
    pl.add_argument("--baseline", default=None, help="default: the first arm")
    pl.add_argument("--depth", default="standard", help="smoke (30) | standard (150) | full | N")
    pl.add_argument("--seed", type=int, default=20260809, help="--filter-sample-seed for every arm")
    pl.add_argument("--channel", default="input", help="input or output guardrail")
    pl.add_argument("--ceiling", type=float, default=0.95)
    pl.add_argument("--reason", default=None, help="why a registered plan is being changed")
    cp = sub.add_parser("compare", help="compare the guardrails' outputs")
    cp.add_argument("exp")
    cp.add_argument("--baseline", default=None, help="default: the plan's baseline")
    cp.add_argument("--ceiling", type=float, default=None,
                    help="validity limit: flag `near_ceiling` when every guardrail is at or above "
                         "it (default: the plan's, else 0.95)")
    cp.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    return cmd_plan(a) if a.cmd == "plan" else cmd_compare(a)


if __name__ == "__main__":
    raise SystemExit(main())
