"""
providers.py - Pluggable transport layer for guardrail evaluation.

A Provider knows how to call ONE gateway / chat endpoint and translate its
response into a uniform ProviderResponse. Providers are the only thing that
needs to know about vendor-specific request/response schemas; the rest of the
harness (runner, metrics, corpus) is provider-agnostic.

This version ships LiteLLMProvider as the only fully implemented provider.
OpenAICompatibleProvider and RESTProvider are scaffolded extension points
that raise NotImplementedError on use - they reserve the registry slot for
future versions without leaking partial behavior into the current pipeline.

To add a new provider, subclass Provider, implement `call`, and register it
in PROVIDERS at the bottom of this file. The runner stays unchanged.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class ProviderResponse:
    """
    What a provider returns to the runner. The runner doesn't care which
    vendor produced the response - only these fields matter.
    """
    status_code: int                          # HTTP status from the gateway
    blocked: bool                             # provider says this was blocked
    block_reason: Optional[str] = None        # gateway / guardrail reason text
    text_response: Optional[str] = None       # the LLM's actual reply (baseline mode)
    raw_body: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None               # transport-level errors


class Provider(ABC):
    """
    Base class for gateway providers. Subclasses must implement `call`.

    Lifecycle: providers own their httpx.AsyncClient. Use `async with provider`
    or call `await provider.aclose()` when done.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout_s: float = 30.0,
        concurrency: int = 10,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._max_keepalive = concurrency
        self._max_connections = concurrency * 2
        self._extra_headers = extra_headers or {}
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return type(self).__name__

    async def __aenter__(self) -> "Provider":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            limits = httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive,
            )
            headers = {"Content-Type": "application/json", **self._extra_headers}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                limits=limits,
                headers=headers,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def call(
        self,
        messages: List[Dict[str, str]],
        mock_response: Optional[str],
        guardrails: Optional[List[str]],
        model: str,
    ) -> ProviderResponse:
        """
        Send one chat request.

        mock_response:
            If non-None and the provider supports it, skip the LLM and use this
            as the assistant reply (LiteLLM-specific feature). Other providers
            should ignore it and make a real model call.
        guardrails:
            List of guardrail names to apply on this request. None means no
            guardrails (baseline). Providers without per-request guardrail
            control should ignore this.
        """


def _extract_text(body: Dict[str, Any]) -> Optional[str]:
    """Pull the assistant message text out of an OpenAI-shaped response."""
    try:
        choices = body.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        return msg.get("content")
    except (AttributeError, IndexError, TypeError):
        return None


def _extract_error_message(body: Dict[str, Any]) -> Optional[str]:
    """Pull a human-readable error message from a non-2xx response body."""
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("message") or err.get("code") or json.dumps(err)[:200]
    if isinstance(err, str):
        return err
    return None


class LiteLLMProvider(Provider):
    """
    LiteLLM proxy provider with native guardrail and mock_response support.

    Request shape:
        POST {base_url}/v1/chat/completions
        {
          "model": "...",
          "messages": [...],
          "mock_response": "..." (optional - skips LLM),
          "guardrails": ["name1", "name2"] (optional)
        }

    Block detection: HTTP 4xx with an error.message describing the trigger.
    The judge classifies the body to distinguish CONTROL_BLOCK from ERROR.
    """

    async def call(
        self,
        messages: List[Dict[str, str]],
        mock_response: Optional[str],
        guardrails: Optional[List[str]],
        model: str,
    ) -> ProviderResponse:
        client = await self._ensure_client()
        payload: Dict[str, Any] = {"model": model, "messages": messages}
        if mock_response is not None:
            payload["mock_response"] = mock_response
        if guardrails:
            payload["guardrails"] = guardrails

        try:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
        except (httpx.TimeoutException, httpx.RequestError) as e:
            return ProviderResponse(
                status_code=0, blocked=False,
                error=f"{type(e).__name__}: {e}",
            )

        try:
            body = resp.json()
        except Exception:
            body = {"_raw_text": resp.text}

        blocked = resp.status_code >= 400
        return ProviderResponse(
            status_code=resp.status_code,
            blocked=blocked,
            block_reason=_extract_error_message(body) if blocked else None,
            text_response=_extract_text(body) if not blocked else None,
            raw_body=body if isinstance(body, dict) else {},
        )


class OpenAICompatibleProvider(Provider):
    """
    Scaffolded extension point for generic /v1/chat/completions endpoints
    (vLLM, TGI, Together, Groq, Anthropic via OAI-compat shim, etc.).

    Not implemented in this version. Use LiteLLM with the upstream provider
    configured in the proxy's model_list instead.
    """

    async def call(self, *_args, **_kwargs) -> ProviderResponse:
        raise NotImplementedError(
            "OpenAICompatibleProvider is a scaffolded extension point and is "
            "not implemented in this version. Configure your model in the "
            "local LiteLLM proxy (local/litellm_config.yaml) and use "
            "--provider litellm instead."
        )


class RESTProvider(Provider):
    """
    Scaffolded extension point for non-OpenAI gateways and custom chat
    endpoints (in-house apps, vendor APIs with bespoke schemas).

    Not implemented in this version. The previous iteration included a
    template/keyword-based block detector that was at odds with the project's
    judge-only classification rule - that code was removed deliberately. A
    future version will provide a clean implementation where block detection
    still flows through the judge.
    """

    async def call(self, *_args, **_kwargs) -> ProviderResponse:
        raise NotImplementedError(
            "RESTProvider is a scaffolded extension point and is not "
            "implemented in this version. For custom REST endpoints, write a "
            "Provider subclass that returns ProviderResponse without doing "
            "any keyword-based block detection (the judge handles that)."
        )


PROVIDERS = {
    "litellm": LiteLLMProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "rest": RESTProvider,
}


def make_provider(
    kind: str,
    base_url: str,
    api_key: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    timeout_s: float = 30.0,
    concurrency: int = 10,
) -> Provider:
    """
    Factory for the built-in providers.

    kind: "litellm" (the only fully implemented provider this version)
          | "openai_compatible" | "rest" (scaffolded; raise on call)
    config: unused in this version (kept for signature stability)
    """
    if kind not in PROVIDERS:
        raise ValueError(
            f"Unknown provider {kind!r}. Available: {list(PROVIDERS)}"
        )
    cls = PROVIDERS[kind]
    return cls(
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        concurrency=concurrency,
    )
