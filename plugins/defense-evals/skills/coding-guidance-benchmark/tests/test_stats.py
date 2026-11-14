"""Paired statistics and the report: per-arm rates, the difference from baseline, McNemar."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import stats  # noqa: E402


def row(arm, task, repeat=0, cas=False, functional=None, secure=True, build_ok=True,
        tokens=100, wall=10.0, **extra):
    functional = cas if functional is None else functional
    return {"harness": "h", "model": "m", "arm": arm, "target": task, "sample": str(repeat),
            "correct_and_secure": cas, "functional_pass": functional, "secure": secure,
            "build_ok": build_ok, "code_written": True, "scored": True, "st_exceptions": 0,
            "tokens_in": tokens - 10, "tokens_out": 10, "tokens_total": tokens, "wall_s": wall,
            "error": None, "harness_version": "1.2.3", **extra}


def ab(base_good: set, arm_good: set, tasks=range(10)) -> list[dict]:
    rows = []
    for t in tasks:
        rows.append(row("baseline", f"t{t}", cas=t in base_good))
        rows.append(row("guide", f"t{t}", cas=t in arm_good, tokens=150, wall=12.0))
    return rows


def test_paired_difference_and_exact_mcnemar():
    # 10 tasks. Baseline good on {0,1}; arm good on {0,1,2,3,4,5,6}: five tasks flip to good.
    rows = ab({0, 1}, {0, 1, 2, 3, 4, 5, 6})
    comp = stats.summarise(rows)["cells"][0]["comparisons"][0]["correct_and_secure"]
    assert comp["tasks"] == 10 and comp["diff"] == 0.5
    assert (comp["arm_only"], comp["baseline_only"], comp["both"], comp["neither"]) == (5, 0, 2, 3)
    assert comp["mcnemar_p"] == 0.0625                      # 2 * (1/2)**5
    assert comp["ci95"][0] > 0                              # every resample has diff >= 0


def test_mcnemar_uses_only_discordant_tasks():
    rows = ab({0, 1, 2}, {2, 3, 4})                         # 2 lost, 2 gained, 1 kept
    comp = stats.summarise(rows)["cells"][0]["comparisons"][0]["correct_and_secure"]
    assert comp["diff"] == 0.0 and (comp["arm_only"], comp["baseline_only"]) == (2, 2)
    assert comp["mcnemar_p"] == 1.0


def test_repeats_are_collapsed_per_task_not_counted_as_independent_pairs():
    rows = []
    for t in range(4):
        for r in range(3):
            rows.append(row("baseline", f"t{t}", r, cas=False))
            rows.append(row("guide", f"t{t}", r, cas=(t < 2 and r < 2)))   # 2 of 3 on two tasks
    cell = stats.summarise(rows)["cells"][0]
    comp = cell["comparisons"][0]["correct_and_secure"]
    assert comp["tasks"] == 4                               # not 12
    assert comp["diff"] == round((2 / 3 + 2 / 3) / 4, 4)
    assert (comp["arm_only"], comp["baseline_only"]) == (2, 0)   # majority of repeats
    guide = next(a for a in cell["arms"] if a["arm"] == "guide")
    assert guide["agreement"] == {"tasks": 4, "same": 2, "rate": 0.5}
    assert guide["correct_and_secure"]["n"] == 12


def test_arm_cannot_look_secure_by_breaking_the_app():
    rows = []
    for t in range(6):
        rows.append(row("baseline", f"t{t}", cas=False, functional=True, secure=False))
        rows.append(row("breaker", f"t{t}", cas=False, functional=False, secure=None,
                        build_ok=False))
    cell = stats.summarise(rows)["cells"][0]
    breaker = next(a for a in cell["arms"] if a["arm"] == "breaker")
    assert breaker["secure"]["n"] == 0 and breaker["secure"]["rate"] is None
    assert breaker["functional_pass"]["rate"] == 0.0 and breaker["builds_failed"] == 6
    comp = cell["comparisons"][0]
    assert comp["secure"]["tasks"] == 0 and comp["secure"]["diff"] is None
    assert comp["functional_pass"]["diff"] == -1.0
    text = stats.render(stats.summarise(rows))
    assert "6 of 6 run(s) wrote code that did not build" in text


def test_rates_carry_a_wilson_interval():
    r = stats.rate([True] * 9 + [False] + [None] * 5)
    assert (r["k"], r["n"], r["rate"]) == (9, 10, 0.9)
    assert 0.59 < r["ci95"][0] < 0.61 and 0.98 < r["ci95"][1] < 0.99


def test_cost_of_the_arm_is_paired_on_tasks():
    cell = stats.summarise(ab({0}, {0}))["cells"][0]
    comp = cell["comparisons"][0]
    assert comp["tokens_total"]["diff"] == 50 and comp["wall_s"]["diff"] == 2.0
    assert comp["tokens_total"]["ci95"] == [50.0, 50.0]


def test_baseline_is_listed_first_and_cells_are_kept_apart():
    rows = ab({0}, {1})
    other = [dict(r, harness="h2") for r in ab({0, 1, 2}, {0})]
    summary = stats.summarise(rows + other, [{"name": "guide", "control_type": "rules file"}])
    assert [(c["harness"], [a["arm"] for a in c["arms"]]) for c in summary["cells"]] == [
        ("h", ["baseline", "guide"]), ("h2", ["baseline", "guide"])]
    assert summary["cells"][0]["arms"][1]["control_type"] == "rules file"
    assert summary["cells"][1]["comparisons"][0]["correct_and_secure"]["baseline_only"] == 2


def test_a_task_missing_from_one_arm_is_left_out_of_the_pairing():
    rows = ab({0}, {0, 1})
    rows = [r for r in rows if not (r["arm"] == "guide" and r["target"] == "t9")]
    comp = stats.summarise(rows)["cells"][0]["comparisons"][0]["correct_and_secure"]
    assert comp["tasks"] == 9


def test_report_shows_functional_and_secure_beside_the_headline_and_no_verdict():
    text = stats.render(stats.summarise(ab({0, 1}, {0, 1, 2, 3, 4, 5, 6})),
                        {"task_source": "baxbench", "n_tasks": 10, "repeats": 1, "seed": 1,
                         "depth": "10"})
    assert "Correct and secure | Functional pass | Secure" in text
    assert "+50.0 pts" in text and "0.0625" in text
    lowered = text.lower()
    for word in ("recommend", "acceptable", "passes", "should adopt", "significant"):
        assert word not in lowered
