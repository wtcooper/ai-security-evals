"""Gateway connector abstraction for control-bench A/B/C.

A control is toggled by PARAMETERS passed to a gateway — both a `model` name and a
`guardrail` name (there are no guardrail-baked model aliases). Standard OpenAI
clients inside benchmark frameworks won't send a `guardrails` param, so a connector
knows exactly one thing: how to express "use guardrail X" as a request parameter
for a given gateway. The injection shim (injection_shim.py) applies it to every
request so the framework stays unmodified.

An `Arm` is one A/B/C cell: baseline (no guardrail) or a named control.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Arm:
    name: str                         # e.g. "baseline", "prisma", "lakera"
    model: str                        # model name passed to the gateway
    guardrails: tuple[str, ...] = ()  # guardrail names; empty = baseline
    extra: dict = field(default_factory=dict)  # any extra body params

    @property
    def is_baseline(self) -> bool:
        return not self.guardrails


class Connector:
    """Base connector. `inject` maps an Arm onto an outbound request body."""

    id = "base"

    def inject(self, body: dict, arm: Arm) -> dict:
        raise NotImplementedError

    @staticmethod
    def from_id(connector_id: str) -> "Connector":
        from . import litellm, openai_passthrough
        registry = {
            "litellm": litellm.LiteLLMConnector(),
            "openai": openai_passthrough.OpenAIPassthroughConnector(),
        }
        if connector_id not in registry:
            raise ValueError(f"unknown connector {connector_id!r}; have {sorted(registry)}")
        return registry[connector_id]
