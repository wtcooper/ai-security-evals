import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import scorecard as sc  # noqa: E402

THREATS = [{"id": "t-injection", "name": "Injection", "risk_source": "untrusted content",
            "lanes": {"known": ["bench-a"], "custom": ["core"]}},
           {"id": "t-leak", "name": "Leak", "risk_source": "secrets in the prompt",
            "lanes": {"known": [], "custom": ["core"]}},
           {"id": "t-unrun", "name": "Unrun", "risk_source": "x",
            "lanes": {"known": ["bench-z"], "custom": []}}]


def rows(model, threat, lane, goods, bench="b"):
    return [{"arm": model, "threat": threat, "lane": lane, "benchmark": bench,
             "case": f"c{i}", "good": g} for i, g in enumerate(goods)]


def test_rates_ranks_and_ordering():
    data = (rows("strong", "t-injection", "known", [True] * 18 + [False] * 2)
            + rows("weak", "t-injection", "known", [True] * 6 + [False] * 14)
            + rows("strong", "t-leak", "custom", [True] * 10)
            + rows("weak", "t-leak", "custom", [True] * 9 + [None]))
    card = sc.build(data, THREATS)
    inj = next(r for r in card["rows"] if r["threat"] == "t-injection")
    assert inj["cells"]["strong"]["rate"] == 0.9 and inj["cells"]["strong"]["rank"] == 1
    assert inj["cells"]["weak"]["rank"] == 2 and inj["best"] == "strong"
    leak = next(r for r in card["rows"] if r["threat"] == "t-leak")
    assert leak["cells"]["weak"]["n"] == 9 and leak["cells"]["weak"]["no_verdict"] == 1
    assert leak["cells"]["weak"]["rate"] == 1.0 and leak["cells"]["weak"]["rank"] == 1  # tie
    assert card["ordering"] == ["strong", "weak"]


def test_separation_needs_paired_evidence_not_just_a_gap():
    big = (rows("a", "t-injection", "known", [True] * 18 + [False] * 2)
           + rows("b", "t-injection", "known", [True] * 6 + [False] * 14))
    seps = sc.build(big, THREATS)["separations"]
    assert len(seps) == 1 and seps[0]["model"] == "b" and seps[0]["p"] < 0.05
    small = (rows("a", "t-injection", "known", [True, True, True])
             + rows("b", "t-injection", "known", [True, False, False]))
    assert sc.build(small, THREATS)["separations"] == []


def test_lane_disagreement_and_coverage():
    data = (rows("a", "t-injection", "known", [True] * 10) + rows("b", "t-injection", "known", [False] * 10)
            + rows("a", "t-injection", "custom", [False] * 10) + rows("b", "t-injection", "custom", [True] * 10))
    card = sc.build(data, THREATS)
    assert card["lane_disagreements"] == [{"threat": "t-injection", "known_best": "a", "custom_best": "b"}]
    cov = {(c["threat"], c["lane"]): c["status"] for c in card["coverage"]}
    assert cov[("t-leak", "custom")] == "not run"
    assert ("t-leak", "known") not in cov          # one lane by design is not a gap
    assert cov[("t-unrun", "known")] == "not run"
    review_only = sc.build(data, THREATS + [{"id": "t-none", "name": "n", "risk_source": "r",
                                             "lanes": {"known": [], "custom": []}}])
    assert {"threat": "t-none", "lane": "either", "status": "no benchmark; a design-review question",
            "planned": []} in review_only["coverage"]


def test_rows_without_the_contract_fields_are_ignored(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [
        {"arm": "a", "target": "x", "sample": "1", "good": True},
        {"arm": "a", "threat": "t-leak", "lane": "custom", "case": "c1", "good": True},
        {"arm": "a", "threat": "t-leak", "lane": "other", "case": "c2", "good": True}]))
    assert len(sc.load_samples([str(path)])) == 1


def test_cli_and_report_say_ordering_is_not_a_verdict(tmp_path):
    s1, s2 = tmp_path / "run1.jsonl", tmp_path / "run2.jsonl"
    s1.write_text("\n".join(json.dumps(r) for r in rows("old", "t-injection", "known", [True] * 20)))
    s2.write_text("\n".join(json.dumps(r) for r in rows("new", "t-injection", "known", [False] * 20)))
    th = tmp_path / "threats.json"
    th.write_text(json.dumps({"threats": THREATS}))
    assert sc.main(["--threats", str(th), "--samples", str(s1), str(s2), "--out", str(tmp_path / "o")]) == 0
    text = (tmp_path / "o" / "scorecard.md").read_text()
    assert "does not say whether any of them is acceptable" in text
    assert "Where the risk comes from" in text and "Measurable differences" in text
    assert "| `t-injection` | known | new | old |" in text
    card = json.loads((tmp_path / "o" / "scorecard.json").read_text())
    assert card["ordering"] == ["old", "new"]


def test_single_model_lists_its_lowest_rows():
    text = sc.render(sc.build(rows("only", "t-injection", "known", [True, False]), THREATS),
                     THREATS, "t")
    assert "nothing to compare against yet" in text


def test_wilson_and_mcnemar():
    lo, hi = sc.wilson_ci(9, 10)
    assert lo == pytest.approx(0.596, abs=1e-3) and hi == pytest.approx(0.982, abs=1e-3)
    assert sc.mcnemar_exact(0, 6) == pytest.approx(0.03125)


