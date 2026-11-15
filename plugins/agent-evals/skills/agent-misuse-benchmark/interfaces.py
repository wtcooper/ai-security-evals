"""The two pieces a team supplies to make this benchmark real, and the mock versions that
let the rest of the pipeline run without them.

  Harness  runs one task with one agent harness and model, inside a sandbox, and returns
           what happened.
  Scorer   decides the outcome of that run from the evidence.

Neither real implementation ships. `get_harness("inspect-swe")` and `get_scorer("custom")`
raise NotImplementedError and point at references/build-guide.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

# What a scorer may return. `unscored` means the scorer could not tell; `error` means the run
# itself failed. Neither is ever counted as the agent declining or complying.
RESTRICTED_OUTCOMES = ("declined", "carried_out", "partial")
PERMITTED_OUTCOMES = ("completed", "declined", "failed")
NO_VERDICT = ("unscored", "error")
BUILD_GUIDE = "references/build-guide.md"


class Harness:
    """Runs a task. Subclass this for a real agent harness."""

    name = "abstract"

    def preflight(self) -> dict:
        """Called once before any task. Must return {"egress_blocked": bool, ...}. A real
        harness verifies, by trying, that its sandbox cannot reach the network."""
        raise NotImplementedError

    def run(self, task: dict, arm: dict, workdir: Path) -> dict:
        """Run one task. Return a dict with at least:
             final_text   the agent's last message
             events       tool calls and other steps, in order (free-form dicts)
             workspace    path to the sandbox workspace as the agent left it
             error        None, or a string if the run itself failed
             tokens       {"input": n, "output": n} when known
             harness_version  the exact version that ran"""
        raise NotImplementedError


class Scorer:
    """Decides the outcome of one run. Subclass this, or supply a module with `score`."""

    def score(self, task: dict, run: dict) -> dict:
        """Return {"outcome": <one of the outcomes for task["kind"], or "unscored">,
                   "evidence": <one line saying what the verdict rests on>}."""
        raise NotImplementedError


# ---- mock implementations: for the smoke test and unit tests only -------------------------

def _draw(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class MockHarness(Harness):
    """Runs nothing. Draws a canned outcome per (arm, task) from the rates in the arm's
    `mock` block, so that different arms give different numbers and the statistics have
    something to work on. Says nothing about any agent."""

    name = "mock"

    def preflight(self) -> dict:
        return {"egress_blocked": True, "note": "mock harness: nothing is executed"}

    def run(self, task: dict, arm: dict, workdir: Path) -> dict:
        rates = arm.get("mock") or {}
        roll = _draw(arm["name"], task["id"])
        if task["kind"] == "restricted":
            outcome = "declined" if roll < rates.get("decline_restricted", 0.7) else "carried_out"
        else:
            p = rates.get("complete_permitted", 0.8)
            outcome = "completed" if roll < p else (
                "declined" if roll < p + (1 - p) / 2 else "failed")
        if _draw("unscored", arm["name"], task["id"]) < rates.get("unscored", 0.0):
            outcome = "unscored"
        return {"final_text": "(mock run)", "events": [], "workspace": str(workdir),
                "error": None, "tokens": {"input": 0, "output": 0},
                "harness_version": "mock-1", "mock_outcome": outcome}


class MockScorer(Scorer):
    def score(self, task: dict, run: dict) -> dict:
        return {"outcome": run["mock_outcome"], "evidence": "canned by the mock harness"}


class ModuleScorer(Scorer):
    """A scorer supplied as a Python file with a function `score(task, run) -> dict`."""

    def __init__(self, path: str):
        spec = importlib.util.spec_from_file_location("user_scorer", path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load scorer module {path}")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        if not callable(getattr(self.module, "score", None)):
            raise TypeError(f"{path} must define score(task, run)")

    def score(self, task: dict, run: dict) -> dict:
        return self.module.score(task, run)


def get_harness(name: str, module: str | None = None) -> Harness:
    if name == "mock":
        return MockHarness()
    if module:
        spec = importlib.util.spec_from_file_location("user_harness", module)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(f"cannot load harness module {module}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not callable(getattr(mod, "make_harness", None)):
            raise TypeError(f"{module} must define make_harness(name) -> Harness")
        return mod.make_harness(name)
    raise NotImplementedError(
        f"no harness named {name!r} ships with this scaffold. Write one (a module with "
        f"make_harness(name) returning a Harness) and pass it with --harness-module. "
        f"See {BUILD_GUIDE}, step 2.")


def get_scorer(name: str) -> Scorer:
    if name == "mock":
        return MockScorer()
    if name.endswith(".py"):
        return ModuleScorer(name)
    raise NotImplementedError(
        f"no scorer named {name!r} ships with this scaffold. Pass --scorer <your_scorer.py> "
        f"defining score(task, run). See {BUILD_GUIDE}, step 3.")


def check_outcome(task: dict, verdict: dict) -> str:
    """The verdict's outcome if it is legal for this task kind, else 'unscored'."""
    allowed = RESTRICTED_OUTCOMES if task["kind"] == "restricted" else PERMITTED_OUTCOMES
    outcome = (verdict or {}).get("outcome")
    return outcome if outcome in allowed or outcome in NO_VERDICT else "unscored"
