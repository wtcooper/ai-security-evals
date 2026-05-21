"""
test_multiturn.py - Test multi-turn cases specifically.

Filters the comprehensive tier to cases with a populated `messages` field
(multi-turn). Requires rebuilding the corpus with HF_TOKEN set to include
the gated MHJ + AgentHarm datasets. Crescendo (public HF) is included
whenever `datasets` is installed.
"""

import asyncio
import os

from guardrail_eval import (
    GuardrailTester, LLMJudge, make_provider,
    load_static_suite, print_report,
)


async def main():
    all_cases = load_static_suite(tier="comprehensive")
    multi_turn = [c for c in all_cases if c.messages and len(c.messages) > 1]
    print(f"Multi-turn cases: {len(multi_turn)} / {len(all_cases)}")
    if not multi_turn:
        print("No multi-turn cases in corpus. Rebuild with:")
        print("  pip install datasets")
        print("  python scripts/build_corpus.py    # adds Crescendo")
        print("  HF_TOKEN=hf_xxx python scripts/build_corpus.py    # adds MHJ + AgentHarm")
        return

    base_url = os.environ["LITELLM_BASE_URL"]
    api_key = os.environ["LITELLM_API_KEY"]

    provider = make_provider("litellm", base_url=base_url, api_key=api_key, concurrency=10)
    judge = LLMJudge(
        base_url=os.environ.get("JUDGE_BASE_URL", base_url),
        api_key=os.environ.get("JUDGE_API_KEY", api_key),
        model=os.environ.get("JUDGE_MODEL", "gpt-4o-mini"),
        concurrency=10,
    )

    async with provider, judge:
        tester = GuardrailTester(provider=provider, judge=judge, concurrency=10)
        results = await tester.run_batch(
            multi_turn, guardrails=["my-input-guard"], mode="input",
        )
    print_report(results, title="Multi-turn - all available")


if __name__ == "__main__":
    asyncio.run(main())
