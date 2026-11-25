#!/usr/bin/env python3
"""In-line mode: run benchmarks with the SAME model behind each guardrail arm.

    SHIM_GATEWAY_URL=http://localhost:4000 SHIM_GATEWAY_KEY=$KEY \
    .venv-inspect/bin/python run_inline.py --arms arms.json --model <model> \
        --judge <judge> --checks guardrail --depth standard [--epochs 3] --out <EXP>/results

    # later: re-grade the saved replies with a second judge, then compare the two judges
    SHIM_GATEWAY_URL=... .venv-inspect/bin/python run_inline.py \
        --regrade <EXP>/results/results.json --judge <second-judge> [--regrade-limit 50]

The arms are guardrail configurations (arms.json: a baseline with no guardrail, then one
entry per guardrail). One injection shim per arm adds that arm's guardrail to every request
and turns a guardrail block into a refusal the benchmark can score. Everything else, the
model included, is identical across arms, and every arm sees the same seeded samples.

The judge is reached on the gateway directly, never through a guardrail, and is never the
model under test. The analysis plan (arms, baseline, checks, depth, seed, epochs, judge,
model, guardrails, the organisation's criteria file) is registered in <out>/plan.json before
the first sample runs; report.py shows it with any departure. --regrade re-scores the saved
logs with a second judge (samples_regrade.jsonl) and writes judge_check.md beside them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import evalkit  # noqa: E402
import injection_shim as shim  # noqa: E402
import inspect_runner  # noqa: E402
import inspect_suite as suite  # noqa: E402
import judgecheck  # noqa: E402
from connectors.base import Connector  # noqa: E402

JUDGE_PROVIDER = "gbjudge"


def provider(arm_name: str) -> str:
    """Inspect provider name for an arm. Prefixed so its env vars can never collide with a
    real provider's (an arm called `azure` must not read or lose AZURE_API_KEY)."""
    return "gb-" + "".join(c if c.isalnum() else "-" for c in arm_name.lower())


def env_name(provider_name: str) -> str:
    return provider_name.upper().replace("-", "_")


def load_arms(path: str) -> list:
    arms = [shim.arm_from_dict(d) for d in json.loads(Path(path).read_text())]
    names = [a.name for a in arms]
    if len(set(names)) != len(names) or not arms:
        raise ValueError(f"arm names must be unique and non-empty: {names}")
    if all(a.guardrails for a in arms):
        raise ValueError("no baseline arm: include one entry with no guardrails, e.g. "
                         '{"name": "baseline"}')
    return arms


def start_shims(arms: list, gateway_url: str, gateway_key: str | None, base_port: int,
                connector_id: str) -> dict:
    """One shim per arm on consecutive local ports; returns {arm name: base URL}."""
    connector = Connector.from_id(connector_id)
    urls = {}
    for i, arm in enumerate(arms):
        port = base_port + i
        shim._serve(shim.make_handler(connector, arm, gateway_url, gateway_key,
                                      shim._block_as_refusal_enabled()), port, daemon=True)
        urls[arm.name] = f"http://127.0.0.1:{port}/v1"
        os.environ[f"{env_name(provider(arm.name))}_BASE_URL"] = urls[arm.name]
        os.environ[f"{env_name(provider(arm.name))}_API_KEY"] = "shim"
    return urls


def route_judge(name: str, gateway_url: str | None, gateway_key: str | None) -> str:
    """An Inspect model string for the judge. A bare model name is reached on the gateway
    directly (never through a shim, so never through a guardrail)."""
    if "/" in name:
        return name
    if not gateway_url:
        raise SystemExit("SHIM_GATEWAY_URL is not set (the gateway the judge is reached on)")
    os.environ[f"{env_name(JUDGE_PROVIDER)}_BASE_URL"] = gateway_url.rstrip("/") + "/v1"
    os.environ[f"{env_name(JUDGE_PROVIDER)}_API_KEY"] = gateway_key or "none"
    return f"openai-api/{JUDGE_PROVIDER}/{name}"


def same_model(judge: str | None, model: str | None) -> bool:
    """Is this judge (a bare name or an Inspect string) the given model?"""
    return bool(judge and model) and (judge == model or judge.endswith("/" + model))


def baseline_name(arms: list) -> str:
    return next(a.name for a in arms if not a.guardrails)


