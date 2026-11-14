"""Shared Inspect suite, runner and report. Nothing here imports inspect_ai."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import inspect_report as report  # noqa: E402
import inspect_runner as runner  # noqa: E402
import inspect_suite as suite  # noqa: E402


# --- suite ---------------------------------------------------------------------------

def test_profiles_reference_known_checks_and_ids_are_unique():
    assert len(suite.BY_ID) == len(suite.CHECKS)
    for ids in suite.PROFILES.values():
        assert all(i in suite.BY_ID for i in ids)
    assert not any(suite.BY_ID[i].needs_judge for i in suite.PROFILES["nojudge"])


def test_misuse_check_is_always_paired_with_its_over_refusal_check():
    for profile in ("core", "guardrail"):
        assert {"cyse4_mitre", "cyse4_mitre_frr"} <= set(suite.PROFILES[profile])


def test_attack_success_metrics_named_accuracy_are_lower_is_better():
    # Read from the scorer source: these count successful attacks, whatever the metric is called.
    for cid in ("agentdojo", "cyse4_multilingual_prompt_injection",
                "cyse3_visual_prompt_injection"):
        assert suite.BY_ID[cid].direction == suite.LOWER
    for cid in ("atb_memory_poison", "cyse4_mitre"):
        assert suite.BY_ID[cid].direction == suite.HIGHER


def test_sample_good_rules():
    by = suite.BY_ID
    assert by["cyse4_mitre"].sample_good("C") is True
    assert by["cyse4_mitre"].sample_good("I") is False
    assert by["cyse4_multilingual_prompt_injection"].sample_good("C") is False
    assert by["cyse4_multilingual_prompt_injection"].sample_good(math.nan) is None
    assert by["agentdojo"].sample_good({"utility": "C", "security": "C"}) is False
    assert by["agentdojo"].sample_good({"utility": "I", "security": "I"}) is True
    assert by["atb_memory_poison"].sample_good({"utility": "I", "security": "C"}) is True
    assert by["strong_reject"].sample_good({"refusal": 1, "specificity": 3}) is True
    assert by["strong_reject"].sample_good({"refusal": 0}) is False
    assert by["strong_reject"].sample_good(math.nan) is None
    assert by["cyse4_instruct"].sample_good({"score": "I", "is_vulnerable": True}) is False


def test_resolve_checks_and_depth_cap():
    assert [c.id for c in suite.resolve_checks("agentdojo, cyse4_instruct")] == [
        "agentdojo", "cyse4_instruct"]
    with pytest.raises(ValueError):
        suite.resolve_checks("agentdojo,nope")
    small = suite.BY_ID["atb_memory_poison"]
    assert suite.samples_for(small, 100) == 10 and suite.samples_for(small, None) == 10
    rows = suite.plan_rows(suite.resolve_checks("cyse4_mitre,atb_memory_poison"), 100)
    assert [(r["samples"], r["calls"]) for r in rows] == [(100, 300), (10, 40)]
    assert suite.normalize(0.1, suite.LOWER) == 90.0


# --- runner --------------------------------------------------------------------------

def test_percent_metrics_are_converted_to_rates():
    out = runner.extract(suite.BY_ID["cyse4_instruct"],
                         {"security_scorer.vulnerable_percentage": 50.0}, 100)
    assert out["value"] == 0.5 and out["ci95"][0] < 0.5 < out["ci95"][1]


def test_missing_or_nan_metric_is_no_value_never_zero():
    check = suite.BY_ID["strong_reject"]
    assert runner.extract(check, {}, 10)["value"] is None
    assert runner.extract(check, {check.metric_key: math.nan}, 10)["value"] is None


def test_unscored_rate_counts_nan_and_grader_failures():
    def sample(value, meta=None):
        return SimpleNamespace(scores={"s": SimpleNamespace(value=value, metadata=meta)})
    samples = [sample("C"), sample(math.nan),
               sample("I", {"grader_failure_mode": "judge_response_invalid"}),
               sample({"utility": "I", "security": "C"})]
    assert runner.unscored_rate(samples) == 0.5
    assert runner.unscored_rate([]) is None


def _samples(values):
    return [SimpleNamespace(id=i, epoch=1, scores={"s": SimpleNamespace(value=v, metadata=None)})
            for i, v in enumerate(values)]


def test_per_sample_rows_must_reproduce_the_headline_metric():
    check = suite.BY_ID["agentdojo"]   # headline = share where the injection was executed
    rows = runner.sample_rows(check, "a", _samples(
        [{"security": "C"}] * 2 + [{"security": "I"}] * 8))
    assert sum(r["good"] for r in rows) == 8
    assert runner.reproduces_headline(check, 0.2, rows) is True
    # If upstream flipped the meaning, the same samples would no longer match the headline.
    assert runner.reproduces_headline(check, 0.8, rows) is False
    assert runner.reproduces_headline(check, None, rows) is None


def test_validity_flags_are_reported_and_never_replace_the_number():
    check = suite.BY_ID["agentdojo"]
    row = {"value": 0.0, "judge_unresolved_rate": 0.4, "paired_ok": False,
           "companion": {"utility.accuracy": 0.05}, "samples_completed": 8, "samples_total": 10}
    names = {f["flag"] for f in runner.flags_for(check, row, 0.05, 0.3)}
    assert names == {"judge_unresolved", "low_utility", "samples_do_not_reproduce_headline",
                     "partial"}
    assert row["value"] == 0.0
    clean = {"value": 0.1, "judge_unresolved_rate": 0.0, "paired_ok": True,
             "companion": {"utility.accuracy": 0.9}, "samples_completed": 10,
             "samples_total": 10}
    assert runner.flags_for(check, clean, 0.05, 0.3) == []


# --- report --------------------------------------------------------------------------

def _row(arm, check, value, n=100, status="ok", **extra):
    return {"arm": arm, "check": check, "status": status, "value": value, "flags": [],
            "ci95": [0.0, 1.0] if value is not None else None, "samples_completed": n,
            "samples_total": n, "paired_ok": True, **extra}


def _pairs(check, base, other):
    out = []
    for i, (a, b) in enumerate(zip(base, other)):
        out += [{"arm": "a", "target": check, "sample": str(i), "epoch": 1, "good": a},
                {"arm": "b", "target": check, "sample": str(i), "epoch": 1, "good": b}]
    return out


def test_paired_comparison_counts_discordant_samples():
    samples = _pairs("cyse4_mitre_frr", [True] * 4 + [False] * 6 + [None],
                     [True] * 4 + [True] * 6 + [True])
    result = report.paired(samples, "cyse4_mitre_frr", "a", "b")
    assert result["n"] == 10 and result["better"] == 6 and result["worse"] == 0
    assert result["delta"] == 0.6 and result["p"] == pytest.approx(0.0312, abs=1e-3)
    assert report.paired(samples, "cyse4_mitre_frr", "a", "missing") is None


def test_report_lists_flags_and_failures_before_results_and_withholds_bad_pairs():
    run = {"depth": "standard", "seed": 1, "judge": "j", "context": {"harness": "opencode"},
           "rows": [
               _row("a", "agentdojo", 0.0, flags=[{"flag": "low_utility", "observed": 0.05,
                                                   "limit": 0.3, "meaning": "rarely acts"}]),
               _row("b", "agentdojo", 0.2, paired_ok=False),
               _row("a", "strong_reject", None, status="no_score"),
               _row("b", "strong_reject", 0.3)],
           "samples": _pairs("agentdojo", [True] * 5, [False] * 5)}
    text = report.render([run])
    assert text.index("Read first") < text.index("## Results")
    assert "validity flag `low_utility`" in text and "**no_score**" in text
    assert "harness `opencode`" in text
    assert "0.00 [0.00–1.00] n=100 ⚑" in text          # the flagged number is still shown
    assert report.summarize([run])["comparisons"] == []  # b's samples do not reproduce
    mixed = report.render([run, {**run, "depth": "smoke"}])
    assert "Not comparable" in mixed
