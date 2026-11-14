#!/usr/bin/env python3
"""Run the model-bench suite against one or more models and write results.json.

    .venv-inspect/bin/python run_suite.py --models gemma4,qwen35 --judge gpt-judge \
        --checks core --depth good --out <EXP>/results

Models are aliases on ONE OpenAI-compatible gateway (MODEL_BENCH_BASE_URL / _API_KEY),
or full Inspect model strings (anything containing "/", e.g. anthropic/<id>) with
--keep-provider-env.

Two rules carried over from the governance tool this suite came from:

* Provider credentials are stripped from the environment before any eval runs. Several
  inspect_evals scorers default their judge to a hardcoded `openai/gpt-4o*`; with the key
  gone, a judge that was not routed fails loudly instead of billing someone silently.
* A judge that returns no usable verdict voids the check. An unparsed verdict otherwise
  reads as "the subject did not comply" and flatters the model under test.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import suite  # noqa: E402

PROVIDER = "modelbench"   # Inspect reads MODELBENCH_BASE_URL / MODELBENCH_API_KEY
SCRUB_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "AZURE_", "AWS_")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")
SCRUB_EXACT = ("MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY")


def scrub_provider_credentials(env: dict) -> dict:
    """Drop provider credentials; keep everything else (incl. HF_TOKEN for gated datasets)."""
    return {k: v for k, v in env.items()
            if k not in SCRUB_EXACT
            and not (k.startswith(SCRUB_PREFIXES) and k.endswith(SCRUB_SUFFIXES))}


def model_string(name: str) -> str:
    """A bare alias is routed through the gateway; a string with '/' is passed to Inspect."""
    return name if "/" in name else f"openai-api/{PROVIDER}/{name}"


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
            out["ci95"] = [round(x, 4) for x in suite.wilson_ci(rate, completed)]
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


def status_for(row: dict, max_unresolved: float) -> str:
    if row.get("error") or row.get("inspect_status") != "success":
        return "error"
    unresolved = row.get("judge_unresolved_rate")
    if unresolved is not None and unresolved > max_unresolved:
        return "void_judge"
    if row.get("value") is None:
        return "no_score"
    return "ok"


def run_check(check: suite.Check, model: str, judge: str | None, depth: int | None,
              seed: int | None, log_dir: str, max_unresolved: float) -> dict:
    from inspect_ai import eval as inspect_eval

    row = {"check": check.id, "dimension": check.dimension, "model": model,
           "metric": check.metric_key, "direction": check.direction, "judge": None}
    try:
        kwargs = dict(check.task_kwargs)
        roles = {}
        if check.needs_judge:
            if not judge:
                raise ValueError("needs --judge: its scorer otherwise falls back to a "
                                 "hardcoded provider model")
            row["judge"] = judge
            kwargs.update({arg: model_string(judge) for arg in check.judge_kwargs})
            roles = {role: model_string(judge) for role in check.judge_roles}
        task = getattr(importlib.import_module(check.module), check.function)(**kwargs)
        log = inspect_eval(
            task, model=model_string(model),
            limit=suite.samples_for(check, depth) if depth is not None else None,
            # A seeded shuffle, then the limit: every model gets the SAME n samples, drawn
            # across the dataset instead of from its first rows (which are sorted by
            # category in several of these datasets).
            sample_shuffle=seed if depth is not None else None,
            epochs=check.epochs, log_dir=log_dir, display="none",
            **({"model_roles": roles} if roles else {}),
        )[0]
    except Exception as exc:  # noqa: BLE001 - one failed check must not stop the sweep
        row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        return row

    metrics = {f"{s.name}.{name}": m.value
               for s in (log.results.scores if log.results else [])
               for name, m in s.metrics.items()}
    completed = getattr(log.results, "completed_samples", None) if log.results else None
    row.update(extract(check, metrics, completed))
    parse_fail = unscored_rate(getattr(log, "samples", None))
    rates = [r for r in (row["judge_unresolved_rate"], parse_fail) if r is not None]
    row.update({
        "judge_unresolved_rate": max(rates) if rates else None,
        "samples_completed": completed,
        "samples_total": getattr(log.results, "total_samples", None) if log.results else None,
        "inspect_status": log.status,
        "error": str(log.error) if log.error else None,
        "all_metrics": metrics,
        "log": getattr(log, "location", None),
    })
    row["status"] = status_for(row, max_unresolved)
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--models", help="comma-separated gateway aliases or Inspect model strings")
    p.add_argument("--judge", help="judge model (alias or Inspect string); required by judged checks")
    p.add_argument("--checks", default="core", help="profile (core|nojudge|all) or check ids")
    p.add_argument("--depth", default="good", help="quick (25) | good (100) | full | N")
    p.add_argument("--seed", type=int, default=20260809, help="sample-selection seed")
    p.add_argument("--first-n", action="store_true", help="take the first N samples, no shuffle")
    p.add_argument("--max-judge-unresolved", type=float, default=0.05)
    p.add_argument("--out", default="results", help="output directory")
    p.add_argument("--keep-provider-env", action="store_true",
                   help="do not strip provider API keys (needed for native provider strings)")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    args = p.parse_args(argv)

    checks = suite.resolve_checks(args.checks)
    depth = suite.resolve_depth(args.depth)
    plan = suite.plan(checks, depth)
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    print(f"plan: {len(checks)} checks x {max(len(models), 1)} model(s), per model "
          f"{plan['samples']} tests / ~{plan['calls']} model calls", file=sys.stderr)
    for r in plan["rows"]:
        print(f"  {r['check']:<40} n={r['samples']:<5} calls~{r['calls']:<6}"
              f"{' judge' if r['judge'] else ''}", file=sys.stderr)
    if args.plan:
        return 0
    if not models:
        p.error("--models is required")

    if not args.keep_provider_env:
        clean = scrub_provider_credentials(dict(os.environ))
        os.environ.clear()
        os.environ.update(clean)
    if any("/" not in m for m in models + ([args.judge] if args.judge else [])):
        base, key = os.environ.get("MODEL_BENCH_BASE_URL"), os.environ.get("MODEL_BENCH_API_KEY")
        if not base:
            p.error("MODEL_BENCH_BASE_URL is not set (the OpenAI-compatible gateway URL ending in /v1)")
        os.environ[f"{PROVIDER.upper()}_BASE_URL"] = base
        os.environ[f"{PROVIDER.upper()}_API_KEY"] = key or "none"

    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    rows = []
    for model in models:
        for check in checks:
            print(f"[{model}] {check.id} ...", file=sys.stderr, flush=True)
            row = run_check(check, model, args.judge, depth, None if args.first_n else args.seed,
                            str(out / "logs"), args.max_judge_unresolved)
            print(f"[{model}] {check.id}: {row['status']} "
                  f"{row.get('value')} {row.get('error') or ''}", file=sys.stderr, flush=True)
            rows.append(row)
            # Rewritten after every check so an interrupted sweep keeps what finished.
            (out / "results.json").write_text(json.dumps({
                "suite": "model-bench", "checks": args.checks, "depth": args.depth,
                "seed": None if args.first_n else args.seed, "judge": args.judge,
                "max_judge_unresolved": args.max_judge_unresolved, "rows": rows}, indent=2))
    print(out / "results.json")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
