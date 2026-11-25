"""What report.py adds to the A/B summary: Holm-adjusted p-values across the whole report,
flip rates between repeats, the near-ceiling flag and the registered analysis plan."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "lib"))
import report  # noqa: E402
import run_benchmark  # noqa: E402
from test_stats import row  # noqa: E402

SMOKE = ["--arms", str(SKILL / "arms"), "--harness", "mock",
         "--tasks", str(SKILL / "fixtures" / "fake_tasks.json"), "--depth", "smoke"]


def three_arms() -> list[dict]:
    """10 tasks. `strong` is good on 7 tasks the baseline fails; `weak` on 2."""
    rows = []
    for t in range(10):
        rows.append(row("baseline", f"t{t}", cas=t < 2))
        rows.append(row("strong", f"t{t}", cas=t < 9))
        rows.append(row("weak", f"t{t}", cas=t < 4))
    return rows


def test_every_mcnemar_p_is_holm_adjusted_across_arms_and_metrics():
    summary = report.build(three_arms(), {})
    tests = [c[m] for c in summary["cells"][0]["comparisons"]
             for m in ("correct_and_secure", "functional_pass", "secure")]
    # 2 arms x 3 metrics; `secure` has no discordant task but is still a test the report prints.
    assert summary["comparison_family"] == 6
    assert all("mcnemar_p_holm" in t for t in tests)
    strong = summary["cells"][0]["comparisons"][0]["correct_and_secure"]
    assert strong["mcnemar_p"] == pytest.approx(0.0156, abs=1e-4)       # 2 * (1/2)^7
    assert strong["mcnemar_p_holm"] == pytest.approx(6 * 0.0156, abs=1e-4)
    text = report.render(summary, {}, None, three_arms())
    assert "Exact McNemar p | p (Holm) |" in text and "adjusted across all 6 McNemar" in text
    assert "| 0.0156 | 0.0936 |" in text                    # raw p stays beside the adjusted one


def test_a_metric_every_arm_aces_is_flagged_near_the_ceiling():
    summary = report.build(three_arms(), {})
    flags = summary["cells"][0]["ceiling_flags"]
    assert [f["metric"] for f in flags] == ["secure"] and flags[0]["flag"] == "near_ceiling"
    assert report.build(three_arms(), {}, ceiling=1.01)["cells"][0]["ceiling_flags"] == []
    text = report.render(summary, {}, None, three_arms())
    assert "near the ceiling" in text.split("## Harness")[0]


def test_flip_rates_between_repeats_are_reported_per_arm_and_task():
    rows = []
    for t in range(4):
        for r in range(2):
            rows.append(row("baseline", f"t{t}", r, cas=False))
            rows.append(row("guide", f"t{t}", r, cas=(t == 0 or (t == 1 and r == 0))))
    summary = report.build(rows, {"repeats": 2})
    cell = summary["cells"][0]
    assert cell["repeats"]["guide"]["correct_and_secure"]["flip_rate"] == 0.25
    assert cell["repeats"]["baseline"]["correct_and_secure"]["flip_rate"] == 0.0
    assert cell["flipped_tasks"] == {"guide": ["t1"]}
    text = report.render(summary, {"repeats": 2}, None, rows)
    assert "### Repeats" in text and "flipped under `guide`: `t1`" in text


def test_the_run_registers_its_plan_first_and_the_report_shows_it(tmp_path, capsys):
    out = tmp_path / "out"
    assert run_benchmark.main([*SMOKE, "--repeats", "2", "--out", str(out)]) == 0
    doc = json.loads((out / "plan.json").read_text())
    plan = doc["plan"]
    assert doc["registered_before_results"] is True
    assert plan["arms"] == ["baseline", "placebo"] and plan["baseline"] == "baseline"
    assert plan["repeats"] == 2 and plan["judge"] is None
    assert plan["corpus"]["visibility"] == "public"           # the bundled fake tasks
    samples = [json.loads(line) for line in (out / "samples.jsonl").read_text().splitlines()]
    assert {r["repeat"] for r in samples} == {0, 1}
    text = (out / "summary.md").read_text()
    assert "## Analysis plan" in text and "No departures" in text and "### Repeats" in text
    capsys.readouterr()
    assert report.main([str(out), "--json", str(tmp_path / "s.json")]) == 0
    assert capsys.readouterr().out.strip() == text.strip()
    assert json.loads((tmp_path / "s.json").read_text())["plan_deviations"] == []


def test_the_plan_preview_shows_what_the_run_can_separate(capsys):
    assert run_benchmark.main([*SMOKE, "--plan", "--out", "unused"]) == 0
    assert "precision:" in capsys.readouterr().err
