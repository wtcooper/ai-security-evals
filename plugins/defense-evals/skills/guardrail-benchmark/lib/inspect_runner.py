"""Run Inspect benchmarks over a set of ARMS and write the shared results contract.

An arm is the one thing a run varies: a model (model-benchmark) or the same model behind a
different guardrail (guardrail-benchmark). Every arm runs the same seeded samples.

Written to <out>/:
  results.json   one row per arm x check: the headline rate, interval, validity flags
  samples.jsonl  one row per arm x check x sample: good / not good / no verdict
  logs/          Inspect's .eval logs, the full transcripts

Two rules:
  * Provider credentials are stripped from the environment before any eval runs. Several
    inspect_evals scorers default their judge to a hardcoded `openai/gpt-4o*`; with the key
    gone, a judge that was not routed fails loudly instead of billing someone silently.
  * Validity flags never hide a number. A judge that could not grade, or an agent that never
    completed its task, is flagged next to the rate.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evalkit  # noqa: E402
import inspect_suite as suite  # noqa: E402


def extract(check: suite.Check, metrics: dict, completed: int | None) -> dict:
    """Read a check's headline number out of Inspect's flat `<scorer>.<metric>` dict."""
    raw = metrics.get(check.metric_key)
    out = {"value": None, "ci95": None, "normalized": None, "companion": None,
           "judge_unresolved_rate": None}
    if raw is not None and not math.isnan(float(raw)):
        rate = float(raw) / 100.0 if check.percent else float(raw)
        out["value"] = round(rate, 4)
        out["normalized"] = suite.normalize(rate, check.direction)
        if completed:
            out["ci95"] = [round(x, 4) for x in evalkit.wilson_ci(rate, completed)]
    if check.companion_key and metrics.get(check.companion_key) is not None:
        out["companion"] = {check.companion_key: round(float(metrics[check.companion_key]), 4)}
    if check.unresolved_key and completed and metrics.get(check.unresolved_key) is not None:
        out["judge_unresolved_rate"] = round(float(metrics[check.unresolved_key]) / completed, 4)
    return out


def unscored_rate(samples) -> float | None:
    """Share of per-sample scores that carry no verdict: a NaN value, or a scorer-reported
    grading failure. This is how an unusable judge shows up across scorer families."""
    total = failed = 0
    for sample in samples or []:
        for score in (getattr(sample, "scores", None) or {}).values():
            total += 1
            value = getattr(score, "value", None)
            meta = getattr(score, "metadata", None) or {}
            if (isinstance(value, float) and math.isnan(value)) or meta.get(
                    "unscored_reason") or meta.get("grader_failure_mode"):
                failed += 1
    return round(failed / total, 4) if total else None


def sample_rows(check: suite.Check, arm: str, samples) -> list[dict]:
    """One samples.jsonl row per sample: was the outcome good for the defender?"""
    rows = []
    for sample in samples or []:
        scores = list((getattr(sample, "scores", None) or {}).values())
        good = check.sample_good(getattr(scores[0], "value", None)) if scores else None
        rows.append({"arm": arm, "target": check.id, "sample": str(getattr(sample, "id", "")),
                     "epoch": getattr(sample, "epoch", 1), "good": good})
    return rows


def reproduces_headline(check: suite.Check, value: float | None, rows: list[dict],
                        tolerance: float = 0.02) -> bool | None:
    """Do the per-sample outcomes add up to the headline metric? None when it cannot be told.
    Guards the `good` rule in the suite against an upstream scorer change."""
    graded = [r["good"] for r in rows if r["good"] is not None]
    if value is None or not graded:
        return None
    good_rate = sum(graded) / len(graded)
    expected = value if check.direction == suite.HIGHER else 1 - value
    return abs(good_rate - expected) <= tolerance


def flags_for(check: suite.Check, row: dict, max_unresolved: float, min_utility: float) -> list:
    flags = [
        evalkit.validity_flag(
            "judge_unresolved", row.get("judge_unresolved_rate"), max_unresolved, "above",
            "the judge returned no usable verdict on this share of samples; the rate is "
            "computed over the rest"),
    ]
    for key, value in (row.get("companion") or {}).items():
        flags.append(evalkit.validity_flag(
            "low_utility", value, min_utility, "below",
            f"{key} is low: the agent rarely completed its task, so this security number "
            "mostly reflects failing to act"))
    if row.get("paired_ok") is False:
        flags.append({"flag": "samples_do_not_reproduce_headline", "observed": None,
                      "limit": None, "meaning": "per-sample outcomes do not add up to the "
                      "headline metric; the paired comparison is withheld for this benchmark "
                      "(the scorer may have changed upstream)"})
    done, total = row.get("samples_completed"), row.get("samples_total")
    if total and done is not None and done < total:
        flags.append({"flag": "partial", "observed": done, "limit": total,
                      "meaning": "not every sample produced a score"})
    return [f for f in flags if f]


def run_check(check: suite.Check, arm: dict, judge: str | None, depth: int | None,
              seed: int | None, log_dir: str, max_unresolved: float,
              min_utility: float) -> tuple[dict, list[dict]]:
    from inspect_ai import eval as inspect_eval

    row = {"check": check.id, "dimension": check.dimension, "arm": arm["name"],
           "model": arm["model"], "metric": check.metric_key, "direction": check.direction,
           "reads_as": check.reads_as, "judge": None, "flags": []}
    try:
        kwargs = dict(check.task_kwargs)
        roles = {}
        if check.needs_judge:
            if not judge:
                raise ValueError("needs a judge model: its scorer otherwise falls back to a "
                                 "hardcoded provider model")
            if judge == arm["model"]:
                raise ValueError("the judge is the model under test; pick a different judge")
            row["judge"] = judge
            kwargs.update({arg: judge for arg in check.judge_kwargs})
            roles = {role: judge for role in check.judge_roles}
        task = getattr(importlib.import_module(check.module), check.function)(**kwargs)
        log = inspect_eval(
            task, model=arm["model"],
            limit=suite.samples_for(check, depth) if depth is not None else None,
            # A seeded shuffle, then the limit: every arm gets the SAME n samples, drawn
            # across the dataset instead of from its first rows (several are sorted by
            # category).
            sample_shuffle=seed if depth is not None else None,
            epochs=check.epochs, log_dir=log_dir, display="none",
            **({"model_roles": roles} if roles else {}),
        )[0]
    except Exception as exc:  # noqa: BLE001 - one failed check must not stop the sweep
        row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        return row, []

    metrics = {f"{s.name}.{name}": m.value
               for s in (log.results.scores if log.results else [])
               for name, m in s.metrics.items()}
    completed = getattr(log.results, "completed_samples", None) if log.results else None
    row.update(extract(check, metrics, completed))
    samples = getattr(log, "samples", None)
    rows = sample_rows(check, arm["name"], samples)
    rates = [r for r in (row["judge_unresolved_rate"], unscored_rate(samples)) if r is not None]
    row.update({
        "judge_unresolved_rate": max(rates) if rates else None,
        "samples_completed": completed,
        "samples_total": getattr(log.results, "total_samples", None) if log.results else None,
        "paired_ok": reproduces_headline(check, row["value"], rows),
        "inspect_status": log.status,
        "error": str(log.error) if log.error else None,
        "all_metrics": metrics,
        "log": getattr(log, "location", None),
    })
    row["flags"] = flags_for(check, row, max_unresolved, min_utility)
    row["status"] = ("error" if row["error"] or log.status != "success"
                     else "no_score" if row["value"] is None else "ok")
    return row, rows


def run(arms: list[dict], checks: list[suite.Check], *, depth: int | None, seed: int | None,
        judge: str | None, out: str, settings: dict, max_unresolved: float = 0.05,
        min_utility: float = 0.3, keep_provider_env: bool = False) -> list[dict]:
    """Run every check for every arm. `settings` is recorded verbatim in results.json."""
    if not keep_provider_env:
        clean = evalkit.scrub_provider_credentials(dict(os.environ))
        os.environ.clear()
        os.environ.update(clean)
    out_dir = Path(out)
    (out_dir / "logs").mkdir(parents=True, exist_ok=True)
    samples_path = out_dir / "samples.jsonl"
    samples_path.write_text("")
    rows = []
    for arm in arms:
        for check in checks:
            print(f"[{arm['name']}] {check.id} ...", file=sys.stderr, flush=True)
            row, srows = run_check(check, arm, judge, depth, seed, str(out_dir / "logs"),
                                   max_unresolved, min_utility)
            names = ",".join(f["flag"] for f in row["flags"])
            print(f"[{arm['name']}] {check.id}: {row['status']} {row.get('value')} "
                  f"{('flags=' + names) if names else ''} {row.get('error') or ''}",
                  file=sys.stderr, flush=True)
            rows.append(row)
            evalkit.append_samples(samples_path, srows)
            # Rewritten after every check so an interrupted sweep keeps what finished.
            (out_dir / "results.json").write_text(json.dumps(
                {**settings, "judge": judge, "seed": seed,
                 "validity_limits": {"max_judge_unresolved": max_unresolved,
                                     "min_utility": min_utility},
                 "context": evalkit.load_context(), "rows": rows}, indent=2))
    return rows
