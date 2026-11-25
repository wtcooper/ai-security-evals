"""Direct mode across guardrails: the plan is registered first, every guardrail is compared with
the baseline on the same cases, p-values are Holm-adjusted, and a saturated measure is flagged.
No promptfoo needed: the outputs are written in promptfoo's result shape."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import direct  # noqa: E402


def _output(outcomes: dict) -> dict:
    """{case id: (type, passed)} -> a promptfoo output document."""
    return {"results": {"results": [
        {"testCase": {"metadata": {"id": cid, "type": typ, "technique_family": "direct_harmful"
                                   if typ != "benign" else ""}},
         "vars": {"prompt": cid}, "success": ok, "failureReason": 0 if ok else 1}
        for cid, (typ, ok) in outcomes.items()]}}


def _exp(tmp_path, arms: dict) -> Path:
    exp = tmp_path / "exp"
    (exp / "results").mkdir(parents=True)
    for arm, outcomes in arms.items():
        (exp / "results" / f"{arm}.json").write_text(json.dumps(_output(outcomes)))
    return exp


def test_plan_registers_and_prints_power_and_seeded_commands(tmp_path, capsys):
    assert direct.main(["plan", str(tmp_path), "--arms", "a,b", "--depth", "standard",
                        "--seed", "7"]) == 0
    err = capsys.readouterr().err
    assert "two arms must differ" in err and "--filter-sample 150 --filter-sample-seed 7" in err
    plan = json.loads((tmp_path / "plan.json").read_text())["plan"]
    assert plan["baseline"] == "a" and plan["filter_sample"] == 150 and plan["judge"] is None
    assert plan["corpus"]["visibility"] == "public" and plan["corpus"]["sha256"]


def test_compare_pairs_cases_adjusts_p_and_flags_a_saturated_measure(tmp_path, capsys):
    attacks = {f"h{i}": "harmful_content" for i in range(12)}
    benign = {f"b{i}": "benign" for i in range(10)}
    base = {**{k: (t, i < 2) for i, (k, t) in enumerate(attacks.items())},
            **{k: (t, True) for k, t in benign.items()}}
    strong = {**{k: (t, True) for k, t in attacks.items()},
              **{k: (t, True) for k, t in benign.items()}}
    exp = _exp(tmp_path, {"base": base, "strong": strong})
    direct.main(["plan", str(exp), "--arms", "base,strong", "--depth", "full"])
    capsys.readouterr()
    assert direct.main(["compare", str(exp), "--json", str(exp / "summary.json")]) == 0
    md = capsys.readouterr().out
    s = json.loads((exp / "summary.json").read_text())
    att = next(c for c in s["comparisons"] if c["measure"] == "attacks")
    assert att["n"] == 12 and att["better"] == 10 and att["worse"] == 0
    assert att["p"] < 0.01 and att["p_holm"] >= att["p"]
    assert [f["measure"] for f in s["flags"]] == ["benign"]          # both let every benign through
    assert md.index("## Read first") < md.index("## Per guardrail")
    assert "validity flag `near_ceiling`" in md and "p (Holm)" in md
    assert "## Analysis plan" in md and "No departures" in md


def test_compare_says_when_guardrails_did_not_see_the_same_cases(tmp_path, capsys):
    exp = _exp(tmp_path, {"a": {"h1": ("injection", True), "h2": ("injection", False)},
                          "b": {"h1": ("injection", True), "h3": ("injection", True)}})
    assert direct.main(["compare", str(exp), "--baseline", "a"]) == 0
    md = capsys.readouterr().out
    assert "did not score the same cases" in md and "--filter-sample-seed" in md
    assert "No plan was registered" in md
