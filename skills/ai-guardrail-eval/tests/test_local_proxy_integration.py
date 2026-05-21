"""
Integration tests against the bundled local LiteLLM proxy.

These tests are SKIPPED when the proxy isn't reachable at http://localhost:4000.
They are not part of the default unit-test signal — they're the verification
matrix that proves the harness wires up end-to-end with the mock target
models, mock judge, and mock guardrail in local/litellm_config.yaml.

To run them:
    bash local/start_proxy.sh > /tmp/litellm_proxy.log 2>&1 &
    # wait ~5s for `curl http://localhost:4000/health/readiness` to return 200
    uv run pytest skills/ai-guardrail-eval/tests/test_local_proxy_integration.py -v

What's covered (one test per outcome path):
    * baseline + mock-target-refusal       -> dominant REFUSAL
    * baseline + mock-target-compliant     -> dominant COMPLIANCE
    * baseline + mock-target-policy-block  -> dominant CONTROL_BLOCK
    * input + mock-guardrail               -> non-zero CONTROL_BLOCK on harmful

If any of these fails after a local change, the harness wiring is broken
(not the judge's calibration or the corpus's content).
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from guardrail_eval.corpus import load_static_suite
from guardrail_eval.judge import (
    COMPLIANCE,
    CONTROL_BLOCK,
    LLMJudge,
    REFUSAL,
)
from guardrail_eval.metrics import compute_outcome_distribution
from guardrail_eval.providers import make_provider
from guardrail_eval.runner import GuardrailTester


PROXY_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
PROXY_KEY = os.environ.get("LITELLM_API_KEY", "sk-mock")
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "mock-judge")


def _proxy_is_up() -> bool:
    try:
        resp = httpx.get(f"{PROXY_URL}/health/readiness", timeout=2.0)
        return resp.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


pytestmark = pytest.mark.skipif(
    not _proxy_is_up(),
    reason=(
        f"Local LiteLLM proxy not reachable at {PROXY_URL}/health/readiness. "
        "Start it with: bash local/start_proxy.sh"
    ),
)


async def _run_matrix_row(
    model: str,
    guardrails: list[str] | None,
    mode: str,
    cases_limit: int = 20,
):
    """
    Run a subset of the smoke tier against the local proxy and return the
    per-label outcome distribution.

    We cap to `cases_limit` so the integration tests stay fast (the smoke
    tier is 100 cases; we only need enough to see the dominant outcome).
    """
    all_cases = load_static_suite(tier="smoke")
    # Keep label balance: take the first N/2 harmful and N/2 benign.
    harmful = [c for c in all_cases if c.label == "harmful"][: cases_limit // 2]
    benign = [c for c in all_cases if c.label == "benign"][: cases_limit // 2]
    cases = harmful + benign

    provider = make_provider(
        "litellm",
        base_url=PROXY_URL,
        api_key=PROXY_KEY,
        concurrency=5,
    )
    judge = LLMJudge(
        base_url=PROXY_URL,
        api_key=PROXY_KEY,
        model=JUDGE_MODEL,
        concurrency=5,
    )
    async with provider, judge:
        tester = GuardrailTester(
            provider=provider, judge=judge, model=model, concurrency=5,
        )
        results = await tester.run_batch(
            cases=cases,
            guardrails=guardrails,
            mode=mode,
            replicates=1,
            show_progress=False,
        )
    return results, compute_outcome_distribution(results)


def test_baseline_refusal_target_dominates_refusal():
    results, dist = asyncio.run(_run_matrix_row(
        model="mock-target-refusal", guardrails=None, mode="baseline",
    ))
    total = len(results)
    refusal_n = dist["harmful"][REFUSAL] + dist["benign"][REFUSAL]
    assert refusal_n == total, (
        f"expected all {total} cases to be REFUSAL on mock-target-refusal; "
        f"got distribution: {dist}"
    )


def test_baseline_compliant_target_dominates_compliance():
    results, dist = asyncio.run(_run_matrix_row(
        model="mock-target-compliant", guardrails=None, mode="baseline",
    ))
    total = len(results)
    compliance_n = dist["harmful"][COMPLIANCE] + dist["benign"][COMPLIANCE]
    assert compliance_n == total, (
        f"expected all {total} cases to be COMPLIANCE on mock-target-compliant; "
        f"got distribution: {dist}"
    )


def test_baseline_policy_block_target_dominates_control_block():
    results, dist = asyncio.run(_run_matrix_row(
        model="mock-target-policy-block", guardrails=None, mode="baseline",
    ))
    total = len(results)
    cb_n = dist["harmful"][CONTROL_BLOCK] + dist["benign"][CONTROL_BLOCK]
    assert cb_n == total, (
        f"expected all {total} cases to be CONTROL_BLOCK on mock-target-policy-block; "
        f"got distribution: {dist}"
    )


def test_input_mode_with_mock_guardrail_produces_control_blocks():
    # Input mode + mock-guardrail: the guardrail blocks any prompt matching
    # its adversarial patterns (~30% of smoke harmful in our tuning) and lets
    # the rest through with the placeholder mock_response. We assert that at
    # least one harmful prompt hit CONTROL_BLOCK — proves the guardrail path
    # is wired up. We don't assert exact counts because the pattern list can
    # be tuned without breaking the wiring contract.
    results, dist = asyncio.run(_run_matrix_row(
        model="mock-target-compliant",
        guardrails=["mock-guardrail"],
        mode="input",
    ))
    cb_harmful = dist["harmful"][CONTROL_BLOCK]
    assert cb_harmful > 0, (
        "expected mock-guardrail to block at least one harmful prompt in "
        f"input mode; got distribution: {dist}"
    )
