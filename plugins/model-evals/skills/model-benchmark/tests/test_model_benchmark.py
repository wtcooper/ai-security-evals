"""model-benchmark's own command line. The suite, runner and report it drives are tested
with the shared library; these run without inspect_ai."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_suite  # noqa: E402


def test_aliases_route_through_the_gateway_and_provider_strings_pass_through():
    assert run_suite.model_string("gemma4") == "openai-api/modelbench/gemma4"
    assert run_suite.model_string("anthropic/some-model") == "anthropic/some-model"


def test_plan_prints_cost_and_runs_nothing(capsys):
    assert run_suite.main(["--checks", "nojudge", "--depth", "smoke", "--plan"]) == 0
    err = capsys.readouterr().err
    assert "4 benchmark(s) x 1 arm(s)" in err and "cyse4_mitre_frr" in err


def test_depth_names_are_the_shared_three():
    for name in ("smoke", "standard", "full", "12"):
        assert run_suite.main(["--depth", name, "--plan"]) == 0
    with pytest.raises(ValueError):
        run_suite.main(["--depth", "quick", "--plan"])


def test_gateway_alias_needs_a_gateway_url(monkeypatch):
    monkeypatch.delenv("MODEL_BENCH_BASE_URL", raising=False)
    with pytest.raises(SystemExit):
        run_suite.main(["--models", "gemma4", "--checks", "nojudge", "--depth", "smoke"])
