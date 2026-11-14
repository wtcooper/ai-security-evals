#!/usr/bin/env python3
"""Classification scoring for asset scanners (skill / MCP / model-file classifiers) — scanner-agnostic.
Each asset has a label (malicious|benign); a scanner run over it yields a verdict (flag|clean).
Reports TPR/FPR with Wilson CIs, per-run flip rate, Fleiss κ across runs, and severity agreement,
split by config (static-only / judge-only / combined) and by held-out mutated stratum.

  python3 score_assets.py verdicts.jsonl --out summary.md --json summary.json [--by config,stratum]
      verdicts.jsonl rows: {"asset":"id","label":"malicious|benign","config":"combined","run":1,
                            "verdict":"flag|clean","severity":"high|...|null","stratum":"shipped|mutant",
                            "yara_hit":true|false}
A scanner "flags" an asset when it emits >=1 finding at/above a severity gate (build the rows with
build_verdicts_from_findings() or your own glue). Wilson/κ/flip come from lib/evalstats.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import evalstats as es  # noqa: E402


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def build_verdicts_from_findings(findings, labels, severity_gate="low", runs=None):
    """findings.jsonl rows (arm=scanner label, target=asset, tool_run=run) + {asset: {label, stratum,
    yara_hit}} -> verdict rows, one per (scanner arm, asset, run). An asset flags on a run iff that
    scanner has a finding >= gate on that run. `config` is the scanner arm, so `--by config` compares
    scanners and the static/judge/combined split in one table.

    `runs` is the list of rows from <EXP>/runs.jsonl ({arm, target, tool_run, status}). With it, a
    verdict exists only for a run that completed; a run that failed gets verdict "error", which is
    left out of every rate. Without it a scanner that crashed is indistinguishable from one that
    found nothing, so always pass it for a real comparison."""
    gate = es.SEV_ORDER.get(severity_gate, 1)
    flagged = defaultdict(lambda: defaultdict(bool)); sev = defaultdict(lambda: defaultdict(str))
    seen = defaultdict(set)  # arm -> {run}
    arms = set()
    for f in findings:
        arm = f.get("arm") or f.get("tool") or "scanner"
        a, r = f.get("target"), f.get("tool_run", 1)
        arms.add(arm); key = (arm, a)
        seen[arm].add(r)
        if es.SEV_ORDER.get(f.get("severity", "low"), 1) >= gate:
            flagged[key][r] = True
            if es.SEV_ORDER.get(f.get("severity"), 0) >= es.SEV_ORDER.get(sev[key][r] or "info", 0):
                sev[key][r] = f.get("severity")

    def row(arm, a, meta, r, verdict):
        return {"asset": a, "label": meta["label"],
                "config": arm if arm is not None else meta.get("config", "combined"),
                "run": r, "verdict": verdict,
                "severity": (sev[(arm, a)][r] or None) if verdict == "flag" else None,
                "stratum": meta.get("stratum", "shipped"), "yara_hit": meta.get("yara_hit")}

    rows = []
    if runs is not None:
        for run in runs:
            arm, a, r = run.get("arm"), run.get("target"), run.get("tool_run", 1)
            if a not in labels:
                continue
            ok = run.get("status") == "ok"
            rows.append(row(arm, a, labels[a], r,
                            ("flag" if flagged[(arm, a)][r] else "clean") if ok else "error"))
        return rows
    if not arms:  # no findings at all: fall back to the label's config so empty runs still tabulate
        arms = {None}
    for arm in arms:
        run_ids = sorted(seen.get(arm, {1})) if arm is not None else [1]
        for a, meta in labels.items():
            for r in run_ids:
                rows.append(row(arm, a, meta, r, "flag" if flagged[(arm, a)][r] else "clean"))
    return rows


def summarize(rows, by):
    groups = defaultdict(list)
    failed = defaultdict(int)
    for r in rows:
        if r["verdict"] == "error":     # the scanner did not run: no evidence either way
            failed[tuple(str(r.get(k)) for k in by)] += 1
            continue
        groups[tuple(str(r.get(k)) for k in by)].append(r)
    L = ["# Asset scanner classification", "",
         f"assets: {len({r['asset'] for r in rows})} · verdicts: {len(rows)} · grouped by {','.join(by)}", "",
         "| " + " · ".join(by) + " | assets | TPR [95% CI] | FPR [95% CI] | flip rate | Fleiss κ | failed runs |",
         "|---|---|---|---|---|---|---|"]
    J = {}
    for g in failed:
        groups.setdefault(g, [])
    for g, rs in sorted(groups.items()):
        assets = {r["asset"] for r in rs}
        # majority verdict per asset for TPR/FPR; flip/κ over runs
        by_asset = defaultdict(dict)
        for r in rs:
            by_asset[r["asset"]][r["run"]] = 1 if r["verdict"] == "flag" else 0
        pos = [a for a in assets if next(iter(l["label"] for l in rs if l["asset"] == a)) == "malicious"]
        neg = [a for a in assets if a not in pos]
        def maj(a):
            v = list(by_asset[a].values()); return 1 if sum(v) * 2 >= len(v) else 0
        tp = sum(maj(a) for a in pos); fp = sum(maj(a) for a in neg)
        tpr = es.wilson_ci(tp, len(pos)) if pos else (float("nan"),) * 3
        fpr = es.wilson_ci(fp, len(neg)) if neg else (float("nan"),) * 3
        # flip + κ: build present/absent matrix over runs (assets with >1 run)
        multi = {a: v for a, v in by_asset.items() if len(v) > 1}
        n_runs = max((len(v) for v in multi.values()), default=0)
        flips = sum(1 for v in multi.values() if len(set(v.values())) > 1)
        flip = flips / len(multi) if multi else None
        matrix = [[sum(v.values()), len(v) - sum(v.values())] for v in multi.values() if len(v) == n_runs] if n_runs else []
        kap = es.fleiss_kappa(matrix) if matrix else None
        gk = " · ".join(g)
        J[gk] = {"assets": len(assets), "pos": len(pos), "neg": len(neg), "tp": tp, "fp": fp,
                 "tpr": tpr, "fpr": fpr, "flip_rate": flip, "fleiss_kappa": kap,
                 "failed_runs": failed.get(g, 0)}
        def w(t):
            import math
            return "–" if not t or math.isnan(t[0]) else f"{t[0]:.2f} [{t[1]:.2f}, {t[2]:.2f}]"
        L.append(f"| {gk} | {len(assets)} | {w(tpr)} | {w(fpr)} | {es._fmt(flip, 3)} | {es._fmt(kap, 3)} | {failed.get(g, 0)} |")
    L += ["", "Flip rate and Fleiss κ say how repeatable a scanner's verdict is across identical runs. "
          "Failed runs are scanner runs that did not complete; they are in no rate above."]
    return "\n".join(L) + "\n", J


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verdicts", type=Path,
                    help="verdicts.jsonl to score (written first when --findings is given)")
    ap.add_argument("--findings", type=Path, default=None,
                    help="build verdicts.jsonl from <EXP>/findings.jsonl before scoring")
    ap.add_argument("--labels", type=Path, default=None,
                    help="labels.jsonl rows: {asset, label, stratum?, yara_hit?} (with --findings)")
    ap.add_argument("--runs", type=Path, default=None,
                    help="<EXP>/runs.jsonl, so failed scanner runs are excluded, not read as clean")
    ap.add_argument("--severity-gate", default="low")
    ap.add_argument("--by", default="config,stratum")
    ap.add_argument("--out", type=Path, default=None); ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    if a.findings:
        if not a.labels:
            ap.error("--findings needs --labels")
        labels = {(r.get("asset") or r.get("id")): r for r in load(a.labels)}
        findings = load(a.findings) if a.findings.exists() else []
        if a.runs is None:
            print("WARNING: no --runs given; a scanner run that failed cannot be told apart from a "
                  "clean scan", file=sys.stderr)
        built = build_verdicts_from_findings(findings, labels, a.severity_gate,
                                             load(a.runs) if a.runs else None)
        a.verdicts.write_text("".join(json.dumps(r) + "\n" for r in built))
    rows = load(a.verdicts)
    md, J = summarize(rows, [b for b in a.by.split(",") if b])
    (a.out.write_text(md) if a.out else sys.stdout.write(md))
    if a.json:
        a.json.write_text(json.dumps(J, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
