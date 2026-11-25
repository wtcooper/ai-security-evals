#!/usr/bin/env python3
"""Run the model-benchmark suite against one or more models.

    .venv-inspect/bin/python run_suite.py --models gemma4,qwen35 --judge gpt-judge \
        --checks core --depth standard --out <EXP>/results

    # second judge on a finished run: samples_regrade.jsonl, then judge_check.md
    .venv-inspect/bin/python run_suite.py --regrade-judge other-judge \
        --results <EXP>/results/results.json

The arms are the models. Each is an alias on ONE OpenAI-compatible gateway
(MODEL_BENCH_BASE_URL / MODEL_BENCH_API_KEY), or a full Inspect model string (anything
containing "/", e.g. anthropic/<id>) together with --keep-provider-env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import evalkit  # noqa: E402
import inspect_runner  # noqa: E402
import inspect_suite as suite  # noqa: E402
import judgecheck  # noqa: E402
import mt_checks  # noqa: E402

PROVIDER = "modelbench"   # Inspect reads MODELBENCH_BASE_URL / MODELBENCH_API_KEY


def model_string(name: str) -> str:
    """A bare alias is routed through the gateway; a string with '/' is passed to Inspect."""
    return name if "/" in name else f"openai-api/{PROVIDER}/{name}"


def _route(p: argparse.ArgumentParser, names: list[str]) -> None:
    """Point Inspect's provider at the gateway when any name is a bare alias."""
    if any("/" not in m for m in names):
        base = os.environ.get("MODEL_BENCH_BASE_URL")
        if not base:
            p.error("MODEL_BENCH_BASE_URL is not set (the OpenAI-compatible gateway URL ending in /v1)")
        os.environ[f"{PROVIDER.upper()}_BASE_URL"] = base
        os.environ[f"{PROVIDER.upper()}_API_KEY"] = os.environ.get("MODEL_BENCH_API_KEY") or "none"


