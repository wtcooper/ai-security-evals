"""Shared, vendor-agnostic response classifier (Python mirror of status_policy.js).

Used by the control-bench injection shim so it classifies a gateway response the
same way the app skills do — body-signal first, status as a hint — instead of a
hard-coded status set. So a guardrail that blocks with a non-400 code (e.g. LiteLLM's
403 content-filter, recognized by its body) is converted to a refusal with no config.

classify(status, json_body, text) -> dict(kind, reason, http_status), kind in:
  'answer' | 'block' | 'error' | 'ambiguous'   (see status_policy.js for the contract)
"""

from __future__ import annotations

import os
import re

_BLOCK_WORDS = {"block", "blocked", "deny", "denied", "unsafe", "malicious"}
_BLOCK_MSG = re.compile(
    r"\b(content blocked|blocked by|guardrail|content[_ ]?policy|policy violation|flagged (by|as)|moderation)\b",
    re.I,
)
_ERROR_MSG = re.compile(
    r"\b(rate.?limit|too many requests|quota|insufficient_quota|billing|unauthorized|"
    r"invalid api key|authentication|api key|timeout|timed out|temporarily unavailable|"
    r"service unavailable|overloaded|try again later|upstream)\b",
    re.I,
)
_INFRA_STATUS = {401, 407, 408, 429}


def block_statuses() -> set[int]:
    raw = os.environ.get("GUARDRAIL_BLOCK_STATUSES", "400")
    out = set()
    for s in raw.split(","):
        s = s.strip()
        try:
            out.add(int(s))
        except ValueError:
            pass
    return out


def _dig(obj, path):
    cur = obj
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _message_of(body, text):
    if isinstance(body, dict):
        err = body.get("error")
        m = None
        if isinstance(err, dict):
            m = err.get("message")
        elif isinstance(err, str):
            m = err
        m = m or body.get("message") or body.get("detail") or body.get("reason")
        if m:
            return m if isinstance(m, str) else str(m)
    return str(text) if text else ""


def body_signals_block(body) -> bool:
    if not isinstance(body, dict):
        return False
    field = os.environ.get("GUARDRAIL_BLOCK_FIELD")
    if field:
        want = (os.environ.get("GUARDRAIL_BLOCK_VALUE") or "true").lower()
        return str(_dig(body, field)).lower() == want
    for key in ("action", "outcome", "decision", "verdict", "result"):
        v = body.get(key)
        if isinstance(v, str) and v.lower() in _BLOCK_WORDS:
            return True
    if body.get("blocked") is True or body.get("flagged") is True or body.get("is_malicious") is True:
        return True
    if isinstance(body.get("guardrails"), dict) and body["guardrails"].get("flagged") is True:
        return True
    if (body.get("guardrail_name") or _dig(body, "error.guardrail_name")
            or _dig(body, "error.provider_specific_fields.guardrail_name")
            or _dig(body, "provider_specific_fields.guardrail_name")):
        return True
    return bool(_BLOCK_MSG.search(_message_of(body, "")))


def body_signals_error(status, body, text) -> bool:
    if isinstance(status, int) and (status >= 500 or status in _INFRA_STATUS):
        return True
    return bool(_ERROR_MSG.search(_message_of(body, text)))


def extract_reason(body, text) -> str:
    m = _message_of(body, text)
    if m:
        return m
    if isinstance(body, dict):
        r = body.get("category") or body.get("code")
        if r:
            return str(r)
    return ""


def classify(status, body, text="") -> dict:
    def out(kind, reason=""):
        return {"kind": kind, "reason": reason or "", "http_status": status if status is not None else None}

    if status is None or (200 <= status < 300):
        if body_signals_block(body):
            return out("block", extract_reason(body, text))
        return out("answer", "")
    if body_signals_block(body):
        return out("block", extract_reason(body, text))
    if status in block_statuses():
        return out("block", extract_reason(body, text) or f"HTTP {status}")
    if body_signals_error(status, body, text):
        return out("error", extract_reason(body, text) or f"HTTP {status}")
    return out("ambiguous", extract_reason(body, text) or f"HTTP {status}")
