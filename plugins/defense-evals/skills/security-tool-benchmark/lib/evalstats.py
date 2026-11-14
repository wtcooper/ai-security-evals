#!/usr/bin/env python3
"""Paired statistics for every harness, from the shared findings.jsonl / samples.jsonl
contract (design doc §2.2–2.3). Pure stdlib so the vendored copy runs anywhere.

  python3 evalstats.py <EXP>/findings.jsonl [--samples <EXP>/samples.jsonl] \
      --pair-on target,sample --baseline A [--arms A,D] [--severity-min high] \
      [--majority scan-code=2/3] [--boot 10000 --seed 0] [--out summary.md] [--json summary.json]

Per (arm, target, sample) it computes: total findings, findings >= severity-min, per-CWE-family
counts, severity-weighted score, exploitable count / any-exploitable, correct-AND-secure
(acceptance_pass and no exploitable), cost. Arms are compared **paired** on --pair-on against
--baseline: bootstrap CI on the mean paired delta, exact McNemar for binary outcomes, Wilcoxon
signed-rank for counts. LLM scanner repeats (tool_run) are majority-voted and their
run-to-run flip rate / Fleiss kappa reported. Wilson CIs on rates. Contaminated samples
(samples.jsonl `contaminated: true`) are reported as a separate stratum.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

SEV_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
SEV_WEIGHT = {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 1.0, "info": 0.0}


# ----------------------------------------------------------------------------- io
def load_jsonl(path: Path | None) -> list[dict]:
    if not path or not Path(path).exists():
        return []
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def sample_key(row: dict, pair_on: list[str]) -> tuple:
    return tuple(row.get(k) for k in pair_on)


def derive_samples(findings: list[dict], pair_on: list[str]) -> list[dict]:
    """If samples.jsonl is missing, every (arm, pair key) seen in findings is a sample."""
    seen = {}
    for f in findings:
        k = (f.get("arm"),) + sample_key(f, pair_on)
        if k not in seen:
            seen[k] = {"arm": f.get("arm"), **{p: f.get(p) for p in pair_on},
                       "build_ok": True, "acceptance_pass": None, "contaminated": False, "_derived": True}
    return list(seen.values())


# ------------------------------------------------------------------- majority vote
def majority_vote(findings: list[dict], tool: str, min_k: int, of_k: int) -> list[dict]:
    """Collapse `tool`'s repeated runs to one row per (arm,target,sample,cwe_family,file)
    kept iff present in >= min_k of of_k runs. Other tools pass through unchanged."""
    keep, groups = [], defaultdict(dict)
    for f in findings:
        if f.get("tool") != tool:
            keep.append(f)
            continue
        key = (f.get("arm"), f.get("target"), f.get("sample"), f.get("cwe_family"), f.get("file"))
        groups[key].setdefault(f.get("tool_run", 1), f)
    for key, runs in groups.items():
        if len(runs) >= min_k:
            first = dict(sorted(runs.items())[0][1])
            first["agree_frac"] = round(len(runs) / of_k, 3)
            first["tool_run"] = 0
            keep.append(first)
    return keep


def flip_rate(findings: list[dict], tool: str) -> tuple[float | None, int]:
    """Fraction of (arm,target,sample,cwe_family,file) cells that are NOT unanimous across
    tool_runs (present in some runs, absent in others). Returns (rate, n_cells)."""
    runs_seen = defaultdict(set)
    all_runs = defaultdict(set)
    for f in findings:
        if f.get("tool") != tool:
            continue
        s = (f.get("arm"), f.get("target"), f.get("sample"))
        all_runs[s].add(f.get("tool_run", 1))
        runs_seen[(s, f.get("cwe_family"), f.get("file"))].add(f.get("tool_run", 1))
    cells = [(s, r) for (s, _, _), r in runs_seen.items() if len(all_runs[s]) > 1]
    if not cells:
        return None, 0
    flips = sum(1 for s, r in cells if len(r) != len(all_runs[s]))
    return flips / len(cells), len(cells)


def fleiss_kappa(matrix: list[list[int]]) -> float | None:
    """matrix[subject][category] = number of raters assigning that category (constant n)."""
    if not matrix:
        return None
    n = sum(matrix[0])
    if n < 2:
        return None
    N, k = len(matrix), len(matrix[0])
    p_j = [sum(row[j] for row in matrix) / (N * n) for j in range(k)]
    P_i = [(sum(c * c for c in row) - n) / (n * (n - 1)) for row in matrix]
    P_bar, Pe = sum(P_i) / N, sum(p * p for p in p_j)
    if Pe == 1.0:
        return 1.0
    return (P_bar - Pe) / (1 - Pe)


def scanner_kappa(findings: list[dict], tool: str) -> tuple[float | None, int]:
    """Fleiss kappa over cells (present/absent) across the tool's runs (requires equal run
    counts per sample; samples with a different run count are skipped)."""
    runs_seen, all_runs = defaultdict(set), defaultdict(set)
    for f in findings:
        if f.get("tool") != tool:
            continue
        s = (f.get("arm"), f.get("target"), f.get("sample"))
        all_runs[s].add(f.get("tool_run", 1))
        runs_seen[(s, f.get("cwe_family"), f.get("file"))].add(f.get("tool_run", 1))
    counts = Counter(len(v) for v in all_runs.values() if len(v) > 1)
    if not counts:
        return None, 0
    n = counts.most_common(1)[0][0]
    matrix = [[len(r), n - len(r)] for (s, _, _), r in runs_seen.items() if len(all_runs[s]) == n]
    return fleiss_kappa(matrix), len(matrix)


# ---------------------------------------------------------------------- statistics
def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float, float, float]:
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def paired_bootstrap_ci(x: list[float], y: list[float], B: int = 10000, seed: int = 0,
                        alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean of (y - x) with percentile bootstrap CI over pairs."""
    d = [b - a for a, b in zip(x, y)]
    n = len(d)
    if n == 0:
        return (float("nan"),) * 3
    mean = sum(d) / n
    if n == 1:
        return (mean, mean, mean)
    rng = random.Random(seed)
    means = []
    for _ in range(B):
        s = rng.choices(d, k=n)
        means.append(sum(s) / n)
    means.sort()
    lo = means[int(math.floor(alpha / 2 * B))]
    hi = means[min(B - 1, int(math.ceil((1 - alpha / 2) * B)) - 1)]
    return (mean, lo, hi)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from discordant counts (b: only-in-x, c: only-in-y)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * p)


