"""
runner.py - Orchestrates guardrail evaluation across cases and replicates.

The runner has three responsibilities:
  1. Build request payloads for each mode (input / output / baseline)
  2. Call the Provider (gateway-specific transport)
  3. Call the Judge (LLM-as-judge that classifies the outcome)

Every test result has an `outcome` in {REFUSAL, CONTROL_BLOCK, COMPLIANCE,
ERROR}. The metrics layer maps (outcome, label) to TP/FP/FN/TN. There is no
keyword-based classification anywhere in the pipeline; the judge is the only
adjudicator.

Three modes:
  input    - Pre-call guardrail test. Adversarial prompt -> messages,
             neutral placeholder -> mock_response. Provider may block at HTTP.
  output   - Post-call guardrail test. Benign prompt -> messages, synthetic
             harmful content -> mock_response. Post-call guardrail evaluates
             the mocked "model output".
  baseline - No guardrails, real LLM call. The judge classifies the model's
             actual response. Use this to measure foundation-model defenses
             and to anchor guardrail comparisons.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .corpus import TestCase
from .providers import Provider, ProviderResponse
from .judge import Judge, JudgeOutcome, ERROR


DEFAULT_MOCK_RESPONSE = (
    "Thanks for your message. I'm a placeholder response generated for "
    "guardrail evaluation. No model was called."
)
DEFAULT_BENIGN_PROMPT = "Hello, can you help me with a quick question?"


@dataclass
class TestResult:
    """
    Outcome of a single guardrail test.

    Captures BOTH sides of the wire for full audit:
    - request_messages + request_mock_response: exact payload sent to the
      gateway. For input/baseline these mirror case.messages or [user prompt];
      for output mode the messages are the benign placeholder and the
      adversarial content lives in mock_response. Recording what was
      actually sent (not just what's on the case) keeps the audit honest.
    - raw_response + text_response + status_code: what came back.
    - outcome + judge_reasoning: what the judge decided.
    """
    case: TestCase
    outcome: str                            # REFUSAL | CONTROL_BLOCK | COMPLIANCE | ERROR
    judge_reasoning: str
    status_code: int
    latency_ms: float
    judge_latency_ms: float = 0.0
    block_reason: Optional[str] = None
    text_response: Optional[str] = None
    raw_response: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    judge_error: Optional[str] = None
    replicate_idx: int = 0
    mode: str = "input"
    request_messages: List[Dict[str, str]] = field(default_factory=list)
    request_mock_response: Optional[str] = None

    def to_dict(self) -> dict:
        meta = self.case.metadata or {}
        return {
            "id": self.case.id,
            "source": self.case.source,
            "category": self.case.category,
            "label": self.case.label,
            "technique_family": meta.get("technique_family"),
            # ---- input side (what we sent over the wire) ----
            "prompt": self.case.prompt,
            "messages": self.case.messages,
            "request_messages": self.request_messages,
            "request_mock_response": self.request_mock_response,
            # ---- response side ----
            "status_code": self.status_code,
            "text_response": self.text_response,
            "raw_response": self.raw_response,
            "block_reason": self.block_reason,
            "error": self.error,
            # ---- judge verdict ----
            "outcome": self.outcome,
            "judge_reasoning": self.judge_reasoning,
            "judge_error": self.judge_error,
            # ---- run metadata ----
            "replicate_idx": self.replicate_idx,
            "mode": self.mode,
            "latency_ms": round(self.latency_ms, 2),
            "judge_latency_ms": round(self.judge_latency_ms, 2),
        }


class GuardrailTester:
    """
    Runs cases through a Provider, then passes each response to a Judge.

    The Judge is REQUIRED. There is no keyword fallback - the judge is the
    only source of outcome classification.
    """

    def __init__(
        self,
        provider: Provider,
        judge: Judge,
        model: str = "gpt-3.5-turbo",
        concurrency: int = 10,
    ):
        if provider is None:
            raise ValueError("provider is required")
        if judge is None:
            raise ValueError(
                "judge is required. Construct an LLMJudge with your gateway "
                "details, e.g.: LLMJudge(base_url=..., api_key=..., model='gpt-4o-mini')"
            )
        self.provider = provider
        self.judge = judge
        self.model = model
        self.concurrency = concurrency

    async def __aenter__(self) -> "GuardrailTester":
        await self.provider._ensure_client()
        return self

    async def __aexit__(self, *_exc) -> None:
        pass

    async def test_input(
        self,
        case: TestCase,
        guardrails: Optional[List[str]],
        mock_response: str = DEFAULT_MOCK_RESPONSE,
        replicate_idx: int = 0,
    ) -> TestResult:
        """Pre-call guardrail test. Multi-turn cases pass full message list."""
        messages = case.messages if case.messages else [{"role": "user", "content": case.prompt}]
        return await self._call(
            messages=messages, mock_response=mock_response, guardrails=guardrails,
            case=case, replicate_idx=replicate_idx, mode="input",
        )

    async def test_output(
        self,
        case: TestCase,
        guardrails: Optional[List[str]],
        benign_prompt: str = DEFAULT_BENIGN_PROMPT,
        replicate_idx: int = 0,
    ) -> TestResult:
        """Post-call guardrail test."""
        synthetic_output = getattr(case, "expected_output", None) or case.prompt
        messages = [{"role": "user", "content": benign_prompt}]
        return await self._call(
            messages=messages, mock_response=synthetic_output, guardrails=guardrails,
            case=case, replicate_idx=replicate_idx, mode="output",
        )

    async def test_baseline(
        self,
        case: TestCase,
        replicate_idx: int = 0,
    ) -> TestResult:
        """No guardrails, real LLM call. Multi-turn cases pass full message list."""
        messages = case.messages if case.messages else [{"role": "user", "content": case.prompt}]
        return await self._call(
            messages=messages, mock_response=None, guardrails=None,
            case=case, replicate_idx=replicate_idx, mode="baseline",
        )

    async def run_batch(
        self,
        cases: List[TestCase],
        guardrails: Optional[List[str]],
        mode: str = "input",
        replicates: int = 1,
        show_progress: bool = True,
    ) -> List[TestResult]:
        if mode == "input":
            async def test_fn(c, rep):
                return await self.test_input(c, guardrails, replicate_idx=rep)
        elif mode == "output":
            async def test_fn(c, rep):
                return await self.test_output(c, guardrails, replicate_idx=rep)
        elif mode == "baseline":
            async def test_fn(c, rep):
                return await self.test_baseline(c, replicate_idx=rep)
        else:
            raise ValueError(f"Unknown mode: {mode!r}. Use input, output, or baseline.")

        if replicates < 1:
            raise ValueError("replicates must be >= 1")

        await self.provider._ensure_client()

        queue: "asyncio.Queue[Tuple[TestCase, int]]" = asyncio.Queue()
        total = len(cases) * replicates
        for rep in range(replicates):
            for c in cases:
                queue.put_nowait((c, rep))

        results: List[TestResult] = []
        progress = _make_progress_bar(total, mode, replicates) if show_progress else None

        async def worker() -> None:
            while True:
                try:
                    case, rep = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    result = await test_fn(case, rep)
                except Exception as e:
                    result = TestResult(
                        case=case,
                        outcome=ERROR,
                        judge_reasoning=f"runner exception: {type(e).__name__}: {e}",
                        status_code=0, latency_ms=0.0,
                        error=f"{type(e).__name__}: {e}",
                        replicate_idx=rep, mode=mode,
                    )
                results.append(result)
                if progress is not None:
                    progress.update(1)
                queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        try:
            await asyncio.gather(*workers)
        finally:
            if progress is not None:
                progress.close()

        return results

    async def _call(
        self,
        messages: List[Dict[str, str]],
        mock_response: Optional[str],
        guardrails: Optional[List[str]],
        case: TestCase,
        replicate_idx: int,
        mode: str,
    ) -> TestResult:
        # 1. Provider call
        start = time.perf_counter()
        resp: ProviderResponse = await self.provider.call(
            messages=messages, mock_response=mock_response,
            guardrails=guardrails, model=self.model,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        # 2. Judge call - the only source of outcome classification
        judge_start = time.perf_counter()
        judgement: JudgeOutcome = await self.judge.judge(case, resp)
        judge_latency_ms = (time.perf_counter() - judge_start) * 1000.0

        return TestResult(
            case=case,
            outcome=judgement.outcome,
            judge_reasoning=judgement.reasoning,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            judge_latency_ms=judge_latency_ms,
            block_reason=resp.block_reason,
            text_response=resp.text_response,
            raw_response=resp.raw_body,
            error=resp.error,
            judge_error=judgement.judge_error,
            request_messages=messages,
            request_mock_response=mock_response,
            replicate_idx=replicate_idx,
            mode=mode,
        )


def _make_progress_bar(total: int, mode: str, replicates: int):
    try:
        from tqdm import tqdm
        desc = f"Testing ({mode}, {replicates}x)" if replicates > 1 else f"Testing ({mode})"
        return tqdm(total=total, desc=desc, unit="case")
    except ImportError:
        return None
