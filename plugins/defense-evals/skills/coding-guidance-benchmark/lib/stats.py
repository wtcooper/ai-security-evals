"""Turn samples.jsonl rows into the A/B summary. Stdlib only.

Reported per (harness, model) cell, baseline first:
  * correct-and-secure, functional-pass and secure rates with 95% Wilson intervals;
  * the paired difference of each arm from the baseline on the same tasks, with a bootstrap
    interval over tasks and an exact McNemar test on per-task outcomes;
  * failed builds, runs with no code, agent errors;
  * tokens and wall time, and what the arm added to them;
  * the touched-the-arm diagnostic.
No thresholds and no verdicts: the numbers are reported and the reader decides.
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evalkit  # noqa: E402

METRICS = ("correct_and_secure", "functional_pass", "secure")
BOOTSTRAP_DRAWS = 2000


def rate(values: list) -> dict:
    """Rate of True among values that are not None, with a Wilson interval."""
    known = [v for v in values if v is not None]
    n, k = len(known), sum(1 for v in known if v)
    if n == 0:
        return {"k": 0, "n": 0, "rate": None, "ci95": None}
    lo, hi = evalkit.wilson_ci(k / n, n)
    return {"k": k, "n": n, "rate": round(k / n, 4), "ci95": [round(lo, 4), round(hi, 4)]}


def mean(values: list) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def bootstrap_ci(diffs: list[float], seed: int = 0) -> list[float] | None:
    """95% percentile interval for the mean of per-task differences, resampling tasks."""
    if len(diffs) < 2:
        return None
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n
                   for _ in range(BOOTSTRAP_DRAWS))
    return [round(means[int(0.025 * BOOTSTRAP_DRAWS)], 4),
            round(means[int(0.975 * BOOTSTRAP_DRAWS) - 1], 4)]


def by_task(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["target"]].append(row)
    return out


def task_rate(rows: list[dict], metric: str) -> float | None:
    """Share of one task's repeats where the metric held (None when none could be judged)."""
    return mean([float(bool(r[metric])) if r.get(metric) is not None else None for r in rows])


def majority(rows: list[dict], metric: str) -> bool | None:
    """Per-task outcome for McNemar: True when a strict majority of repeats were good."""
    r = task_rate(rows, metric)
    return None if r is None else r > 0.5


def paired(arm_rows: list[dict], base_rows: list[dict], metric: str, seed: int = 0) -> dict:
    """Arm minus baseline on the tasks both built.

    diff      mean over tasks of (arm's rate on the task - baseline's rate on the task)
    ci95      bootstrap over tasks, so repeats of one task are not counted as independent
    mcnemar   exact, on per-task outcomes (majority of repeats): `arm_only` tasks good under
              the arm and not the baseline, `baseline_only` the reverse
    """
    arm, base = by_task(arm_rows), by_task(base_rows)
    diffs, arm_only, base_only, both, neither = [], 0, 0, 0, 0
    for task in sorted(set(arm) & set(base)):
        a, b = task_rate(arm[task], metric), task_rate(base[task], metric)
        if a is None or b is None:
            continue
        diffs.append(a - b)
        ma, mb = a > 0.5, b > 0.5
        arm_only += ma and not mb
        base_only += mb and not ma
        both += ma and mb
        neither += (not ma) and (not mb)
    if not diffs:
        return {"tasks": 0, "diff": None, "ci95": None, "arm_only": 0, "baseline_only": 0,
                "both": 0, "neither": 0, "mcnemar_p": None}
    return {"tasks": len(diffs), "diff": round(sum(diffs) / len(diffs), 4),
            "ci95": bootstrap_ci(diffs, seed), "arm_only": arm_only,
            "baseline_only": base_only, "both": both, "neither": neither,
            "mcnemar_p": round(evalkit.mcnemar_exact(arm_only, base_only), 4)}


def paired_cost(arm_rows: list[dict], base_rows: list[dict], key: str, seed: int = 0) -> dict:
    """What the arm added per run: mean over tasks of (arm's mean - baseline's mean)."""
    arm, base = by_task(arm_rows), by_task(base_rows)
    diffs = []
    for task in sorted(set(arm) & set(base)):
        a, b = mean([r.get(key) for r in arm[task]]), mean([r.get(key) for r in base[task]])
        if a is not None and b is not None:
            diffs.append(a - b)
    if not diffs:
        return {"tasks": 0, "diff": None, "ci95": None}
    return {"tasks": len(diffs), "diff": round(sum(diffs) / len(diffs), 4),
            "ci95": bootstrap_ci(diffs, seed)}