def wilcoxon_signed_rank(x: list[float], y: list[float]) -> tuple[float, float, int]:
    """Two-sided Wilcoxon signed-rank on paired differences (zeros dropped, ties mid-ranked).
    Exact enumeration for n<=20 else normal approximation. Returns (W, p, n_nonzero)."""
    d = [b - a for a, b in zip(x, y) if b - a != 0]
    n = len(d)
    if n == 0:
        return (0.0, 1.0, 0)
    ad = sorted((abs(v), i) for i, v in enumerate(d))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ad[j + 1][0] == ad[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for t in range(i, j + 1):
            ranks[ad[t][1]] = r
        i = j + 1
    w_plus = sum(r for r, v in zip(ranks, d) if v > 0)
    w_minus = sum(r for r, v in zip(ranks, d) if v < 0)
    W = min(w_plus, w_minus)
    if n <= 20:
        # exact: distribution of W+ over all sign assignments (ties handled by actual ranks)
        dist = defaultdict(int)
        dist[0.0] = 1
        for r in ranks:
            nd = defaultdict(int)
            for s, cnt in dist.items():
                nd[s] += cnt
                nd[s + r] += cnt
            dist = nd
        total = 2 ** n
        p_le = sum(cnt for s, cnt in dist.items() if s <= W + 1e-9) / total
        return (W, min(1.0, 2 * p_le), n)
    mu = n * (n + 1) / 4
    ties = Counter(ranks)
    tie_corr = sum(t ** 3 - t for t in ties.values()) / 48
    sigma = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - tie_corr)
    z = (W - mu) / sigma if sigma > 0 else 0.0
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return (W, min(1.0, p), n)


