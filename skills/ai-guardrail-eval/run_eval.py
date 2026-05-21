#!/usr/bin/env python3
"""
run_eval.py - CLI for guardrail evaluation against a LiteLLM gateway.

Every test outcome is classified by an LLM-as-judge (REQUIRED, not optional).
There is NO keyword classification. You must supply judge endpoint details
via --judge-* flags or environment variables.

Three things this script handles:
  1. Three modes:   input | output | baseline (no guardrails)
  2. Three tiers:   smoke (100) | standard (300) | comprehensive (600+)
  3. One provider:  litellm (others scaffolded but not implemented)

Examples
--------
# Smoke test against the local LiteLLM proxy with mock target and judge.
python run_eval.py --guardrail none --model mock-target-refusal \\
    --base-url http://localhost:4000 --api-key sk-mock --judge-model mock-judge \\
    --experiment-name local_mock_baseline

# Real guardrail comparison once you've swapped mock models for real ones in
# local/litellm_config.yaml:
python run_eval.py --guardrail panw-prisma-airs-pre --tier standard \\
    --experiment-name standard_panw_pre

# Compare two guardrails head-to-head (run twice with different --experiment-name)
python run_eval.py --guardrail panw-prisma-airs-pre --experiment-name g_panw
python run_eval.py --guardrail bedrock-pre --experiment-name g_bedrock

Environment variables:
    LITELLM_BASE_URL   default http://localhost:4000
    LITELLM_API_KEY    default sk-mock
    JUDGE_BASE_URL     defaults to LITELLM_BASE_URL
    JUDGE_API_KEY      defaults to LITELLM_API_KEY
    JUDGE_MODEL        default gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from guardrail_eval.corpus import (
    load_all,
    load_static_corpus,
    load_static_suite,
    validate_benign_present,
    DATASET_LOADERS,
    TIER_SIZES,
    DEFAULT_CORPUS_PATH,
)
from guardrail_eval.providers import PROVIDERS, make_provider
from guardrail_eval.runner import GuardrailTester
from guardrail_eval.judge import LLMJudge
from guardrail_eval.metrics import (
    compute_metrics,
    compute_metrics_by_category,
    compute_metrics_by_source,
    compute_replicate_stability,
    latency_stats,
    print_report,
)


# Repo root: skills/ai-guardrail-eval/run_eval.py -> two levels up.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_EXPERIMENTS_DIR = _REPO_ROOT / ".evals" / "experiments"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate guardrails (or baseline model) against standardized benchmarks via LiteLLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # ---- what to test ----------------------------------------------------
    p.add_argument(
        "--guardrail",
        required=True,
        help="Guardrail name(s) as registered in your LiteLLM config. "
             "Multiple = comma-separated. Use 'none' for baseline mode "
             "(no guardrails, real LLM call, judge classifies the response).",
    )
    p.add_argument(
        "--mode",
        choices=["input", "output", "baseline"],
        default=None,
        help="input (pre_call), output (post_call), or baseline (no guardrails). "
             "Defaults: 'input' normally; 'baseline' if --guardrail none.",
    )

    # ---- where to test ---------------------------------------------------
    p.add_argument(
        "--provider",
        choices=list(PROVIDERS.keys()),
        default="litellm",
        help="Gateway provider. 'litellm' is the only fully implemented "
             "option in this version; the others are scaffolded.",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
        help="LiteLLM gateway URL. Env: LITELLM_BASE_URL (default http://localhost:4000).",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("LITELLM_API_KEY", "sk-mock"),
        help="LiteLLM gateway API key. Env: LITELLM_API_KEY (default sk-mock).",
    )
    p.add_argument(
        "--model",
        default="mock-target-refusal",
        help="Model name as registered in LiteLLM's model_list. "
             "Defaults to mock-target-refusal for the local mock proxy.",
    )

    # ---- what corpus -----------------------------------------------------
    p.add_argument(
        "--tier",
        choices=list(TIER_SIZES.keys()),
        default="smoke",
        help="Static corpus tier: smoke (100), standard (300), comprehensive (600).",
    )
    p.add_argument(
        "--corpus",
        default=None,
        help="Path to a corpus JSON file (defaults to the bundled "
             "data/corpus_v1.json; pass a rebuilt corpus from .evals/corpus/ "
             "for the full multi-turn version).",
    )
    p.add_argument(
        "--datasets",
        nargs="+",
        default=None,
        choices=list(DATASET_LOADERS.keys()),
        help="Override the static suite with dynamic dataset loading.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit per dataset (only applies with --datasets).",
    )

    # ---- judge -----------------------------------------------------------
    p.add_argument(
        "--judge-base-url",
        default=os.environ.get("JUDGE_BASE_URL") or os.environ.get("LITELLM_BASE_URL", "http://localhost:4000"),
        help="Judge endpoint (OpenAI-compatible /v1/chat/completions). "
             "Env: JUDGE_BASE_URL, falls back to LITELLM_BASE_URL.",
    )
    p.add_argument(
        "--judge-api-key",
        default=os.environ.get("JUDGE_API_KEY") or os.environ.get("LITELLM_API_KEY", "sk-mock"),
        help="Judge API key. Env: JUDGE_API_KEY, falls back to LITELLM_API_KEY.",
    )
    p.add_argument(
        "--judge-model",
        default=os.environ.get("JUDGE_MODEL", "gpt-4o-mini"),
        help="Model name for the judge. Env: JUDGE_MODEL. Default gpt-4o-mini. "
             "For the local mock proxy, use mock-judge.",
    )
    p.add_argument(
        "--judge-concurrency", type=int, default=10,
        help="Max concurrent in-flight judge calls.",
    )

    # ---- how -------------------------------------------------------------
    p.add_argument("--replicates", type=int, default=1,
                   help="Run each case this many times to measure stability.")
    p.add_argument("--concurrency", type=int, default=10, help="Worker pool size.")
    p.add_argument("--timeout-s", type=float, default=30.0, help="HTTP timeout per call.")
    p.add_argument("--quiet", action="store_true", help="Suppress progress bar.")
    p.add_argument("--min-benign", type=int, default=10,
                   help="Minimum benign cases required (else error - F1 not meaningful).")

    # ---- outputs ---------------------------------------------------------
    p.add_argument(
        "--experiment-name",
        default=None,
        help="Name this experiment. Outputs go to "
             ".evals/experiments/<name>/{config,results,metrics,transcript}.json. "
             "Default: auto-generated as {tier}_{guardrail-or-baseline}_{timestamp}.",
    )
    p.add_argument(
        "--experiments-dir",
        default=str(_DEFAULT_EXPERIMENTS_DIR),
        help="Root directory for experiment outputs (default: <repo>/.evals/experiments).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing experiment directory if it exists.",
    )

    return p.parse_args()


def resolve_guardrails_and_mode(args):
    """
    Map --guardrail flag and --mode flag to (guardrails_list, mode_string).

    --guardrail none -> baseline mode, no guardrails
    --guardrail name1,name2 -> mode defaults to 'input' if not given
    """
    raw = args.guardrail.strip().lower()
    if raw in ("none", ""):
        mode = args.mode or "baseline"
        if mode != "baseline":
            print(
                f"[WARN] --guardrail none implies baseline mode but --mode={mode} "
                f"was passed. Switching to baseline.",
                file=sys.stderr,
            )
            mode = "baseline"
        return None, mode

    guardrails = [g.strip() for g in args.guardrail.split(",") if g.strip()]
    mode = args.mode or "input"
    if mode == "baseline":
        print(
            "[WARN] --mode baseline given alongside guardrails - the guardrails "
            "will be ignored in baseline mode.",
            file=sys.stderr,
        )
        guardrails = None
    return guardrails, mode


def resolve_experiment_name(args, guardrails) -> str:
    if args.experiment_name:
        return args.experiment_name
    tag = "baseline" if guardrails is None else "_".join(guardrails)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{args.tier}_{tag}_{ts}"


def warn_if_partial_corpus(corpus_path: Path) -> None:
    """Read the corpus JSON metadata and print a stderr warning if is_partial."""
    try:
        raw = load_static_corpus(str(corpus_path))
    except FileNotFoundError:
        return
    if raw.get("is_partial"):
        missing = raw.get("missing_sources") or []
        reason = raw.get("partial_reason") or ""
        print(
            "[WARN] Corpus is marked is_partial=true. "
            f"Missing sources: {missing}. "
            f"{reason} "
            "Rebuild with scripts/build_corpus.py "
            "(set HF_TOKEN for gated MHJ/AgentHarm) and write to "
            ".evals/corpus/corpus_v1_full.json, then pass --corpus to use it.",
            file=sys.stderr,
        )


async def main_async(args):
    # ---- corpus ----------------------------------------------------------
    corpus_path = None
    if args.datasets is None:
        corpus_path = Path(args.corpus) if args.corpus else DEFAULT_CORPUS_PATH
        print(f"Loading STATIC corpus tier='{args.tier}' from {corpus_path}...")
        try:
            cases = load_static_suite(tier=args.tier, path=str(corpus_path))
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            print("  Run: python scripts/build_corpus.py", file=sys.stderr)
            return 1
        warn_if_partial_corpus(corpus_path)
    else:
        print(f"Loading custom datasets: {args.datasets}")
        cases = load_all(args.datasets, limit_per_dataset=args.limit)

    if not cases:
        print("[ERROR] No cases loaded.", file=sys.stderr)
        return 1

    try:
        validate_benign_present(cases, min_benign=args.min_benign)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    harmful = sum(1 for c in cases if c.label == "harmful")
    benign = sum(1 for c in cases if c.label == "benign")
    print(f"Corpus: {len(cases)} cases (harmful={harmful}, benign={benign})")

    # ---- guardrails + mode ----------------------------------------------
    guardrails, mode = resolve_guardrails_and_mode(args)

    # ---- experiment output dir ------------------------------------------
    exp_name = resolve_experiment_name(args, guardrails)
    exp_dir = Path(args.experiments_dir) / exp_name
    if exp_dir.exists() and not args.force:
        print(
            f"[ERROR] Experiment directory already exists: {exp_dir}\n"
            f"  Choose a different --experiment-name or pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1
    exp_dir.mkdir(parents=True, exist_ok=True)
    print(f"Experiment outputs -> {exp_dir}")

    # Judge-vs-target same-model check
    if args.judge_model == args.model:
        print(
            f"[WARN] Judge model ({args.judge_model}) is identical to the target "
            "model. This biases the eval (judge-self-assessment); use a different "
            "judge unless you're explicitly testing judge stability.",
            file=sys.stderr,
        )

    # ---- provider --------------------------------------------------------
    provider = make_provider(
        kind=args.provider,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_s=args.timeout_s,
        concurrency=args.concurrency,
    )

    # ---- judge -----------------------------------------------------------
    judge = LLMJudge(
        base_url=args.judge_base_url,
        api_key=args.judge_api_key,
        model=args.judge_model,
        timeout_s=args.timeout_s,
        concurrency=args.judge_concurrency,
    )

    total = len(cases) * args.replicates
    print(
        f"\nProvider: {args.provider}  |  Mode: {mode}  |  "
        f"Guardrails: {guardrails or 'NONE (baseline)'}"
    )
    print(f"Endpoint: {args.base_url}  |  Model: {args.model}")
    print(f"Judge:    {args.judge_base_url}  |  Judge model: {args.judge_model}")
    print(f"Replicates: {args.replicates}  |  Total calls: {total}  |  Workers: {args.concurrency}\n")

    # ---- run -------------------------------------------------------------
    async with provider, judge:
        tester = GuardrailTester(
            provider=provider, judge=judge, model=args.model, concurrency=args.concurrency,
        )
        results = await tester.run_batch(
            cases=cases,
            guardrails=guardrails,
            mode=mode,
            replicates=args.replicates,
            show_progress=not args.quiet,
        )

    # ---- report (stdout) -------------------------------------------------
    title_guardrails = ",".join(guardrails) if guardrails else "BASELINE"
    title = f"Eval [{exp_name}]: {title_guardrails} ({mode}, x{args.replicates})"
    print_report(results, title=title)

    if mode == "baseline":
        print("[NOTE] Baseline mode: model called directly, no guardrails. Judge "
              "classified each response into REFUSAL / CONTROL_BLOCK / COMPLIANCE / "
              "ERROR. Compare CONTROL_BLOCK rate baseline vs guardrail-on to isolate "
              "the guardrail's marginal contribution.")

    # ---- write per-experiment artifacts ----------------------------------
    config_payload = {
        "experiment_name": exp_name,
        "mode": mode,
        "guardrails": guardrails,
        "provider": args.provider,
        "base_url": args.base_url,
        "model": args.model,
        "tier": args.tier if args.datasets is None else None,
        "corpus_path": str(corpus_path) if corpus_path else None,
        "datasets": args.datasets,
        "judge_base_url": args.judge_base_url,
        "judge_model": args.judge_model,
        "judge_concurrency": args.judge_concurrency,
        "replicates": args.replicates,
        "concurrency": args.concurrency,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    metrics_payload = {
        "overall": compute_metrics(results),
        "by_source": compute_metrics_by_source(results),
        "by_category": compute_metrics_by_category(results),
        "latency": latency_stats(results),
        "stability": compute_replicate_stability(results),
    }
    results_payload = {"results": [r.to_dict() for r in results]}

    (exp_dir / "config.json").write_text(json.dumps(config_payload, indent=2))
    (exp_dir / "metrics.json").write_text(json.dumps(metrics_payload, indent=2))
    (exp_dir / "results.json").write_text(json.dumps(results_payload, indent=2))

    with (exp_dir / "transcript.jsonl").open("w") as f:
        for r in results:
            line = {
                "id": r.case.id,
                "label": r.case.label,
                "source": r.case.source,
                "replicate_idx": r.replicate_idx,
                "mode": r.mode,
                "outcome": r.outcome,
                "judge_reasoning": r.judge_reasoning,
                "judge_error": r.judge_error,
                "status_code": r.status_code,
                "block_reason": r.block_reason,
                "text_response": r.text_response,
                "raw_response": r.raw_response,
                "error": r.error,
                "latency_ms": round(r.latency_ms, 2),
                "judge_latency_ms": round(r.judge_latency_ms, 2),
            }
            f.write(json.dumps(line, default=str) + "\n")

    print(f"\nArtifacts written:")
    print(f"  config:     {exp_dir}/config.json")
    print(f"  metrics:    {exp_dir}/metrics.json")
    print(f"  results:    {exp_dir}/results.json")
    print(f"  transcript: {exp_dir}/transcript.jsonl  (one line per test)")
    return 0


def main():
    sys.exit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