def agreement(rows: list[dict], metric: str = "correct_and_secure") -> dict | None:
    """Run-to-run agreement: share of tasks whose repeats all gave the same outcome.
    None when there was one repeat per task."""
    groups = [g for g in by_task(rows).values() if len(g) > 1]
    if not groups:
        return None
    same = sum(1 for g in groups if len({bool(r[metric]) for r in g}) == 1)
    return {"tasks": len(groups), "same": same, "rate": round(same / len(groups), 4)}


def touched_counts(rows: list[dict]) -> dict:
    with_t = [r["touched"] for r in rows if isinstance(r.get("touched"), dict)]
    out = {"runs_with_transcript": len(with_t)}
    for key in ("arm_file", "skill", "mcp"):
        vals = [t.get(key) for t in with_t]
        out[key] = None if all(v is None for v in vals) else sum(1 for v in vals if v)
    out["any"] = sum(1 for t in with_t if any(t.get(k) for k in ("arm_file", "skill", "mcp")))
    return out


def arm_summary(rows: list[dict]) -> dict:
    out = {"runs": len(rows), "tasks": len(by_task(rows))}
    for metric in METRICS:
        out[metric] = rate([r.get(metric) for r in rows])
    out["no_code"] = sum(1 for r in rows if not r.get("code_written"))
    out["builds_failed"] = sum(1 for r in rows if r.get("code_written") and not r.get("build_ok"))
    out["agent_errors"] = sum(1 for r in rows if r.get("error"))
    out["not_scored"] = sum(1 for r in rows if r.get("code_written") and not r.get("scored"))
    out["exploit_exceptions"] = sum(1 for r in rows if r.get("build_ok")
                                    and (r.get("st_exceptions") or 0) > 0)
    for key in ("tokens_in", "tokens_out", "tokens_total", "wall_s"):
        m = mean([r.get(key) for r in rows])
        out[f"mean_{key}"] = None if m is None else round(m, 3)
    out["agreement"] = agreement(rows)
    out["touched"] = touched_counts(rows)
    versions = sorted({str(r.get("harness_version")) for r in rows
                       if r.get("harness_version") is not None})
    out["harness_versions"] = versions
    return out


def summarise(rows: list[dict], arms_meta: list[dict] | None = None,
              baseline: str = "baseline", seed: int = 0) -> dict:
    """The whole summary: one entry per (harness, model) cell."""
    meta = {a["name"]: a for a in (arms_meta or [])}
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        cells[(row.get("harness"), row.get("model"))].append(row)
    out = {"baseline": baseline, "metric": "correct_and_secure", "cells": []}
    for (harness, model), cell_rows in sorted(cells.items(), key=lambda kv: str(kv[0])):
        per_arm: dict[str, list[dict]] = defaultdict(list)
        for row in cell_rows:
            per_arm[row["arm"]].append(row)
        names = ([baseline] if baseline in per_arm else []) + sorted(
            n for n in per_arm if n != baseline)
        cell = {"harness": harness, "model": model, "arms": [], "comparisons": []}
        for name in names:
            cell["arms"].append({"arm": name,
                                 "control_type": (meta.get(name) or {}).get("control_type"),
                                 **arm_summary(per_arm[name])})
        if baseline in per_arm:
            for name in names:
                if name == baseline:
                    continue
                comp = {"arm": name, "baseline": baseline}
                for metric in METRICS:
                    comp[metric] = paired(per_arm[name], per_arm[baseline], metric, seed)
                comp["tokens_total"] = paired_cost(per_arm[name], per_arm[baseline],
                                                   "tokens_total", seed)
                comp["wall_s"] = paired_cost(per_arm[name], per_arm[baseline], "wall_s", seed)
                cell["comparisons"].append(comp)
        out["cells"].append(cell)
    return out


# ----------------------------------------------------------------------------- markdown

def _pct(r: dict | None) -> str:
    if not r or r.get("rate") is None:
        return "n/a (0 judged)"
    lo, hi = r["ci95"]
    return f"{100 * r['rate']:.1f}% [{100 * lo:.1f}, {100 * hi:.1f}] ({r['k']}/{r['n']})"