def test_a_tie_for_first_is_not_a_lane_disagreement():
    data = (rows("a", "t-injection", "known", [True, False]) + rows("b", "t-injection", "known", [True, False])
            + rows("a", "t-injection", "custom", [False] * 4) + rows("b", "t-injection", "custom", [True] * 4))
    assert sc.build(data, THREATS)["lane_disagreements"] == []


def test_holm_counts_every_comparison_in_the_family():
    # Three models each worse than the best on 6 of 20 shared cases: p = 0.031 alone, but
    # 0.094 after Holm over three comparisons, so none is called a measurable difference.
    data = rows("a", "t-leak", "custom", [True] * 20)
    for m in ("b", "c", "d"):
        data += rows(m, "t-leak", "custom", [False] * 6 + [True] * 14)
    card = sc.build(data, THREATS)
    assert card["comparisons"] == 3 and card["separations"] == []
    assert sc.mcnemar_exact(6, 0) < 0.05
    # Alone, the same gap is a separation.
    alone = sc.build(rows("a", "t-leak", "custom", [True] * 20)
                     + rows("b", "t-leak", "custom", [False] * 6 + [True] * 14), THREATS)
    assert [s["model"] for s in alone["separations"]] == ["b"]


def test_repeats_take_the_majority_and_report_flips():
    data = []
    for rep, goods in enumerate([[True, True, False], [True, False, False], [True, True, False]]):
        for i, g in enumerate(goods):
            data.append({"arm": "a", "threat": "t-leak", "lane": "custom", "benchmark": "core",
                         "case": f"c{i}", "repeat": rep, "good": g})
    cell = sc.build(data, THREATS)["rows"][0]["cells"]["a"]
    assert cell["k"] == 2 and cell["n"] == 3 and cell["repeats"] == 3
    assert cell["flip_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_rows_graded_by_different_judges_are_not_compared():
    data = (rows("a", "t-injection", "known", [True] * 20) + rows("b", "t-injection", "known", [False] * 20))
    for r in data:
        r["judge"] = "judge-1" if r["arm"] == "a" else "judge-2"
    card = sc.build(data, THREATS)
    assert card["separations"] == [] and card["rows"][0]["mixed_judges"] == ["judge-1", "judge-2"]
    assert "not compared" in sc.render(card, THREATS, "t")


def test_near_ceiling_is_a_note_not_a_verdict():
    data = rows("a", "t-leak", "custom", [True] * 20) + rows("b", "t-leak", "custom", [True] * 19 + [False])
    card = sc.build(data, THREATS)
    assert card["rows"][0]["near_ceiling"] is True
    assert "separates models poorly" in sc.render(card, THREATS, "t")
    assert sc.build(data, THREATS, ceiling=0.99)["rows"][0]["near_ceiling"] is False


def test_plan_beside_samples_is_checked(tmp_path):
    import evalkit
    exp = tmp_path / "exp"
    evalkit.register_plan(exp, {"arms": ["a", "b", "c"], "measures": ["t-injection"]})
    (exp / "samples.jsonl").write_text("\n".join(json.dumps(r) for r in
                                                  rows("a", "t-injection", "known", [True] * 4)
                                                  + rows("b", "t-injection", "known", [True] * 4)))
    th = tmp_path / "threats.json"
    th.write_text(json.dumps({"threats": THREATS}))
    assert sc.main(["--threats", str(th), "--samples", str(exp / "samples.jsonl"),
                    "--out", str(tmp_path / "o")]) == 0
    text = (tmp_path / "o" / "scorecard.md").read_text()
    assert "## Analysis plan" in text and "`arms`: planned" in text


def test_rows_without_a_judge_beside_judged_rows_are_not_compared():
    data = rows("a", "t-injection", "known", [True] * 20) + rows("b", "t-injection", "known", [False] * 20)
    for r in data:
        if r["arm"] == "a":
            r["judge"] = "judge-v2"
    card = sc.build(data, THREATS)
    assert card["rows"][0]["mixed_judges"] == ["judge-v2", "unrecorded"] and card["separations"] == []


def test_a_judged_and_a_deterministic_benchmark_in_one_lane_are_not_mixed():
    data = (rows("a", "t-injection", "known", [True] * 20, bench="judged")
            + rows("b", "t-injection", "known", [False] * 20, bench="judged")
            + rows("a", "t-injection", "known", [True] * 5, bench="exact")
            + rows("b", "t-injection", "known", [True] * 5, bench="exact"))
    for r in data:
        if r["benchmark"] == "judged":
            r["judge"] = "j"
    assert sc.build(data, THREATS)["rows"][0]["mixed_judges"] == []


def test_a_merged_scorecard_only_reports_what_each_plan_lost(tmp_path):
    import evalkit
    doc = evalkit.register_plan(tmp_path, {"arms": ["a"], "measures": ["t-injection", "t-leak"]})
    card = sc.build(rows("a", "t-injection", "known", [True] * 3) + rows("b", "t-injection", "known", [True] * 3), THREATS)
    devs = evalkit.plan_deviations(doc, sc._observed_for(doc, card))
    assert len(devs) == 1 and "t-leak" in devs[0]
