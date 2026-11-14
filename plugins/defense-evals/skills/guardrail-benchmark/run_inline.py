#!/usr/bin/env python3
"""In-line mode: run benchmarks with the SAME model behind each guardrail arm.

    SHIM_GATEWAY_URL=http://localhost:4000 SHIM_GATEWAY_KEY=$KEY \
    .venv-inspect/bin/python run_inline.py --arms arms.json --model <model> \
        --judge <judge> --checks guardrail --depth standard --out <EXP>/results

The arms are guardrail configurations (arms.json: a baseline with no guardrail, then one
entry per guardrail). One injection shim per arm adds that arm's guardrail to every request
and turns a guardrail block into a refusal the benchmark can score. Everything else, the
model included, is identical across arms, and every arm sees the same seeded samples.

The judge is reached on the gateway directly, never through a guardrail.
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--arms", default="arms.json", help="JSON list of guardrail arms")
    p.add_argument("--model", help="the model under every arm, as the gateway names it")
    p.add_argument("--judge", help="judge model on the gateway (or a full Inspect string)")
    p.add_argument("--checks", default="guardrail",
                   help="profile (guardrail|core|nojudge|all) or comma-separated check ids")
    p.add_argument("--depth", default="standard", help="smoke (25) | standard (100) | full | N")
    p.add_argument("--seed", type=int, default=20260809)
    p.add_argument("--base-port", type=int, default=8901)
    p.add_argument("--max-judge-unresolved", type=float, default=0.05,
                   help="validity flag: share of samples the judge could not grade")
    p.add_argument("--min-utility", type=float, default=0.3,
                   help="validity flag: agent task completion below this")
    p.add_argument("--out", default="results")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    args = p.parse_args(argv)

    checks = suite.resolve_checks(args.checks)
    depth = evalkit.resolve_depth(args.depth)
    arms = load_arms(args.arms) if Path(args.arms).is_file() else []
    evalkit.print_plan(suite.plan_rows(checks, depth), arms=max(len(arms), 1))
    if args.plan:
        return 0
    if not arms:
        p.error(f"arms file not found: {args.arms}")
    if not args.model:
        p.error("--model is required (the same model runs behind every arm)")
    gateway_url = os.environ.get("SHIM_GATEWAY_URL")
    if not gateway_url:
        p.error("SHIM_GATEWAY_URL is not set (the gateway that applies the guardrails)")
    gateway_key = os.environ.get("SHIM_GATEWAY_KEY")

    start_shims(arms, gateway_url, gateway_key, args.base_port,
                os.environ.get("SHIM_CONNECTOR", "litellm"))
    judge = None
    if args.judge:
        judge = args.judge if "/" in args.judge else f"openai-api/{JUDGE_PROVIDER}/{args.judge}"
        os.environ[f"{env_name(JUDGE_PROVIDER)}_BASE_URL"] = gateway_url.rstrip("/") + "/v1"
        os.environ[f"{env_name(JUDGE_PROVIDER)}_API_KEY"] = gateway_key or "none"

    rows = inspect_runner.run(
        [{"name": a.name, "model": f"openai-api/{provider(a.name)}/{args.model}"} for a in arms],
        checks, depth=depth, seed=args.seed, judge=judge, out=args.out,
        settings={"suite": "guardrail-benchmark/inline", "checks": args.checks,
                  "depth": args.depth, "model": args.model,
                  "arms": [{"name": a.name, "guardrails": list(a.guardrails)} for a in arms]},
        max_unresolved=args.max_judge_unresolved, min_utility=args.min_utility)
    print(Path(args.out) / "results.json")
    return 0 if all(r["status"] == "ok" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
