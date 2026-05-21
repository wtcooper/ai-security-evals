"""
Tests for the judge prompt machinery.

We don't test the judge model's classification accuracy here — that depends
on the real LLM. We test the harness's contract with the judge: how the
response envelope is serialized into the user message, how the judge's
output is parsed, and how failure modes degrade to ERROR (never to silent
misclassification).
"""
from __future__ import annotations

import json

import httpx
import pytest

from guardrail_eval.corpus import TestCase
from guardrail_eval.judge import (
    JUDGE_SYSTEM_PROMPT,
    JUDGE_USER_TEMPLATE,
    LLMJudge,
    REFUSAL,
    CONTROL_BLOCK,
    COMPLIANCE,
    ERROR,
    OUTCOMES,
)
from guardrail_eval.providers import ProviderResponse


def _case(prompt="hello") -> TestCase:
    return TestCase(
        id="t1", source="test", category="test", label="benign", prompt=prompt
    )


def _envelope_response(status=200, body=None, text=None, error=None) -> ProviderResponse:
    return ProviderResponse(
        status_code=status,
        blocked=status >= 400,
        text_response=text,
        raw_body=body or {},
        error=error,
    )


# ---------------------------------------------------------------------------
# Judge prompt regression checks (no network)
# ---------------------------------------------------------------------------

def test_judge_system_prompt_is_label_blind():
    """
    The judge MUST NOT see harmful/benign labels. The system prompt should
    explicitly tell the judge to ignore that question. If this regression
    fires, someone leaked the label into the prompt.
    """
    sp = JUDGE_SYSTEM_PROMPT.lower()
    assert "not your job" in sp or "not your concern" in sp or "do not consider whether" in sp
    # User template should not template a label field
    assert "label" not in JUDGE_USER_TEMPLATE.lower()
    assert "harmful" not in JUDGE_USER_TEMPLATE.lower()


def test_judge_prompt_enumerates_all_four_outcomes():
    sp = JUDGE_SYSTEM_PROMPT
    for outcome in OUTCOMES:
        assert outcome in sp, f"system prompt missing outcome {outcome!r}"


def test_format_blob_includes_status_body_and_text():
    judge = LLMJudge(base_url="http://x", api_key="k", model="m")
    resp = _envelope_response(
        status=400,
        body={"error": {"message": "policy violation", "code": "content_policy_violation"}},
    )
    blob = judge._format_blob(resp)
    parsed = json.loads(blob)
    assert parsed["http_status_code"] == 400
    assert parsed["response_body"]["error"]["code"] == "content_policy_violation"


def test_format_blob_truncates_long_text():
    judge = LLMJudge(base_url="http://x", api_key="k", model="m", max_response_chars=50)
    long_text = "x" * 500
    resp = _envelope_response(status=200, text=long_text)
    blob = judge._format_blob(resp)
    parsed = json.loads(blob)
    assert "[truncated]" in parsed["assistant_text"]
    assert len(parsed["assistant_text"]) < len(long_text)


# ---------------------------------------------------------------------------
# Judge output parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('{"outcome": "REFUSAL", "reasoning": "ok"}', REFUSAL),
    ('{"outcome":"CONTROL_BLOCK","reasoning":"x"}', CONTROL_BLOCK),
    ('{"outcome": "compliance", "reasoning": "lower-case"}', COMPLIANCE),
    ('  {"outcome": "ERROR", "reasoning": "y"}  ', ERROR),
    ('```json\n{"outcome": "REFUSAL", "reasoning": "fenced"}\n```', REFUSAL),
    ('```\n{"outcome": "COMPLIANCE", "reasoning": "fenced"}\n```', COMPLIANCE),
])
def test_parse_judge_response_happy_paths(raw, expected):
    judge = LLMJudge(base_url="http://x", api_key="k", model="m")
    out = judge._parse_judge_response(raw)
    assert out.outcome == expected
    assert out.judge_error is None


@pytest.mark.parametrize("raw", [
    "",
    "not json at all",
    '{"outcome": "MAYBE", "reasoning": "invalid outcome"}',
    '{"reasoning": "missing outcome"}',
])
def test_parse_judge_response_degrades_to_error(raw):
    judge = LLMJudge(base_url="http://x", api_key="k", model="m")
    out = judge._parse_judge_response(raw)
    assert out.outcome == ERROR
    assert out.judge_error is not None


# ---------------------------------------------------------------------------
# End-to-end: mocked judge endpoint
# ---------------------------------------------------------------------------

class _RecordingTransport(httpx.AsyncBaseTransport):
    """httpx mock transport that records the request and returns a canned response."""

    def __init__(self, response_text: str, status: int = 200):
        self.response_text = response_text
        self.status = status
        self.last_request_body: dict | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            self.last_request_body = json.loads(request.content)
        except json.JSONDecodeError:
            self.last_request_body = None
        body = {
            "choices": [{"message": {"role": "assistant", "content": self.response_text}}],
        }
        return httpx.Response(self.status, json=body)


@pytest.mark.asyncio
async def test_judge_round_trip_classifies_compliance():
    transport = _RecordingTransport(
        response_text='{"outcome": "COMPLIANCE", "reasoning": "substantive text"}'
    )
    judge = LLMJudge(base_url="http://judge.test", api_key="sk", model="judge-m")
    # Inject the mock transport by replacing client construction.
    judge._client = httpx.AsyncClient(transport=transport, base_url="http://judge.test")

    resp = _envelope_response(status=200, text="Sure, here is the answer.")
    outcome = await judge.judge(_case(), resp)
    await judge.aclose()

    assert outcome.outcome == COMPLIANCE
    assert outcome.reasoning == "substantive text"
    # Verify the judge sent the right shape: system + user message, JSON-format
    body = transport.last_request_body
    assert body["model"] == "judge-m"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"
    # The user message should contain the blob with status code 200
    assert '"http_status_code": 200' in body["messages"][1]["content"]


@pytest.mark.asyncio
async def test_judge_http_error_degrades_to_error_outcome():
    transport = _RecordingTransport(response_text="oops", status=500)
    judge = LLMJudge(base_url="http://judge.test", api_key="sk", model="judge-m")
    judge._client = httpx.AsyncClient(transport=transport, base_url="http://judge.test")

    resp = _envelope_response(status=200, text="anything")
    outcome = await judge.judge(_case(), resp)
    await judge.aclose()

    assert outcome.outcome == ERROR
    assert outcome.judge_error is not None
