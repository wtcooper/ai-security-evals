#!/usr/bin/env python3
"""Small shared helpers every measurement skill uses. Stdlib only, so the vendored copy
runs in any Python.

  depth      smoke / standard / full, the same three names in every skill
  plan       print what a run will cost before it starts
  context    the deployment context a result applies to (surface, harness, safeguards...)
  samples    append rows to the shared samples.jsonl contract
  intervals  95% Wilson interval for a rate
  validity   flags that say whether a measurement can be trusted. They are NOT acceptance
             thresholds: a flag never hides the number and never says a result is good or bad.
  secrets    strip provider credentials from an environment
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Samples per benchmark. `smoke` proves the wiring and nothing else: near a 0.9 rate the 95%
# interval is about +/-12 points at n=25 and +/-6 at n=100.
DEPTHS: dict[str, int | None] = {"smoke": 25, "standard": 100, "full": None}

CONTEXT_KEYS = ("surface", "harness", "harness_version", "system_prompt", "tools",
                "safeguards", "data_sensitivity", "autonomy", "notes")


def resolve_depth(spec: str) -> int | None:
    """`smoke`, `standard`, `full`, or a positive integer. None means the whole dataset."""
    if spec in DEPTHS:
        return DEPTHS[spec]
    try:
        n = int(spec)
    except ValueError:
        raise ValueError(f"depth must be one of {sorted(DEPTHS)} or a positive integer") from None
    if n < 1:
        raise ValueError("depth must be a positive integer")
    return n


def print_plan(rows: list[dict], arms: int = 1, file=None) -> dict:
    """rows: [{name, samples, calls, note?}]. Prints and returns per-arm totals."""
    file = file or sys.stderr
    total = {"samples": sum(r["samples"] for r in rows), "calls": sum(r["calls"] for r in rows)}
    print(f"plan: {len(rows)} benchmark(s) x {arms} arm(s); per arm {total['samples']} tests / "
          f"~{total['calls']} model calls", file=file)
    for r in rows:
        print(f"  {r['name']:<40} n={r['samples']:<6} calls~{r['calls']:<7}{r.get('note', '')}",
              file=file)
    return total


def wilson_ci(rate: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    denom = 1 + z * z / n
    centre = (rate + z * z / (2 * n)) / denom
    half = z * math.sqrt(rate * (1 - rate) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant counts of a paired comparison."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def load_context(path: str | None = None) -> dict:
    """The `context` object of a review profile (review.json), or {} when there is none.
    Looks at the argument, then $REVIEW_FILE, then ./review.json."""
    for candidate in (path, os.environ.get("REVIEW_FILE"), "review.json"):
        if candidate and Path(candidate).is_file():
            data = json.loads(Path(candidate).read_text())
            ctx = data.get("context", {}) if isinstance(data, dict) else {}
            return {k: ctx[k] for k in CONTEXT_KEYS if ctx.get(k) is not None}
    return {}


def append_samples(path: str | Path, rows: list[dict]) -> None:
    """Append rows to samples.jsonl. Every row needs run, arm, target and sample so that
    denominators include samples with nothing to report."""
    for row in rows:
        missing = [k for k in ("arm", "target", "sample") if k not in row]
        if missing:
            raise ValueError(f"samples row missing {missing}: {row}")
    with open(path, "a") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def validity_flag(name: str, observed: float | None, limit: float, direction: str,
                  meaning: str) -> dict | None:
    """A flag when `observed` is beyond a configurable `limit` ("above" or "below").
    Reported next to the number, which is always shown."""
    if observed is None:
        return None
    tripped = observed > limit if direction == "above" else observed < limit
    return {"flag": name, "observed": observed, "limit": limit, "meaning": meaning} if tripped \
        else None


SCRUB_PREFIXES = ("OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "AZURE_", "AWS_")
SCRUB_SUFFIXES = ("_API_KEY", "_TOKEN", "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")
SCRUB_EXACT = ("MISTRAL_API_KEY", "COHERE_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY")


def scrub_provider_credentials(env: dict) -> dict:
    """Drop provider credentials so an unrouted judge fails instead of billing a provider.
    Everything else is kept (including HF_TOKEN, which gated datasets need)."""
    return {k: v for k, v in env.items()
            if k not in SCRUB_EXACT
            and not (k.startswith(SCRUB_PREFIXES) and k.endswith(SCRUB_SUFFIXES))}