# ---------------------------------------------------------------- per-sample metrics
def sample_metrics(findings: list[dict], samples: list[dict], pair_on: list[str],
                   sev_min: str, tools: set[str] | None) -> dict:
    """{(arm, pair_key): metrics}"""
    out = {}
    for s in samples:
        k = (s.get("arm"), sample_key(s, pair_on))
        out[k] = {"arm": s.get("arm"), "key": sample_key(s, pair_on),
                  # missing key -> built (detection benchmarks); explicit null -> not scored yet -> excluded
                  "build_ok": (s.get("build_ok", True) is True) if "build_ok" in s else True,
                  "acceptance_pass": s.get("acceptance_pass"),
                  "contaminated": bool(s.get("contaminated", False)),
                  "cost_usd": s.get("cost_usd"), "wall_s": s.get("wall_s"),
                  "tokens_in": s.get("tokens_in"), "tokens_out": s.get("tokens_out"),
                  "total": 0, "sev": 0, "sev_weighted": 0.0, "exploitable": 0,
                  "per_family": Counter(), "per_family_sev": Counter(), "by_tool": Counter()}
    thr = SEV_ORDER.get(sev_min, 3)
    for f in findings:
        if tools and f.get("tool") not in tools:
            continue
        k = (f.get("arm"), sample_key(f, pair_on))
        m = out.get(k)
        if m is None:
            continue
        m["total"] += 1
        m["by_tool"][f.get("tool")] += 1
        sev = f.get("severity") or "medium"
        m["sev_weighted"] += SEV_WEIGHT.get(sev, 2.0)
        fam = f.get("cwe_family") or "uncwe"
        m["per_family"][fam] += 1
        if SEV_ORDER.get(sev, 2) >= thr:
            m["sev"] += 1
            m["per_family_sev"][fam] += 1
        if f.get("exploitable") is True or (f.get("tool") == "probe" and f.get("oracle_confirmed") is True):
            m["exploitable"] += 1
    for m in out.values():
        m["any_exploitable"] = 1 if m["exploitable"] > 0 else 0
        m["correct_and_secure"] = (1 if (m["acceptance_pass"] is True and m["exploitable"] == 0) else 0) \
            if m["acceptance_pass"] is not None else None
    return out


def pair_arms(metrics: dict, base: str, other: str, contaminated: bool | None = None):
    """Aligned (base_metrics, other_metrics) lists over shared pair keys where both built."""
    b = {m["key"]: m for (a, _), m in metrics.items() if a == base}
    o = {m["key"]: m for (a, _), m in metrics.items() if a == other}
    pairs = []
    for k in sorted(set(b) & set(o), key=str):
        if not (b[k]["build_ok"] and o[k]["build_ok"]):
            continue
        if contaminated is not None and (b[k]["contaminated"] != contaminated or o[k]["contaminated"] != contaminated):
            continue
        pairs.append((b[k], o[k]))
    return pairs


# ------------------------------------------------------------------------- report
def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _mean_ci(vals: list[float], B: int, seed: int) -> str:
    vals = [v for v in vals if v is not None]
    if not vals:
        return "–"
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return f"{m:.2f}"
    rng = random.Random(seed)
    bs = sorted(sum(rng.choices(vals, k=len(vals))) / len(vals) for _ in range(min(B, 2000)))
    return f"{m:.2f} [{bs[int(0.025 * len(bs))]:.2f}, {bs[int(0.975 * len(bs)) - 1]:.2f}]"


