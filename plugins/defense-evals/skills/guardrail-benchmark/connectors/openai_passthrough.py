"""OpenAI-passthrough connector — for gateways where the guardrail is selected by
an extra body field other than litellm's `guardrails`, or where only the model is
pinned. Maps the arm's guardrail names into a configurable body field (default
`guardrails`) and any `extra` params. Use this as the base for vendor connectors
(e.g. Netskope) that route by a different parameter or header convention.
"""

from __future__ import annotations

import copy
import os

from .base import Arm, Connector


class OpenAIPassthroughConnector(Connector):
    id = "openai"

    def inject(self, body: dict, arm: Arm) -> dict:
        field = os.environ.get("GUARDRAIL_PARAM_FIELD", "guardrails")
        out = copy.deepcopy(body)
        if arm.model:
            out["model"] = arm.model
        if arm.guardrails:
            out[field] = list(arm.guardrails)
        else:
            out.pop(field, None)
        for k, v in arm.extra.items():
            out[k] = v
        return out
