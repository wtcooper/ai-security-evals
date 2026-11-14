"""Realtime target adapters. One file per wire protocol; register it in ADAPTERS.

To add a vendor: write adapters/<name>.py with a class that has `name`, `describe()` and
`respond(TargetInput) -> TargetResult` (see base.py), then add it to ADAPTERS below. The
runner, the grading and the report do not change.
"""
from __future__ import annotations

from .base import TargetInput, TargetResult
from .openai_realtime import OpenAIRealtimeAdapter

ADAPTERS = {
    OpenAIRealtimeAdapter.name: OpenAIRealtimeAdapter,
}


def get(name: str):
    if name not in ADAPTERS:
        raise ValueError(f"unknown adapter {name!r}; known: {sorted(ADAPTERS)}")
    return ADAPTERS[name]


__all__ = ["ADAPTERS", "TargetInput", "TargetResult", "get"]
