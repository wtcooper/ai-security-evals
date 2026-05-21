"""
Tests for the --mode resolution in run_eval.py.

The rule: when --guardrail is set to a named guardrail, --mode is REQUIRED
and the CLI must hard-error rather than silently default to "input". Picking
the wrong mode silently measures the wrong side of the gateway (pre-call vs
post-call) and produces convincing but wrong metrics — a real bug we saw in
the wild before this guard was in place.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

# run_eval lives at the skill root; pythonpath set in pyproject pytest config
import run_eval


def _args(guardrail: str, mode=None):
    return SimpleNamespace(guardrail=guardrail, mode=mode)


def test_baseline_default_when_guardrail_none():
    """--guardrail none -> mode auto-defaults to baseline (the only valid pick)."""
    guards, mode = run_eval.resolve_guardrails_and_mode(_args("none"))
    assert guards is None
    assert mode == "baseline"


def test_explicit_baseline_with_guardrail_none_passes_through():
    guards, mode = run_eval.resolve_guardrails_and_mode(_args("none", "baseline"))
    assert guards is None
    assert mode == "baseline"


def test_named_guardrail_without_mode_hard_errors():
    """Bug fix: named guardrail + no --mode used to silently default to 'input'."""
    with pytest.raises(SystemExit) as exc_info:
        run_eval.resolve_guardrails_and_mode(_args("panw-prisma-airs-pre"))
    msg = str(exc_info.value)
    # Error message must guide the user to pick a mode explicitly
    assert "--mode is REQUIRED" in msg
    assert "input" in msg and "output" in msg


def test_named_guardrail_with_input_mode_works():
    guards, mode = run_eval.resolve_guardrails_and_mode(
        _args("panw-prisma-airs-pre", "input")
    )
    assert guards == ["panw-prisma-airs-pre"]
    assert mode == "input"


def test_named_guardrail_with_output_mode_works():
    guards, mode = run_eval.resolve_guardrails_and_mode(
        _args("panw-prisma-airs-post", "output")
    )
    assert guards == ["panw-prisma-airs-post"]
    assert mode == "output"


def test_multiple_guardrails_comma_separated():
    guards, mode = run_eval.resolve_guardrails_and_mode(
        _args("guard-a,guard-b,guard-c", "input")
    )
    assert guards == ["guard-a", "guard-b", "guard-c"]
    assert mode == "input"


def test_named_guardrail_with_baseline_mode_drops_guardrails(capsys):
    """--mode baseline + named guardrails => warn and drop the guardrails."""
    guards, mode = run_eval.resolve_guardrails_and_mode(
        _args("some-guard", "baseline")
    )
    assert guards is None
    assert mode == "baseline"
    err = capsys.readouterr().err
    assert "guardrails will be ignored" in err.lower()
