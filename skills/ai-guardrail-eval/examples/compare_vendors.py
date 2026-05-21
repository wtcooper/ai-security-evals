"""
compare_vendors.py - Run the standard tier against multiple guardrails and
print a side-by-side comparison including marginal attribution.

Highlights the new outcome taxonomy: ASR + control_block_rate is the
delta-vs-baseline story.
"""

import asyncio
import os

from guardrail_eval import (
    GuardrailTester, LLMJudge, make_provider,
    load_static_suite, compute_metrics,
)


VENDORS = [
    ("none",                     "baseline"),  # special-case: no guardrails
    ("panw-prisma-airs-pre",     "input"),
    ("bedrock-pre",              "input"),
    ("azure-content-safety-pre", "input"),
]


async def main():
    cases = load_static_suite(tier="standard")
    print(f"Loaded {len(cases)} cases\n")

    base_url = os.environ["LITELLM_BASE_URL"]
    api_key = os.environ["LITELLM_API_KEY"]

    provider = make_provider("litellm", base_url=base_url, api_key=api_key, concurrency=20)
    judge = LLMJudge(
        base_url=os.environ.get("JUDGE_BASE_URL", base_url),
        api_key=os.environ.get("JUDGE_API_KEY", api_key),
        model=os.environ.get("JUDGE_MODEL", "gpt-4o-mini"),
        concurrency=10,
    )

    all_metrics = {}
    async with provider, judge:
        tester = GuardrailTester(
            provider=provider, judge=judge,
            model="gpt-3.5-turbo", concurrency=20,
        )
        for name, mode in VENDORS:
            print(f"Running {name} ({mode})...")
            guards = None if name == "none" else [name]
            results = await tester.run_batch(
                cases, guardrails=guards, mode=mode, replicates=3,
            )
            all_metrics[name] = compute_metrics(results)

    baseline = all_metrics["none"]
    print(f"\n{'vendor':<30} {'ASR':>7} {'FPR':>7} {'ΔASR':>7} {'CB_h':>7} {'ΔCB_h':>7}")
    for name, m in all_metrics.items():
        d_asr = m['asr'] - baseline['asr']
        d_cbh = m['control_block_rate_harmful'] - baseline['control_block_rate_harmful']
        print(f"  {name:<28} {m['asr']:>7.3f} {m['fpr']:>7.3f} "
              f"{d_asr:>+7.3f} {m['control_block_rate_harmful']:>7.3f} {d_cbh:>+7.3f}")


if __name__ == "__main__":
    asyncio.run(main())