def _points(p: dict) -> str:
    if p.get("diff") is None:
        return "n/a"
    ci = p.get("ci95")
    ci_text = f" [{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]" if ci else " [interval needs 2+ tasks]"
    return f"{100 * p['diff']:+.1f} pts{ci_text}"


def _num(value, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def _delta(p: dict, digits: int = 0) -> str:
    if p.get("diff") is None:
        return "n/a"
    ci = p.get("ci95")
    ci_text = f" [{ci[0]:+,.{digits}f}, {ci[1]:+,.{digits}f}]" if ci else ""
    return f"{p['diff']:+,.{digits}f}{ci_text}"


def render(summary: dict, run: dict | None = None, title: str = "coding-guidance-benchmark summary") -> str:
    run = run or {}
    lines = [f"# {title}", ""]
    if run:
        lines += [f"- Tasks: {run.get('task_source', '?')}, {run.get('n_tasks', '?')} task(s) x "
                  f"{run.get('repeats', '?')} repeat(s), seed {run.get('seed', '?')}, "
                  f"depth `{run.get('depth', '?')}`"
                  + (f", frameworks {', '.join(run['frameworks'])}" if run.get("frameworks") else ""),
                  f"- Every arm ran the same tasks. Baseline arm: `{summary['baseline']}` "
                  "(nothing installed)."]
        if run.get("baxbench_commit"):
            lines.append(f"- BaxBench commit {run['baxbench_commit']}; prompt built with no safety "
                         "prompt, so the arm is the only security guidance.")
        lines.append("")
    notes = read_first(summary, run)
    lines += ["## Read first", ""] + [f"- {n}" for n in notes] + [""]

    for cell in summary["cells"]:
        versions = sorted({v for a in cell["arms"] for v in a["harness_versions"]})
        lines += [f"## Harness `{cell['harness']}` (version {', '.join(versions) or 'not recorded'}), "
                  f"model `{cell['model']}`", "",
                  "### Outcome per arm (95% Wilson interval)", "",
                  "| Arm | Control type | Runs | Correct and secure | Functional pass | "
                  "Secure, of apps whose exploits ran |",
                  "|---|---|---|---|---|---|"]
        for a in cell["arms"]:
            lines.append(f"| {a['arm']} | {a['control_type'] or 'not labelled'} | {a['runs']} | "
                         f"{_pct(a['correct_and_secure'])} | {_pct(a['functional_pass'])} | "
                         f"{_pct(a['secure'])} |")
        lines += ["", "Correct and secure = every functional test passed and no exploit succeeded "
                  "(BaxBench's headline). Read the two right-hand columns with it: an arm can raise "
                  "the secure rate by producing apps that do not work.", ""]

        if cell["comparisons"]:
            lines += [f"### Paired difference from `{summary['baseline']}` (same tasks)", "",
                      "| Arm | Metric | Tasks | Difference [95% bootstrap over tasks] | "
                      "Good under arm only | Good under baseline only | Exact McNemar p |",
                      "|---|---|---|---|---|---|---|"]
            for c in cell["comparisons"]:
                for metric in METRICS:
                    p = c[metric]
                    lines.append(f"| {c['arm']} | {metric.replace('_', ' ')} | {p['tasks']} | "
                                 f"{_points(p)} | {p['arm_only']} | {p['baseline_only']} | "
                                 f"{_num(p['mcnemar_p'], 4)} |")
            lines += ["", "A per-task outcome is good when a strict majority of its repeats were. "
                      "The p-value is the chance of a split at least this uneven between the two "
                      "discordant columns if the arm made no difference.", ""]

        lines += ["### Builds and errors", "",
                  "| Arm | Runs | No code written | Build failed | Agent errors | Not scored | "
                  "Exploit could not complete |", "|---|---|---|---|---|---|---|"]
        for a in cell["arms"]:
            lines.append(f"| {a['arm']} | {a['runs']} | {a['no_code']} | {a['builds_failed']} | "
                         f"{a['agent_errors']} | {a['not_scored']} | {a['exploit_exceptions']} |")
        lines.append("")
        agreements = [(a["arm"], a["agreement"]) for a in cell["arms"] if a["agreement"]]
        if agreements:
            lines += ["Run-to-run agreement (tasks whose repeats all gave the same "
                      "correct-and-secure outcome): "
                      + "; ".join(f"`{n}` {g['same']}/{g['tasks']}" for n, g in agreements) + ".", ""]

        lines += ["### Cost", "",
                  "| Arm | Mean tokens in | Mean tokens out | Mean tokens total | Mean wall time (s) | "
                  "Tokens added vs baseline [95%] | Wall time added (s) [95%] |",
                  "|---|---|---|---|---|---|---|"]
        comps = {c["arm"]: c for c in cell["comparisons"]}
        for a in cell["arms"]:
            c = comps.get(a["arm"])
            lines.append(f"| {a['arm']} | {_num(a['mean_tokens_in'])} | {_num(a['mean_tokens_out'])} | "
                         f"{_num(a['mean_tokens_total'])} | {_num(a['mean_wall_s'], 2)} | "
                         f"{_delta(c['tokens_total']) if c else '-'} | "
                         f"{_delta(c['wall_s'], 2) if c else '-'} |")
        lines.append("")

        lines += ["### Did the agent touch the arm? (diagnostic)", "",
                  "| Arm | Runs with a transcript | Named an arm path | Called a skill tool | "
                  "Called an MCP tool | Any signal |", "|---|---|---|---|---|---|"]
        for a in cell["arms"]:
            t = a["touched"]
            n = t["runs_with_transcript"]

            cells = ["n/a" if t[k] is None else f"{t[k]}/{n}" for k in ("arm_file", "skill", "mcp")]
            lines.append(f"| {a['arm']} | {n} | {cells[0]} | {cells[1]} | {cells[2]} | "
                         f"{t['any']}/{n} |")
        lines += ["", "Read from tool calls only, without interpreting the arm. A signal shows the "
                  "arm was reached. No signal does not show it was unused: a file the harness "
                  "loads into context by itself, or a hook, leaves no tool call. The baseline row "
                  "is the level to compare against.", ""]
    lines += ["This report states what was measured. It sets no threshold and gives no verdict.", ""]
    return "\n".join(lines)


def read_first(summary: dict, run: dict) -> list[str]:
    """Things that change how the numbers should be read. Listed whenever they occur; none of
    them hides a number or says a result is good or bad."""
    notes = []
    harnesses = {c["harness"] for c in summary["cells"]}
    if harnesses & {"mock", "mock-sandbox"}:
        notes.append("The harness is a mock that writes fixed code. These numbers show that the "
                     "pipeline runs; they say nothing about any agent, model or arm.")
    if run.get("task_source") == "fake":
        notes.append("The tasks and the scorer are the bundled fakes, not BaxBench.")
    for cell in summary["cells"]:
        where = f"`{cell['harness']}` / `{cell['model']}`"
        if not any(a["arm"] == summary["baseline"] for a in cell["arms"]):
            notes.append(f"{where}: no `{summary['baseline']}` rows, so no paired comparison.")
        for a in cell["arms"]:
            for key, text in (
                    ("builds_failed", "run(s) wrote code that did not build. No CWE is recorded "
                     "for an app that never ran, so these are counted as not correct-and-secure "
                     "and left out of the secure rate"),
                    ("no_code", "run(s) wrote no code"),
                    ("agent_errors", "run(s) ended with a harness error"),
                    ("not_scored", "run(s) have code but no result file: scoring did not finish"),
                    ("exploit_exceptions", "run(s) had an exploit that could not complete; "
                     "the scorer counts such an exploit as not having found a weakness")):
                if a[key]:
                    notes.append(f"{where}, arm `{a['arm']}`: {a[key]} of {a['runs']} {text}.")
            if len(a["harness_versions"]) > 1:
                notes.append(f"{where}, arm `{a['arm']}`: more than one harness version ran "
                             f"({', '.join(a['harness_versions'])}).")
    if run.get("repeats", 1) > 1:
        notes.append("With more than one repeat per task the Wilson intervals treat repeats as "
                     "independent and are somewhat too narrow; the paired differences resample "
                     "whole tasks and do not have that problem.")
    if run.get("harness_version_requested") in ("stable", "latest", "auto", "sandbox"):
        notes.append(f"The harness version was requested as `{run['harness_version_requested']}`, "
                     "not pinned to a number; the installed version is the one shown.")
    return notes or ["Nothing to flag."]
