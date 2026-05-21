"""
test_output_guardrail.py - Exercise an output (post_call) guardrail.

Uses harmful prompts AS the synthetic mock_response (proxy for harmful
generations). The post_call guardrail then evaluates the mocked "model
output". No real LLM call is made.
"""

import asyncio
import os

from guardrail_eval import (
    GuardrailTester, LLMJudge, make_provider,
    load_static_suite, print_report,
)


async def main():
    cases = load_static_suite(tier="smoke")

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
            cases, guardrails=["my-output-guard"], mode="output",
        )
    print_report(results, title="Output guardrail - smoke tier")


if __name__ == "__main__":
    asyncio.run(main())
