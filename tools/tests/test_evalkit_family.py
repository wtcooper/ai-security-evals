import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import evalkit  # noqa: E402


def test_holm_matches_hand_computation_and_keeps_order():
    assert evalkit.holm([0.01, 0.04, 0.03, None, 0.5]) == [0.04, 0.09, 0.09, None, 0.5]
    assert evalkit.holm([]) == []


def test_min_detectable_grows_with_the_family():
    assert evalkit.min_detectable(100) == 6            # 2 * 0.5**6 = 0.031 < 0.05
    assert evalkit.min_detectable(100, comparisons=20) == 10
    assert evalkit.min_detectable(5) is None
    assert "at least 6 cases" in evalkit.power_note(100)


def test_print_plan_shows_power_only_when_arms_are_compared(capsys):
    evalkit.print_plan([{"name": "x", "samples": 50, "calls": 50}], arms=1)
    assert "separated" not in capsys.readouterr().err
    tot = evalkit.print_plan([{"name": "x", "samples": 50, "calls": 50}], arms=3)
    assert "separated across 2 comparisons" in capsys.readouterr().err and tot["comparisons"] == 2


def test_repeat_consistency():
    rows = [{"arm": "a", "target": "t", "sample": s, "repeat": r, "good": g}
            for s, r, g in [("1", 0, True), ("1", 1, False), ("2", 0, True), ("2", 1, True),
                            ("3", 0, None)]]
    out = evalkit.repeat_consistency(rows)["a|t"]
    assert out["cases"] == 2 and out["flip_rate"] == 0.5 and out["repeat_rates"] == [1.0, 0.5]


def test_ceiling_flag_is_configurable():
    assert evalkit.ceiling_flag({"a": 0.97, "b": 0.99}, 0.95)["flag"] == "near_ceiling"
    assert evalkit.ceiling_flag({"a": 0.90, "b": 0.99}, 0.95) is None


def test_register_plan_records_amendments_and_timing(tmp_path):
    doc = evalkit.register_plan(tmp_path, {"arms": ["a", "b"], "depth": "standard"})
    assert doc["registered_before_results"] and doc["amendments"] == []
    assert evalkit.register_plan(tmp_path, {"arms": ["a", "b"], "depth": "standard"}) == doc
    (tmp_path / "samples.jsonl").write_text('{"arm":"a"}\n')
    doc = evalkit.register_plan(tmp_path, {"arms": ["a"], "depth": "standard"}, reason="b failed")
    assert doc["amendments"][0]["after_results"] is True
    devs = evalkit.plan_deviations(doc, {"arms": ["a"], "depth": "smoke"})
    assert any("`arms`" in d for d in devs) and any("`depth`" in d for d in devs)
    assert any("b failed" in d for d in devs)
    assert "## Analysis plan" in "\n".join(evalkit.plan_section(doc, {}))
    assert "No plan was registered" in "\n".join(evalkit.plan_section(None, {}))


def test_fingerprints_and_records(tmp_path):
    f = tmp_path / "c.json"
    f.write_text("{}")
    rec = evalkit.corpus_record(f, bundled=True)
    assert rec["visibility"] == "public" and len(rec["sha256"]) == 64
    assert evalkit.corpus_record(f, bundled=False)["visibility"] == "private"
    assert evalkit.criteria_record(f)["sha256"] == rec["sha256"]
    assert evalkit.judge_id("m", "2") == "m|rubric:2" and evalkit.judge_id(None) is None
