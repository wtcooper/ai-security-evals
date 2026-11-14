"""The runner end to end with the mock harness, the fake tasks and the fake scorer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import report  # noqa: E402
import run_benchmark  # noqa: E402

SMOKE = ["--arms", str(SKILL / "arms"), "--harness", "mock",
         "--tasks", str(SKILL / "fixtures" / "fake_tasks.json"), "--depth", "smoke"]


def rows(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "samples.jsonl").read_text().splitlines()]


def test_plan_prints_the_cost_and_runs_nothing(tmp_path, capsys):
    out = tmp_path / "out"
    assert run_benchmark.main([*SMOKE, "--repeats", "2", "--plan", "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert "8 task(s) x 2 repeat(s) x 2 arm(s) [baseline, placebo]" in err
    assert "16 agent run(s) and 16 app build(s)" in err
    assert "token cost depends on the harness" in err
    assert not out.exists()


def test_baxbench_plan_needs_no_clone_and_uses_the_shared_depth_names(capsys):
    for depth, n in (("smoke", 25), ("standard", 100), ("full", 392), ("7", 7)):
        assert run_benchmark.main(["--harness", "claude_code@1.2.3", "--model", "x/y",
                                   "--depth", depth, "--plan"]) == 0
        assert f"plan: {n} task(s)" in capsys.readouterr().err
    with pytest.raises(ValueError):
        run_benchmark.main(["--depth", "quick", "--plan"])


def test_a_real_harness_must_be_pinned(capsys):
    with pytest.raises(SystemExit):
        run_benchmark.main(["--harness", "claude_code", "--model", "x/y", "--plan"])
    assert "pin the harness version" in capsys.readouterr().err
    assert run_benchmark.parse_harnesses("codex_cli@0.9.0,mock") == [
        {"name": "codex_cli", "version": "0.9.0"}, {"name": "mock", "version": "1"}]


def test_smoke_run_writes_the_results_contract(tmp_path):
    out = tmp_path / "out"
    assert run_benchmark.main([*SMOKE, "--repeats", "2", "--out", str(out)]) == 0
    data = rows(out)
    assert len(data) == 2 * 8 * 2                      # arms x tasks x repeats
    for key in ("arm", "target", "sample", "harness", "harness_version", "model",
                "functional_pass", "secure", "correct_and_secure", "build_ok", "tokens_total",
                "wall_s", "touched"):
        assert key in data[0], key
    by_arm = {arm: sorted((r["target"], r["sample"]) for r in data if r["arm"] == arm)
              for arm in ("baseline", "placebo")}
    assert by_arm["baseline"] == by_arm["placebo"]     # every arm built the same tasks
    summary = json.loads((out / "summary.json").read_text())
    arms = summary["cells"][0]["arms"]
    assert [a["arm"] for a in arms] == ["baseline", "placebo"]
    assert summary["cells"][0]["comparisons"][0]["correct_and_secure"]["tasks"] == 8
    text = (out / "summary.md").read_text()
    assert "Paired difference from `baseline`" in text and "mock" in text.split("## Harness")[0]


def test_arm_reaches_the_workspace_and_the_diagnostic_sees_it(tmp_path):
    out = tmp_path / "out"
    run_benchmark.main([*SMOKE, "--out", str(out)])
    data = rows(out)
    assert all(r["touched"]["arm_file"] is None for r in data if r["arm"] == "baseline")
    placebo = [r["touched"]["arm_file"] for r in data if r["arm"] == "placebo"]
    assert any(placebo) and None not in placebo
    # nothing from the arm ends up in the scored code
    for code in (out / "baxbench").glob("*placebo/*/*/*/sample*/code"):
        assert sorted(p.name for p in code.iterdir()) == ["app.json"]


def test_same_seed_gives_the_same_outcomes_and_another_seed_does_not(tmp_path):
    def outcomes(name, seed):
        out = tmp_path / name
        run_benchmark.main([*SMOKE, "--seed", str(seed), "--out", str(out)])
        return [(r["arm"], r["target"], r["correct_and_secure"], r["build_ok"]) for r in rows(out)]
    assert outcomes("a", 1) == outcomes("b", 1)
    assert outcomes("a2", 1) != outcomes("c", 2)


def test_out_directory_is_not_silently_reused_but_can_be_rescored(tmp_path):
    out = tmp_path / "out"
    run_benchmark.main([*SMOKE, "--out", str(out)])
    first = rows(out)
    with pytest.raises(SystemExit):
        run_benchmark.main([*SMOKE, "--out", str(out)])
    assert run_benchmark.main(["--score-only", "--out", str(out)]) == 0
    strip = [{k: v for k, v in r.items()} for r in rows(out)]
    assert strip == first


def test_report_can_be_rebuilt_from_samples(tmp_path, capsys):
    out = tmp_path / "out"
    run_benchmark.main([*SMOKE, "--out", str(out)])
    capsys.readouterr()
    assert report.main([str(out), "--json", str(tmp_path / "s.json")]) == 0
    assert capsys.readouterr().out.strip() == (out / "summary.md").read_text().strip()
    assert json.loads((tmp_path / "s.json").read_text())["baseline"] == "baseline"


def test_mock_harness_refuses_real_tasks_without_fixed_code(tmp_path):
    sys.path.insert(0, str(SKILL / "lib"))
    import mock_harness
    with pytest.raises(ValueError, match="--mock-code"):
        mock_harness.run({"id": "Calculator@Python-Flask", "prompt": "p"}, tmp_path, 1, 0)
