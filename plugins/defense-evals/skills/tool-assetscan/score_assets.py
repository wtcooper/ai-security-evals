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

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import evalstats as es  # noqa: E402


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def build_verdicts_from_findings(findings, labels, severity_gate="low"):
    """findings.jsonl rows (arm=scanner label, target=asset, tool_run=run) + {asset: {label, stratum, yara_hit}}
    -> verdict rows, one row per (scanner arm, asset, run). An asset flags on a run iff that scanner
    has a finding >= gate on that run. `config` is the scanner arm (e.g. scan-skill-combined, yara),
    so `--by config` compares scanners and the static/judge/combined split in one table."""
    gate = es.SEV_ORDER.get(severity_gate, 1)
    # segment every tally by the scanner arm so multiple scanners over the same asset don't collide
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
    if not arms:  # no findings at all: fall back to the label's config so empty runs still tabulate
        arms = {None}
    rows = []
    for arm in arms:
        runs = sorted(seen.get(arm, {1})) if arm is not None else [1]
        for a, meta in labels.items():
            key = (arm, a)
            for r in runs:
                rows.append({"asset": a, "label": meta["label"],
                             "config": arm if arm is not None else meta.get("config", "combined"),
                             "run": r, "verdict": "flag" if flagged[key][r] else "clean",
                             "severity": sev[key][r] or None, "stratum": meta.get("stratum", "shipped"),
                             "yara_hit": meta.get("yara_hit")})
    return rows


def summarize(rows, by):
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(str(r.get(k)) for k in by)].append(r)
    L = ["# Asset scanner classification", "",
         f"assets: {len({r['asset'] for r in rows})} · verdicts: {len(rows)} · grouped by {','.join(by)}", "",
         "| " + " · ".join(by) + " | assets | TPR [95% CI] | FPR [95% CI] | flip rate | Fleiss κ | κ verdict |",
         "|---|---|---|---|---|---|---|"]
    J = {}
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
        kv = "–" if kap is None else ("usable" if kap >= 0.6 else "**κ<0.6 — not for CI gating**")
        gk = " · ".join(g)
        J[gk] = {"assets": len(assets), "pos": len(pos), "neg": len(neg), "tp": tp, "fp": fp,
                 "tpr": tpr, "fpr": fpr, "flip_rate": flip, "fleiss_kappa": kap}
        def w(t):
            import math
            return "–" if not t or math.isnan(t[0]) else f"{t[0]:.2f} [{t[1]:.2f}, {t[2]:.2f}]"
        L.append(f"| {gk} | {len(assets)} | {w(tpr)} | {w(fpr)} | {es._fmt(flip, 3)} | {es._fmt(kap, 3)} | {kv} |")
    return "\n".join(L) + "\n", J


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("verdicts", type=Path)
    ap.add_argument("--by", default="config,stratum")
    ap.add_argument("--out", type=Path, default=None); ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()
    rows = load(a.verdicts)
    md, J = summarize(rows, [b for b in a.by.split(",") if b])
    (a.out.write_text(md) if a.out else sys.stdout.write(md))
    if a.json:
        a.json.write_text(json.dumps(J, indent=1, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
