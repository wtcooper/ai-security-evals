"""
Tests for the startup probe that detects whether per-request mock_response
injection is honored by the user's LiteLLM gateway. Catches the silent-
broken-output-mode bug that was the original reason for this whole rework
(see commit `Route mock_response via metadata.harness_mock_response`).
"""
from __future__ import annotations

import pytest

from guardrail_eval.providers import Provider, ProviderResponse

# run_eval lives at the skill root; pythonpath set in pyproject pytest config
import run_eval


class _EchoProvider(Provider):
    """In-memory provider that echoes the mock_response back as the text
    response. Models a correctly-configured LiteLLM with MockResponseHandler."""

    def __init__(self):
        super().__init__(base_url="http://mock", api_key="sk-mock")

    async def _ensure_client(self):
        return None

    async def call(self, messages, mock_response, guardrails, model):
        return ProviderResponse(
            status_code=200, blocked=False,
            text_response=mock_response or "[no mock]",
            raw_body={},
        )

    async def aclose(self):
        pass


class _IgnoreProvider(Provider):
    """In-memory provider that ignores mock_response and returns canned
    text. Models a real LiteLLM upstream that the proxy strips
    mock_response from — the bug the probe is meant to catch."""

    def __init__(self):
        super().__init__(base_url="http://mock", api_key="sk-mock")

    async def _ensure_client(self):
        return None

    async def call(self, messages, mock_response, guardrails, model):
        return ProviderResponse(
            status_code=200, blocked=False,
            text_response="some canned model response that ignores mock_response",
            raw_body={},
        )

    async def aclose(self):
        pass


class _AuthFailureProvider(Provider):
    """In-memory provider that fails with 401 — models the real symptom we
    saw when probing openai-test-route (fake key against real upstream)."""

    def __init__(self):
        super().__init__(base_url="http://mock", api_key="sk-mock")

    async def _ensure_client(self):
        return None

    async def call(self, messages, mock_response, guardrails, model):
        return ProviderResponse(
            status_code=401, blocked=True,
            block_reason="Incorrect API key provided: sk-fake-...",
            raw_body={"error": {"message": "bad key", "code": "401"}},
        )

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_probe_passes_when_provider_echoes_mock_response():
    ok, detail = await run_eval.probe_mock_response_support(_EchoProvider(), "m")
    assert ok is True
    assert detail == "ok"


@pytest.mark.asyncio
async def test_probe_fails_when_provider_ignores_mock_response():
    """The original silent-broken case: real upstream LLM gets called,
    returns its own text, the probe string is nowhere in the response."""
    ok, detail = await run_eval.probe_mock_response_support(_IgnoreProvider(), "m")
    assert ok is False
    assert "did not contain the mock string" in detail


@pytest.mark.asyncio
async def test_probe_fails_when_provider_returns_auth_error():
    """What happened against openai-test-route — 401 from real upstream
    because the proxy forwarded the call when it should have short-circuited."""
    ok, detail = await run_eval.probe_mock_response_support(_AuthFailureProvider(), "m")
    assert ok is False
    assert "HTTP 401" in detail


@pytest.mark.asyncio
async def test_probe_uses_unique_string_per_call():
    """Each probe should send a unique mock string so a stale-cache layer
    can't accidentally pass a previous probe's value."""
    probe = _EchoProvider()

    class _Capturing(_EchoProvider):
        captured = []

        async def call(self, messages, mock_response, guardrails, model):
            self.captured.append(mock_response)
            return await super().call(messages, mock_response, guardrails, model)

    p = _Capturing()
    await run_eval.probe_mock_response_support(p, "m")
    await run_eval.probe_mock_response_support(p, "m")
    assert len(p.captured) == 2
    assert p.captured[0] != p.captured[1]
    for s in p.captured:
        assert s.startswith("HARNESS-MOCK-PROBE-")
