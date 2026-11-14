#!/usr/bin/env python3
"""Run the model-benchmark suite against one or more models.

    .venv-inspect/bin/python run_suite.py --models gemma4,qwen35 --judge gpt-judge \
        --checks core --depth standard --out <EXP>/results

The arms are the models. Each is an alias on ONE OpenAI-compatible gateway
(MODEL_BENCH_BASE_URL / MODEL_BENCH_API_KEY), or a full Inspect model string (anything
containing "/", e.g. anthropic/<id>) together with --keep-provider-env.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import evalkit  # noqa: E402
import inspect_runner  # noqa: E402
import inspect_suite as suite  # noqa: E402

PROVIDER = "modelbench"   # Inspect reads MODELBENCH_BASE_URL / MODELBENCH_API_KEY


def model_string(name: str) -> str:
    """A bare alias is routed through the gateway; a string with '/' is passed to Inspect."""
    return name if "/" in name else f"openai-api/{PROVIDER}/{name}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--models", help="comma-separated gateway aliases or Inspect model strings")
    p.add_argument("--judge", help="judge model (alias or Inspect string); needed by judged checks")
    p.add_argument("--checks", default="core",
                   help="profile (core|nojudge|vision|all) or comma-separated check ids")
    p.add_argument("--depth", default="standard", help="smoke (25) | standard (100) | full | N")
    p.add_argument("--seed", type=int, default=20260809, help="sample-selection seed")
    p.add_argument("--first-n", action="store_true", help="take the first N samples, no shuffle")
    p.add_argument("--max-judge-unresolved", type=float, default=0.05,
                   help="validity flag: share of samples the judge could not grade")
    p.add_argument("--min-utility", type=float, default=0.3,
                   help="validity flag: agent task completion below this")
    p.add_argument("--out", default="results", help="output directory")
    p.add_argument("--keep-provider-env", action="store_true",
                   help="do not strip provider API keys (needed for native provider strings)")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    args = p.parse_args(argv)

    checks = suite.resolve_checks(args.checks)
    depth = evalkit.resolve_depth(args.depth)
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    evalkit.print_plan(suite.plan_rows(checks, depth), arms=max(len(models), 1))
    if args.plan:
        return 0
    if not models:
        p.error("--models is required")
    if any("/" not in m for m in models + ([args.judge] if args.judge else [])):
        base = os.environ.get("MODEL_BENCH_BASE_URL")
        if not base:
            p.error("MODEL_BENCH_BASE_URL is not set (the OpenAI-compatible gateway URL ending in /v1)")
        os.environ[f"{PROVIDER.upper()}_BASE_URL"] = base
        os.environ[f"{PROVIDER.upper()}_API_KEY"] = os.environ.get("MODEL_BENCH_API_KEY") or "none"

    rows = inspect_runner.run(
        [{"name": m, "model": model_string(m)} for m in models], checks,
        depth=depth, seed=None if args.first_n else args.seed,
        judge=model_string(args.judge) if args.judge else None, out=args.out,
        settings={"suite": "model-benchmark", "checks": args.checks, "depth": args.depth},
        max_unresolved=args.max_judge_unresolved, min_utility=args.min_utility,
        keep_provider_env=args.keep_provider_env)
    print(Path(args.out) / "results.json")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
