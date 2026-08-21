#!/usr/bin/env python3
"""Match scanner findings (findings.jsonl) to benchmark ground truth (design doc §2.4):
a finding matches when the CWE *family* matches AND the location matches at the granularity the
benchmark provides (file -> function -> line ±N). Emits per-finding `ground_truth_id`/`matched`,
recall at each granularity, precision lower bound, and an adjudication CSV of unmatched findings.

  python3 match.py findings.jsonl ground_truth.jsonl --out matched.jsonl --report match.md \
      [--line-window 5] [--adjudicate adjudicate.csv --adjudicate-n 30] [--group-by target,tool]

ground_truth.jsonl rows: {"target": "CVE-2026-1234", "id": "gt-1", "cwe": "22", "file": "app/x.py",
                          "function": "download", "line": 42, "severity": "high"}   (function/line optional)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
from cwe_map import family_of  # noqa: E402


def load(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def norm_file(f: str | None) -> str:
    return (f or "").replace("\\", "/").lstrip("./").lower()


def granularity(gt: dict) -> str:
    if gt.get("line") is not None:
        return "line"
    if gt.get("function"):
        return "function"
    return "file"


def match_one(f: dict, gts: list[dict], window: int) -> tuple[dict | None, str | None]:
    """Best ground-truth match for finding f among gts of the same target. Returns (gt, level)."""
    ff = norm_file(f.get("file")); fam = f.get("cwe_family") or family_of(f.get("cwe"))
    best, best_rank = None, 99
    for gt in gts:
        if family_of(gt.get("cwe")) != fam:
            continue
        gf = norm_file(gt.get("file"))
        if not gf or not (ff == gf or ff.endswith("/" + gf) or gf.endswith("/" + ff)):
            continue
        rank, level = 2, "file"
        if gt.get("line") is not None and f.get("line") is not None and abs(int(f["line"]) - int(gt["line"])) <= window:
            rank, level = 0, "line"
        elif gt.get("function") and gt["function"] in (f.get("message") or ""):
            rank, level = 1, "function"
        if rank < best_rank:
            best, best_rank, best_level = gt, rank, level
    return (best, best_level) if best else (None, None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings", type=Path); ap.add_argument("ground_truth", type=Path)
    ap.add_argument("--out", type=Path, required=True); ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--line-window", type=int, default=5)
    ap.add_argument("--adjudicate", type=Path, default=None); ap.add_argument("--adjudicate-n", type=int, default=30)
    ap.add_argument("--group-by", default="tool"); ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    F, G = load(a.findings), load(a.ground_truth)
    by_target = defaultdict(list)
    for g in G:
        by_target[g["target"]].append(g)
    keys = a.group_by.split(",")
    found = defaultdict(lambda: defaultdict(set))       # group -> level -> {gt ids}
    fp = defaultdict(int); tp = defaultdict(int); unmatched = []
    for f in F:
        gt, level = match_one(f, by_target.get(f.get("target"), []), a.line_window)
        f["ground_truth_id"] = gt["id"] if gt else None
        f["matched"] = level
        grp = tuple(str(f.get(k)) for k in keys)
        if gt:
            tp[grp] += 1
            for lv in ("file", "function", "line"):
                if lv == "file" or (lv == "function" and level in ("function", "line")) or (lv == "line" and level == "line"):
                    found[grp][lv].add(gt["id"])
        else:
            fp[grp] += 1; unmatched.append(f)
    a.out.write_text("".join(json.dumps(r) + "\n" for r in F))
    n_gt = len(G)
    L = [f"# Ground-truth matching — {a.findings.parent.name}", "",
         f"ground truth: {n_gt} vulns over {len(by_target)} targets · findings: {len(F)} · line window ±{a.line_window}", "",
         f"| {' · '.join(keys)} | findings | matched (TP) | unmatched (FP lower bound) | precision (lower bound) | recall@file | recall@function | recall@line |",
         "|---|---|---|---|---|---|---|---|"]
    J = {}
    for grp in sorted(set(tp) | set(fp)):
        n = tp[grp] + fp[grp]
        rec = {lv: len(found[grp][lv]) / n_gt if n_gt else 0 for lv in ("file", "function", "line")}
        prec = tp[grp] / n if n else 0
        J[" · ".join(grp)] = {"findings": n, "tp": tp[grp], "fp_lower_bound": fp[grp], "precision_lower_bound": prec, **{f"recall_{k}": v for k, v in rec.items()}}
        L.append(f"| {' · '.join(grp)} | {n} | {tp[grp]} | {fp[grp]} | {prec:.2f} | {rec['file']:.2f} | {rec['function']:.2f} | {rec['line']:.2f} |")
    # per CWE family recall (file level), all groups pooled
    fam_gt = Counter(family_of(g.get("cwe")) for g in G)
    fam_found = Counter()
    seen = set()
    for f in F:
        if f["ground_truth_id"] and f["ground_truth_id"] not in seen:
            seen.add(f["ground_truth_id"]); fam_found[f.get("cwe_family")] += 1
    L += ["", "## Recall by CWE family (any tool, file level)", "", "| family | ground truth | found | recall |", "|---|---|---|---|"]
    for fam, n in sorted(fam_gt.items(), key=lambda x: -x[1]):
        L.append(f"| CWE-{fam} | {n} | {fam_found[fam]} | {fam_found[fam]/n:.2f} |")
    # complement analysis across tools
    tools = sorted({f.get("tool") for f in F})
    if len(tools) > 1:
        per_tool = {t: {f["ground_truth_id"] for f in F if f.get("tool") == t and f["ground_truth_id"]} for t in tools}
        allf = set().union(*per_tool.values())
        L += ["", "## Complement (ground-truth vulns found by …)", ""]
        for t in tools:
            only = per_tool[t] - set().union(*(v for k, v in per_tool.items() if k != t))
            L.append(f"- **{t}**: {len(per_tool[t])} found, {len(only)} only-by-{t}")
        L.append(f"- **union**: {len(allf)} / {n_gt} = {len(allf)/n_gt if n_gt else 0:.2f}")
    if a.adjudicate:
        rng = random.Random(a.seed)
        sample = unmatched if len(unmatched) <= a.adjudicate_n else rng.sample(unmatched, a.adjudicate_n)
        with a.adjudicate.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["target", "tool", "rule_id", "cwe", "file", "line", "severity", "message", "verdict(TP/FP)", "note"])
            for f in sample:
                w.writerow([f.get("target"), f.get("tool"), f.get("rule_id"), f.get("cwe"), f.get("file"), f.get("line"), f.get("severity"), (f.get("message") or "")[:200], "", ""])
        L += ["", f"Adjudication sample: {len(sample)} of {len(unmatched)} unmatched findings -> `{a.adjudicate.name}` (fill verdict column; rerun with --adjudicated to report adjudicated precision)."]
    md = "\n".join(L) + "\n"
    if a.report:
        a.report.write_text(md)
    else:
        print(md)
    print(json.dumps(J, indent=1), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