def summarize(findings, samples, *, pair_on, baseline, arms, sev_min, tools, majority,
              B, seed, run_label="") -> tuple[str, dict]:
    notes = []
    for tool, (mk, ok) in majority.items():
        findings = majority_vote(findings, tool, mk, ok)
        notes.append(f"{tool}: majority vote {mk}/{ok}")
    metrics = sample_metrics(findings, samples, pair_on, sev_min, tools)
    seen_arms = sorted({a for a, _ in metrics})
    arms = arms or seen_arms
    if baseline is None:
        baseline = arms[0] if arms else None
    J: dict = {"pair_on": pair_on, "baseline": baseline, "arms": arms, "severity_min": sev_min,
               "n_findings": len(findings), "n_samples": len(samples), "notes": notes, "arms_summary": {},
               "paired": {}, "per_family": {}, "scanner_repeats": {}, "cost": {}}
    L = [f"# Results — {run_label}".rstrip(" —"), ""]
    L.append(f"findings: {len(findings)} · samples: {len(samples)} · pair on `{','.join(pair_on)}` · "
             f"baseline **{baseline}** · severity ≥ {sev_min}" + (f" · {'; '.join(notes)}" if notes else ""))
    L.append("")

    # --- per-arm summary
    L += ["## Per-arm summary (mean [95% bootstrap CI] over samples that built)", "",
          "| arm | n | built | ≥sev findings | total | sev-weighted | exploitable | any-exploitable | acceptance pass | correct-AND-secure |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        ms = [m for (aa, _), m in metrics.items() if aa == a]
        built = [m for m in ms if m["build_ok"]]
        acc = [m for m in built if m["acceptance_pass"] is not None]
        ae = sum(m["any_exploitable"] for m in built)
        ap = sum(1 for m in acc if m["acceptance_pass"])
        cs = sum(1 for m in acc if m["correct_and_secure"])
        row = {"n": len(ms), "built": len(built),
               "sev_mean": statistics.fmean([m["sev"] for m in built]) if built else None,
               "total_mean": statistics.fmean([m["total"] for m in built]) if built else None,
               "sev_weighted_mean": statistics.fmean([m["sev_weighted"] for m in built]) if built else None,
               "exploitable_mean": statistics.fmean([m["exploitable"] for m in built]) if built else None,
               "any_exploitable": wilson_ci(ae, len(built)) if built else None,
               "acceptance_pass": wilson_ci(ap, len(acc)) if acc else None,
               "correct_and_secure": wilson_ci(cs, len(acc)) if acc else None}
        J["arms_summary"][a] = row
        def _w(t):
            return "–" if not t else f"{t[0]:.2f} [{t[1]:.2f}, {t[2]:.2f}]"
        L.append(f"| {a} | {len(ms)} | {len(built)} | {_mean_ci([m['sev'] for m in built], B, seed)} | "
                 f"{_mean_ci([m['total'] for m in built], B, seed)} | {_mean_ci([m['sev_weighted'] for m in built], B, seed)} | "
                 f"{_mean_ci([m['exploitable'] for m in built], B, seed)} | {_w(row['any_exploitable'])} | "
                 f"{_w(row['acceptance_pass'])} | {_w(row['correct_and_secure'])} |")
    L.append("")

    # --- paired comparisons vs baseline
    if baseline in arms and len(arms) > 1:
        L += [f"## Paired deltas vs {baseline} (other − baseline; negative = fewer findings)", "",
              "| arm | pairs | Δ ≥sev findings [CI] | Wilcoxon p | Δ sev-weighted [CI] | Δ exploitable [CI] | any-exploitable McNemar (b/c, p) | correct-AND-secure McNemar (b/c, p) |",
              "|---|---|---|---|---|---|---|---|"]
        for a in arms:
            if a == baseline:
                continue
            for stratum, flag in (("all", None), ("clean", False), ("contaminated", True)):
                pairs = pair_arms(metrics, baseline, a, flag)
                if flag is not None and (not pairs or not any(m["contaminated"] for (_, m) in metrics.items())):
                    continue
                if not pairs:
                    continue
                bx = [p[0] for p in pairs]
                ox = [p[1] for p in pairs]
                d_sev = paired_bootstrap_ci([m["sev"] for m in bx], [m["sev"] for m in ox], B, seed)
                W, pw, nn = wilcoxon_signed_rank([m["sev"] for m in bx], [m["sev"] for m in ox])
                d_w = paired_bootstrap_ci([m["sev_weighted"] for m in bx], [m["sev_weighted"] for m in ox], B, seed)
                d_e = paired_bootstrap_ci([m["exploitable"] for m in bx], [m["exploitable"] for m in ox], B, seed)
                b_ = sum(1 for x, y in pairs if x["any_exploitable"] and not y["any_exploitable"])
                c_ = sum(1 for x, y in pairs if not x["any_exploitable"] and y["any_exploitable"])
                pm = mcnemar_exact(b_, c_)
                cs_pairs = [(x, y) for x, y in pairs if x["correct_and_secure"] is not None and y["correct_and_secure"] is not None]
                b2 = sum(1 for x, y in cs_pairs if x["correct_and_secure"] and not y["correct_and_secure"])
                c2 = sum(1 for x, y in cs_pairs if not x["correct_and_secure"] and y["correct_and_secure"])
                pm2 = mcnemar_exact(b2, c2) if cs_pairs else None
                key = a if stratum == "all" else f"{a}[{stratum}]"
                J["paired"][key] = {"pairs": len(pairs), "delta_sev": d_sev, "wilcoxon": [W, pw, nn],
                                    "delta_sev_weighted": d_w, "delta_exploitable": d_e,
                                    "mcnemar_any_exploitable": [b_, c_, pm],
                                    "mcnemar_correct_and_secure": [b2, c2, pm2] if cs_pairs else None}
                L.append(f"| {key} | {len(pairs)} | {_fmt(d_sev[0])} [{_fmt(d_sev[1])}, {_fmt(d_sev[2])}] | {_fmt(pw, 3)} | "
                         f"{_fmt(d_w[0])} [{_fmt(d_w[1])}, {_fmt(d_w[2])}] | {_fmt(d_e[0])} [{_fmt(d_e[1])}, {_fmt(d_e[2])}] | "
                         f"{b_}/{c_}, p={_fmt(pm, 3)} | " + (f"{b2}/{c2}, p={_fmt(pm2, 3)}" if cs_pairs else "–") + " |")
        L.append("")

    # --- per CWE family
    fams = sorted({f for m in metrics.values() for f in m["per_family"]}, key=lambda s: (s == "uncwe", int(s) if s.isdigit() else 0))
    if fams:
        L += [f"## Per-CWE-family mean count per built sample (≥{sev_min} in parentheses)", "",
              "| family | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        for fam in fams:
            cells, jrow = [], {}
            for a in arms:
                built = [m for (aa, _), m in metrics.items() if aa == a and m["build_ok"]]
                if not built:
                    cells.append("–")
                    continue
                mean_all = statistics.fmean(m["per_family"][fam] for m in built)
                mean_sev = statistics.fmean(m["per_family_sev"][fam] for m in built)
                cells.append(f"{mean_all:.2f} ({mean_sev:.2f})")
                jrow[a] = [mean_all, mean_sev]
            J["per_family"][fam] = jrow
            L.append(f"| CWE-{fam} | " + " | ".join(cells) + " |")
        L.append("")

    # --- by tool (complement analysis)
    tool_names = sorted({t for m in metrics.values() for t in m["by_tool"]})
    if len(tool_names) > 1:
        L += ["## Findings by tool (mean per built sample; complement = (target,sample,family,file) cells seen by that tool only)", "",
              "| arm | " + " | ".join(tool_names) + " | only-by-tool |", "|---|" + "---|" * (len(tool_names) + 1)]
        for a in arms:
            built = [m for (aa, _), m in metrics.items() if aa == a and m["build_ok"]]
            cells = [f"{statistics.fmean(m['by_tool'][t] for m in built):.2f}" if built else "–" for t in tool_names]
            cellsets = defaultdict(set)
            for f in findings:
                if f.get("arm") == a and (not tools or f.get("tool") in tools):
                    cellsets[(f.get("target"), f.get("sample"), f.get("cwe_family"), f.get("file"))].add(f.get("tool"))
            only = Counter(next(iter(s)) for s in cellsets.values() if len(s) == 1)
            L.append(f"| {a} | " + " | ".join(cells) + " | " + ", ".join(f"{t}:{only[t]}" for t in tool_names) + " |")
        L.append("")

    # --- scanner repeat stability (from raw findings before majority vote — recompute)
    return "\n".join(L), J, metrics


def cost_section(samples: list[dict], arms: list[str]) -> tuple[list[str], dict]:
    L = ["## Cost / time (per built sample)", "", "| arm | n | $ mean | $ total | tokens in | tokens out | wall s mean |", "|---|---|---|---|---|---|---|"]
    J = {}
    for a in arms:
        ss = [s for s in samples if s.get("arm") == a and s.get("build_ok", True) is not False]
        def _num(k):
            v = [s.get(k) for s in ss if isinstance(s.get(k), (int, float))]
            return v
        c, ti, to, w = _num("cost_usd"), _num("tokens_in"), _num("tokens_out"), _num("wall_s")
        J[a] = {"n": len(ss), "usd_mean": statistics.fmean(c) if c else None, "usd_total": sum(c) if c else None,
                "tokens_in": sum(ti) if ti else None, "tokens_out": sum(to) if to else None,
                "wall_s_mean": statistics.fmean(w) if w else None}
        L.append(f"| {a} | {len(ss)} | {_fmt(J[a]['usd_mean'], 3)} | {_fmt(J[a]['usd_total'], 2)} | "
                 f"{_fmt(J[a]['tokens_in'])} | {_fmt(J[a]['tokens_out'])} | {_fmt(J[a]['wall_s_mean'], 0)} |")
    L.append("")
    return L, J


def repeat_section(raw_findings: list[dict], majority: dict) -> tuple[list[str], dict]:
    L, J = [], {}
    tools = set(majority) | {f.get("tool") for f in raw_findings if (f.get("tool_run") or 1) > 1}
    for tool in sorted(t for t in tools if t):
        fr, n_cells = flip_rate(raw_findings, tool)
        kap, n_k = scanner_kappa(raw_findings, tool)
        J[tool] = {"flip_rate": fr, "cells": n_cells, "fleiss_kappa": kap, "kappa_cells": n_k}
        if not L:
            L += ["## LLM-scanner run-to-run stability", "", "| tool | cells | flip rate | Fleiss κ | verdict |", "|---|---|---|---|---|"]
        verdict = "–" if kap is None else ("usable for gating" if kap >= 0.6 else "**unstable (κ<0.6) — not for CI gating**")
        L.append(f"| {tool} | {n_cells} | {_fmt(fr, 3)} | {_fmt(kap, 3)} | {verdict} |")
    if L:
        L.append("")
    return L, J


def parse_majority(specs: list[str]) -> dict:
    out = {}
    for s in specs or []:
        tool, frac = s.split("=")
        mk, ok = frac.split("/")
        out[tool] = (int(mk), int(ok))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings", type=Path)
    ap.add_argument("--samples", type=Path, default=None)
    ap.add_argument("--pair-on", default="target,sample")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--arms", default=None, help="comma list; default = all seen")
    ap.add_argument("--severity-min", default="high", choices=list(SEV_ORDER))
    ap.add_argument("--tools", default=None, help="comma list of tools to count (default all)")
    ap.add_argument("--majority", action="append", default=[], help="tool=k/n, e.g. scan-code=2/3")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args()

    findings = load_jsonl(a.findings)
    pair_on = [p for p in a.pair_on.split(",") if p]
    samples = load_jsonl(a.samples) if a.samples else []
    if not samples:
        cand = a.findings.parent / "samples.jsonl"
        samples = load_jsonl(cand)
        if not samples:
            print("warning: no samples.jsonl — deriving samples from findings (zero-finding samples invisible)", file=sys.stderr)
            samples = derive_samples(findings, pair_on)
    tools = set(a.tools.split(",")) if a.tools else None
    arms = a.arms.split(",") if a.arms else None
    majority = parse_majority(a.majority)
    md, J, _ = summarize(findings, samples, pair_on=pair_on, baseline=a.baseline, arms=arms,
                         sev_min=a.severity_min, tools=tools, majority=majority, B=a.boot, seed=a.seed,
                         run_label=a.label or a.findings.parent.name)
    rl, rj = repeat_section(findings, majority)
    cl, cj = cost_section(samples, J["arms"])
    J["scanner_repeats"], J["cost"] = rj, cj
    md = md + "\n" + "\n".join(rl + cl)
    if a.out:
        a.out.write_text(md)
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(md)
    if a.json:
        a.json.write_text(json.dumps(J, indent=2, default=str) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
