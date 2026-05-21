"""
Tests for the streaming transcript behavior in GuardrailTester.run_batch().

The earlier implementation held all TestResult objects in memory and wrote
transcript.jsonl after the run completed. This left every comprehensive run
one Ctrl-C away from losing 1000+ judged cases. The runner now opens the
transcript file at run start and each worker writes+flushes its line on
completion, under an asyncio.Lock. These tests pin that contract.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Optional

import pytest

from guardrail_eval.corpus import TestCase
from guardrail_eval.judge import COMPLIANCE, Judge, JudgeOutcome
from guardrail_eval.providers import Provider, ProviderResponse
from guardrail_eval.runner import GuardrailTester


class _FastMockProvider(Provider):
    """In-memory provider — returns immediately, no httpx, no real network."""

    def __init__(self) -> None:
        super().__init__(base_url="http://mock", api_key="sk-mock")

    async def _ensure_client(self):
        return None  # no real client needed

    async def call(self, messages, mock_response, guardrails, model):
        return ProviderResponse(
            status_code=200,
            blocked=False,
            text_response="canned compliance response",
            raw_body={"choices": [{"message": {"content": "canned compliance response"}}]},
        )

    async def aclose(self):
        pass


class _FastMockJudge(Judge):
    """In-memory judge that always says COMPLIANCE."""

    async def judge(self, case, response) -> JudgeOutcome:
        return JudgeOutcome(outcome=COMPLIANCE, reasoning="mock judge: fixture")


def _make_cases(n: int, label: str = "harmful") -> List[TestCase]:
    return [
        TestCase(
            id=f"stream-{label}-{i:03d}",
            source="testsrc", category="testcat", label=label,
            prompt=f"test prompt {i}",
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_streaming_writes_one_line_per_result(tmp_path: Path):
    """Every result gets exactly one valid JSONL line on disk by run end."""
    transcript = tmp_path / "transcript.jsonl"
    provider = _FastMockProvider()
    judge = _FastMockJudge()
    tester = GuardrailTester(provider=provider, judge=judge, model="m", concurrency=4)

    cases = _make_cases(20)
    results = await tester.run_batch(
        cases=cases, guardrails=None, mode="baseline",
        replicates=1, show_progress=False,
        transcript_path=transcript,
    )

    assert transcript.exists(), "streaming transcript file was not created"
    lines = transcript.read_text().splitlines()
    assert len(lines) == len(results) == 20

    # Every line is valid JSON with the audit-trail fields populated.
    for line in lines:
        rec = json.loads(line)
        assert "id" in rec
        assert "outcome" in rec
        assert "request_messages" in rec
        assert rec["outcome"] == COMPLIANCE

    # All cases accounted for (set equality, since worker order isn't deterministic).
    transcript_ids = {json.loads(L)["id"] for L in lines}
    expected_ids = {c.id for c in cases}
    assert transcript_ids == expected_ids


@pytest.mark.asyncio
async def test_streaming_persists_results_before_run_completes(tmp_path: Path):
    """
    Mid-run durability: while the run is in flight, lines that have
    completed should already be on disk. We use a provider that sleeps so we
    can peek at the file before run_batch returns.
    """
    transcript = tmp_path / "transcript.jsonl"

    class _SlowProvider(_FastMockProvider):
        async def call(self, messages, mock_response, guardrails, model):
            await asyncio.sleep(0.05)  # 50ms per case
            return await super().call(messages, mock_response, guardrails, model)

    provider = _SlowProvider()
    judge = _FastMockJudge()
    tester = GuardrailTester(provider=provider, judge=judge, model="m", concurrency=2)

    cases = _make_cases(10)
    run_task = asyncio.create_task(
        tester.run_batch(
            cases=cases, guardrails=None, mode="baseline",
            replicates=1, show_progress=False,
            transcript_path=transcript,
        )
    )

    # Peek partway through: wait long enough for ~2-4 cases to finish
    # (10 cases / concurrency=2 / 50ms = ~250ms wall; peek at 150ms).
    await asyncio.sleep(0.15)
    assert transcript.exists(), "transcript file should exist mid-run"
    partial_lines = transcript.read_text().splitlines()
    assert 0 < len(partial_lines) < len(cases), (
        f"expected some-but-not-all lines mid-run; got {len(partial_lines)} of {len(cases)}"
    )

    # Now wait for the run to finish
    results = await run_task
    final_lines = transcript.read_text().splitlines()
    assert len(final_lines) == len(results) == len(cases)


@pytest.mark.asyncio
async def test_transcript_path_none_skips_streaming(tmp_path: Path):
    """
    Backwards-compatible default: callers that don't pass transcript_path
    get the old behavior (no streaming, no file). Run still works.
    """
    provider = _FastMockProvider()
    judge = _FastMockJudge()
    tester = GuardrailTester(provider=provider, judge=judge, model="m", concurrency=2)

    cases = _make_cases(5)
    results = await tester.run_batch(
        cases=cases, guardrails=None, mode="baseline",
        replicates=1, show_progress=False,
        # transcript_path NOT passed
    )
    assert len(results) == 5
    # No stray transcript file in cwd or tmp_path
    assert not (tmp_path / "transcript.jsonl").exists()


@pytest.mark.asyncio
async def test_streaming_creates_parent_dir(tmp_path: Path):
    """If transcript_path lands in a non-existent dir, runner creates it."""
    transcript = tmp_path / ".evals" / "experiments" / "new-exp" / "transcript.jsonl"
    assert not transcript.parent.exists(), "precondition: parent should not exist yet"

    provider = _FastMockProvider()
    judge = _FastMockJudge()
    tester = GuardrailTester(provider=provider, judge=judge, model="m", concurrency=2)

    results = await tester.run_batch(
        cases=_make_cases(3), guardrails=None, mode="baseline",
        replicates=1, show_progress=False, transcript_path=transcript,
    )
    assert transcript.exists()
    assert len(transcript.read_text().splitlines()) == len(results) == 3
