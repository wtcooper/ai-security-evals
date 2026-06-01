"""LiteLLM connector — param-based guardrails.

LiteLLM enables a guardrail per-request via a top-level `guardrails: [<name>]` in
the body (verified on LiteLLM >= 1.85). The model is passed as usual. Baseline
omits the guardrails key entirely.
"""

from __future__ import annotations

import copy

from .base import Arm, Connector


class LiteLLMConnector(Connector):
    id = "litellm"

    def inject(self, body: dict, arm: Arm) -> dict:
        out = copy.deepcopy(body)
        if arm.model:
            out["model"] = arm.model              # pin the model for this arm
        if arm.guardrails:
            out["guardrails"] = list(arm.guardrails)
        else:
            out.pop("guardrails", None)            # baseline: no guardrail param
        for k, v in arm.extra.items():
            out[k] = v
        return out