def regrade(args, p) -> int:
    """Re-score a finished run's saved logs with a second judge; no model is called again."""
    results = Path(args.regrade)
    if not results.is_file():
        p.error(f"no results.json at {results}")
    if not args.judge:
        p.error("--regrade needs --judge: the second judge")
    run = json.loads(results.read_text())
    if same_model(args.judge, run.get("model")):
        p.error("the second judge is the model under test; pick a different judge")
    judge = route_judge(args.judge, os.environ.get("SHIM_GATEWAY_URL"),
                        os.environ.get("SHIM_GATEWAY_KEY"))
    if judge == run.get("judge"):
        p.error("the second judge must differ from the run's judge")
    # Inspect re-creates each arm's model client from the log while re-scoring. No arm is
    # called again, so point every arm provider at a closed local port: a call fails at once.
    for row in run.get("rows", []):
        parts = str(row.get("model", "")).split("/")
        if len(parts) > 2 and parts[0] == "openai-api":
            os.environ[f"{env_name(parts[1])}_BASE_URL"] = "http://127.0.0.1:9/v1"
            os.environ[f"{env_name(parts[1])}_API_KEY"] = "regrade-calls-no-arm"
    dest = inspect_runner.regrade(str(results), judge, limit=args.regrade_limit)
    judgecheck.main(["--primary", str(results.with_name("samples.jsonl")),
                     "--secondary", str(dest), "--out", str(results.parent)])
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--arms", default="arms.json", help="JSON list of guardrail arms")
    p.add_argument("--model", help="the model under every arm, as the gateway names it")
    p.add_argument("--judge", help="judge model on the gateway (or a full Inspect string); "
                   "with --regrade, the second judge")
    p.add_argument("--checks", default="guardrail",
                   help="profile (guardrail|core|nojudge|all) or comma-separated check ids")
    p.add_argument("--depth", default="standard", help="smoke (25) | standard (100) | full | N")
    p.add_argument("--seed", type=int, default=20260809)
    p.add_argument("--base-port", type=int, default=8901)
    p.add_argument("--max-judge-unresolved", type=float, default=0.05,
                   help="validity flag: share of samples the judge could not grade")
    p.add_argument("--min-utility", type=float, default=0.3,
                   help="validity flag: agent task completion below this")
    p.add_argument("--epochs", type=int, default=None,
                   help="run every sample N times; the report shows how often outcomes changed")
    p.add_argument("--ceiling", type=float, default=0.95,
                   help="validity flag: every arm's good-outcome rate at or above this")
    p.add_argument("--plan-reason", default=None,
                   help="why this run's plan differs from the one registered in --out")
    p.add_argument("--regrade", metavar="RESULTS_JSON", default=None,
                   help="re-score that run's saved logs with --judge (a second judge) and write "
                        "judge_check.md; runs no model")
    p.add_argument("--regrade-limit", type=int, default=None,
                   help="with --regrade: re-score only the first N samples of each log")
    p.add_argument("--out", default="results")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    args = p.parse_args(argv)
    if args.regrade:
        return regrade(args, p)

    checks = suite.resolve_checks(args.checks)
    depth = evalkit.resolve_depth(args.depth)
    arms = load_arms(args.arms) if Path(args.arms).is_file() else []
    rows = suite.plan_rows(checks, depth)
    if args.epochs and args.epochs > 1:
        for r in rows:       # repeats of a case are not new cases: n (and power) stay per sample
            r["calls"] *= args.epochs
            r["note"] += f" x{args.epochs} epochs"
    evalkit.print_plan(rows, arms=max(len(arms), 1))
    if args.plan:
        return 0
    if not arms:
        p.error(f"arms file not found: {args.arms}")
    if not args.model:
        p.error("--model is required (the same model runs behind every arm)")
    if same_model(args.judge, args.model):
        p.error("the judge is the model under test; pick a different judge")
    gateway_url = os.environ.get("SHIM_GATEWAY_URL")
    if not gateway_url:
        p.error("SHIM_GATEWAY_URL is not set (the gateway that applies the guardrails)")
    gateway_key = os.environ.get("SHIM_GATEWAY_KEY")

    start_shims(arms, gateway_url, gateway_key, args.base_port,
                os.environ.get("SHIM_CONNECTOR", "litellm"))
    judge = route_judge(args.judge, gateway_url, gateway_key) if args.judge else None
    plan = {"arms": [a.name for a in arms], "baseline": baseline_name(arms),
            "measures": [c.id for c in checks], "depth": args.depth, "seed": args.seed,
            "epochs": args.epochs, "judge": judge, "model": args.model,
            "guardrails": {a.name: list(a.guardrails) for a in arms}, "ceiling": args.ceiling,
            "criteria": evalkit.criteria_record()}

    rows = inspect_runner.run(
        [{"name": a.name, "model": f"openai-api/{provider(a.name)}/{args.model}"} for a in arms],
        checks, depth=depth, seed=args.seed, judge=judge, out=args.out,
        settings={"suite": "guardrail-benchmark/inline", "checks": args.checks,
                  "depth": args.depth, "model": args.model,
                  "arms": [{"name": a.name, "guardrails": list(a.guardrails)} for a in arms]},
        max_unresolved=args.max_judge_unresolved, min_utility=args.min_utility,
        epochs=args.epochs, ceiling=args.ceiling, plan=plan, plan_reason=args.plan_reason)
    print(Path(args.out) / "results.json")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
