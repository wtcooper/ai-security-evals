"""model-bench: suite data, result extraction, void rules, summary and weights verdicts.

None of this imports inspect_ai, so it runs in the main venv alongside the other tests.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_suite  # noqa: E402
import suite  # noqa: E402
import report  # noqa: E402
import weights_scan  # noqa: E402


# --- suite ---------------------------------------------------------------------------

def test_profiles_reference_known_checks_and_ids_are_unique():
    assert len(suite.BY_ID) == len(suite.CHECKS)
    for ids in suite.PROFILES.values():
        assert all(i in suite.BY_ID for i in ids)
    assert not any(suite.BY_ID[i].needs_judge for i in suite.PROFILES["nojudge"])


def test_misuse_check_is_always_paired_with_its_over_refusal_check():
    assert {"cyse4_mitre", "cyse4_mitre_frr"} <= set(suite.PROFILES["core"])


def test_resolve_checks_rejects_unknown():
    assert [c.id for c in suite.resolve_checks("agentdojo, cyse4_instruct")] == [
        "agentdojo", "cyse4_instruct"]
    with pytest.raises(ValueError):
        suite.resolve_checks("agentdojo,nope")


def test_depth_is_capped_at_dataset_size():
    small = suite.BY_ID["atb_memory_poison"]
    assert suite.samples_for(small, suite.resolve_depth("good")) == 10
    assert suite.samples_for(small, suite.resolve_depth("full")) == 10
    assert suite.samples_for(suite.BY_ID["cyse4_mitre"], suite.resolve_depth("40")) == 40
    plan = suite.plan(suite.resolve_checks("cyse4_mitre,atb_memory_poison"), 100)
    assert plan["samples"] == 110 and plan["calls"] == 100 * 3 + 10 * 4


def test_wilson_interval_and_normalize():
    lo, hi = suite.wilson_ci(0.9, 100)
    assert 0.82 < lo < 0.83 and 0.94 < hi < 0.95
    assert suite.wilson_ci(0.0, 4)[0] == pytest.approx(0.0, abs=1e-9)
    assert suite.wilson_ci(1.0, 4)[1] == pytest.approx(1.0, abs=1e-9)
    assert suite.normalize(0.1, suite.LOWER) == 90.0
    assert suite.normalize(0.1, suite.HIGHER) == 10.0


# --- runner --------------------------------------------------------------------------

def test_provider_credentials_are_scrubbed_but_gateway_and_hf_survive():
    env = {"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "x", "AWS_SECRET_ACCESS_KEY": "x",
           "GROQ_API_KEY": "x", "MODEL_BENCH_API_KEY": "k", "HF_TOKEN": "h",
           "OPENAI_BASE_URL": "u", "PATH": "/bin"}
    assert run_suite.scrub_provider_credentials(env) == {
        "MODEL_BENCH_API_KEY": "k", "HF_TOKEN": "h", "OPENAI_BASE_URL": "u", "PATH": "/bin"}


def test_model_string_routes_aliases_through_the_gateway():
    assert run_suite.model_string("gemma4") == "openai-api/modelbench/gemma4"
    assert run_suite.model_string("anthropic/some-model") == "anthropic/some-model"


def test_percent_metrics_are_converted_to_rates():
    out = run_suite.extract(suite.BY_ID["cyse4_instruct"],
                            {"security_scorer.vulnerable_percentage": 50.0}, 100)
    assert out["value"] == 0.5 and out["normalized"] == 50.0
    assert out["ci95"][0] < 0.5 < out["ci95"][1]


def test_missing_or_nan_metric_is_no_value_never_zero():
    check = suite.BY_ID["strong_reject"]
    assert run_suite.extract(check, {}, 10)["value"] is None
    assert run_suite.extract(check, {check.metric_key: math.nan}, 10)["value"] is None


def test_companion_and_scorer_reported_unresolved_rate():
    out = run_suite.extract(suite.BY_ID["agentdojo"],
                            {"security.accuracy": 1.0, "utility.accuracy": 0.1}, 20)
    assert out["companion"] == {"utility.accuracy": 0.1}
    out = run_suite.extract(suite.BY_ID["cyse4_mitre"],
                            {"mitre_scorer.accuracy": 0.9, "mitre_scorer.else_count": 5.0}, 50)
    assert out["judge_unresolved_rate"] == 0.1


def test_unscored_rate_counts_nan_and_grader_failures():
    def sample(value, meta=None):
        return SimpleNamespace(scores={"s": SimpleNamespace(value=value, metadata=meta)})
    samples = [sample("C"), sample(math.nan),
               sample("I", {"grader_failure_mode": "judge_response_invalid"}),
               sample({"utility": "I", "security": "C"})]
    assert run_suite.unscored_rate(samples) == 0.5
    assert run_suite.unscored_rate([]) is None


def test_an_unusable_judge_voids_the_check_even_when_a_number_exists():
    ok = {"inspect_status": "success", "value": 0.9, "judge_unresolved_rate": 0.02}
    assert run_suite.status_for(ok, 0.05) == "ok"
    assert run_suite.status_for({**ok, "judge_unresolved_rate": 0.2}, 0.05) == "void_judge"
    assert run_suite.status_for({**ok, "value": None}, 0.05) == "no_score"
    assert run_suite.status_for({**ok, "inspect_status": "error"}, 0.05) == "error"


# --- summary -------------------------------------------------------------------------

def _row(model, check, value, n=100, status="ok", **extra):
    c = suite.BY_ID[check]
    return {"model": model, "check": check, "status": status, "value": value,
            "ci95": list(suite.wilson_ci(value, n)) if value is not None else None,
            "samples_completed": n, "samples_total": n, "direction": c.direction, **extra}


def test_summary_reports_only_differences_larger_than_the_noise():
    run = {"depth": "good", "seed": 1, "judge": "j", "rows": [
        _row("a", "cyse4_mitre_frr", 0.05), _row("b", "cyse4_mitre_frr", 0.60),
        _row("a", "cyse4_instruct", 0.30), _row("b", "cyse4_instruct", 0.33)]}
    text = report.render([run])
    assert "`cyse4_mitre_frr`: a vs b" in text
    assert "`cyse4_instruct`: a vs b" not in text


def test_summary_flags_void_low_utility_and_mixed_settings():
    rows = [_row("a", "agentdojo", 1.0, companion={"utility.accuracy": 0.05}),
            _row("a", "strong_reject", None, status="void_judge", judge_unresolved_rate=1.0)]
    text = report.render([{"depth": "good", "seed": 1, "judge": "j", "rows": rows},
                             {"depth": "quick", "seed": 1, "judge": "j", "rows": []}])
    assert "failing to act" in text
    assert "no usable verdict" in text and "**void_judge**" in text
    assert "Not comparable" in text


# --- weights -------------------------------------------------------------------------

def _file(path, status="safe", **scanners):
    return {"type": "file", "path": path, "size": 1,
            "securityFileStatus": {"status": status,
                                   **{k: {"status": v} for k, v in scanners.items()}}}


def test_weights_clean_requires_scans_done_and_every_weight_file_scanned():
    tree = [_file("model.safetensors", protectAiScan="safe", avScan="safe")]
    assert weights_scan.assess(tree, {"scansDone": True})["verdict"] == "clean"
    assert weights_scan.assess(tree, {})["verdict"] == "unscanned"
    assert weights_scan.assess(tree, {"scansDone": False})["verdict"] == "unscanned"
    unscanned = [_file("model.safetensors", status="unscanned", avScan="queued")]
    assert weights_scan.assess(unscanned, {"scansDone": True})["verdict"] == "unscanned"
    assert weights_scan.assess([], {"scansDone": True})["verdict"] == "unscanned"


def test_weights_any_scanner_or_summary_issue_is_unsafe():
    tree = [_file("pytorch_model.bin", protectAiScan="safe", pickleImportScan="unsafe")]
    result = weights_scan.assess(tree, {"scansDone": True})
    assert result["verdict"] == "unsafe" and result["unsafe_files"] == ["pytorch_model.bin"]
    assert result["pickle_only"] is True
    clean_tree = [_file("m.safetensors", avScan="safe")]
    flagged = weights_scan.assess(clean_tree, {"scansDone": True,
                                               "filesWithIssues": [{"path": "evil.pkl"}]})
    assert flagged["verdict"] == "unsafe" and "evil.pkl" in flagged["unsafe_files"]


def test_weights_coverage_counts_only_scanners_that_looked():
    tree = [_file("a.safetensors", avScan="safe", jFrogScan="unscanned"),
            _file("b.bin", avScan="safe"), _file("config.json", avScan="safe")]
    result = weights_scan.assess(tree, {"scansDone": True})
    assert result["weight_files"] == 2
    assert result["scanner_coverage"]["avScan"] == 2
    assert result["scanner_coverage"]["jFrogScan"] == 0
    assert result["pickle_only"] is False