def tag_corpus(path: Path, corpus: dict) -> None:
    """Add the multi-turn corpus fingerprint to that lane's samples rows."""
    if not path.is_file() or not corpus.get("sha256"):
        return
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for r in rows:
        if r.get("target") in mt_checks.CHECK_IDS:
            r["corpus"] = corpus["sha256"][:12]
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def regrade(args, p: argparse.ArgumentParser) -> int:
    """Re-score a finished run's logs with a second judge, then compare the two judges."""
    if not args.results:
        p.error("--regrade-judge needs --results <results.json> of the run to re-grade")
    results = Path(args.results)
    first = json.loads(results.read_text()).get("judge")
    second = model_string(args.regrade_judge)
    if second == first:
        p.error("the second judge is the run's judge; pick a different model")
    _route(p, [args.regrade_judge])
    mt_checks.register(suite)   # so the multi-turn checks can be re-scored too
    dest = inspect_runner.regrade(str(results), second, limit=args.regrade_limit,
                                  keep_provider_env=args.keep_provider_env)
    primary = results.with_name("samples.jsonl")
    tag = next((r["corpus"] for r in judgecheck.load(primary) if r.get("corpus")), None)
    if tag:   # the re-graded conversations are the run's own, so they keep its corpus
        tag_corpus(dest, {"sha256": tag})
    return judgecheck.main(["--primary", str(primary), "--secondary", str(dest),
                            "--out", str(results.parent)])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--models", help="comma-separated gateway aliases or Inspect model strings")
    p.add_argument("--judge", help="judge model (alias or Inspect string); needed by judged checks")
    p.add_argument("--auditor", help="multi-turn checks: the model that plays the user "
                   "(default: the judge); never a model under test")
    p.add_argument("--checks", default="core",
                   help="profile (core|nojudge|vision|multiturn|all) or comma-separated check ids")
    p.add_argument("--depth", default="standard", help="smoke (25) | standard (100) | full | N")
    p.add_argument("--epochs", "--repeats", dest="epochs", type=int,
                   help="run every sample N times (default 1); rows carry the epoch and the "
                        "report shows how often outcomes flip")
    p.add_argument("--seed", type=int, default=20260809, help="sample-selection seed")
    p.add_argument("--first-n", action="store_true", help="take the first N samples, no shuffle")
    p.add_argument("--max-judge-unresolved", type=float, default=0.05,
                   help="validity flag: share of samples the judge could not grade")
    p.add_argument("--min-utility", type=float, default=0.3,
                   help="validity flag: agent task completion below this")
    p.add_argument("--ceiling", type=float, default=0.95,
                   help="validity flag: every model at or above this share of good outcomes")
    p.add_argument("--out", default="results", help="output directory")
    p.add_argument("--plan-reason", help="why this run's plan differs from the one already "
                   "registered in --out (recorded with the amendment)")
    p.add_argument("--keep-provider-env", action="store_true",
                   help="do not strip provider API keys (needed for native provider strings)")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    p.add_argument("--regrade-judge", help="re-grade the run in --results with this second "
                   "judge (no model is re-run); writes samples_regrade.jsonl and judge_check.md")
    p.add_argument("--results", help="with --regrade-judge: that run's results.json")
    p.add_argument("--regrade-limit", type=int,
                   help="with --regrade-judge: re-grade only the first N samples of each check")
    args = p.parse_args(argv)
    if args.regrade_judge:
        return regrade(args, p)

    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    auditor = args.auditor or args.judge
    design = mt_checks.design_for(args.depth)
    mt_checks.register(suite, design=design, auditor=model_string(auditor) if auditor else None)
    checks = suite.resolve_checks(args.checks)
    depth = evalkit.resolve_depth(args.depth)
    epochs = args.epochs or 1
    multiturn = [c for c in checks if c.id in mt_checks.CHECK_IDS]
    rows = [{**r, "samples": r["samples"] * epochs, "calls": r["calls"] * epochs}
            for r in suite.plan_rows(checks, depth)]
    evalkit.print_plan(rows, arms=max(len(models), 1))
    if multiturn:
        print(mt_checks.plan_note(design, epochs), file=sys.stderr)
    if args.plan:
        return 0
    if not models:
        p.error("--models is required")
    if multiturn and auditor and model_string(auditor) in map(model_string, models):
        p.error("the auditor (--auditor, or the judge by default) is a model under test")
    _route(p, models + [m for m in (args.judge, auditor) if m])

    judge = model_string(args.judge) if args.judge else None
    seed = None if args.first_n else args.seed
    plan = {"arms": models, "baseline": models[0], "measures": [c.id for c in checks],
            "depth": depth, "seed": seed, "epochs": args.epochs, "repeats": epochs,
            "judge": judge, "criteria": evalkit.criteria_record()}
    corpus = evalkit.corpus_record(mt_checks.corpus_files(), bundled=True)
    if multiturn:
        plan.update({"auditor": model_string(auditor) if auditor else None, "corpus": corpus,
                     "multiturn": {"design": design, "rubric": mt_checks.RUBRIC_VERSION,
                                   "user_turns": mt_checks.MAX_USER_TURNS,
                                   "slices": ["topic", *mt_checks.FACTORS]}})
    results = inspect_runner.run(
        [{"name": m, "model": model_string(m)} for m in models], checks,
        depth=depth, seed=seed, judge=judge, out=args.out,
        settings={"suite": "model-benchmark", "checks": args.checks, "depth": args.depth,
                  **({"multiturn_design": design, "auditor": plan["auditor"]} if multiturn else {})},
        max_unresolved=args.max_judge_unresolved, min_utility=args.min_utility,
        keep_provider_env=args.keep_provider_env, epochs=args.epochs, ceiling=args.ceiling,
        plan=plan, plan_reason=args.plan_reason)
    if multiturn:
        tag_corpus(Path(args.out) / "samples.jsonl", corpus)
    print(Path(args.out) / "results.json")
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
