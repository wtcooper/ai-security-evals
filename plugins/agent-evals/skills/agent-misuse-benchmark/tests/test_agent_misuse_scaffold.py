"""The scaffold's own behaviour: pack rules, the plug-in contracts, the statistics, and the
refusals that keep it from being run half-built."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
import interfaces  # noqa: E402
import metrics  # noqa: E402
import run_benchmark  # noqa: E402
import scenarios  # noqa: E402

EXAMPLE = SKILL / "scenarios.example"


def _pack(pairs):
    return {"name": "p", "pairs": pairs}


def _pair(pid="pair-01", **over):
    base = {"id": pid, "category": "c", "restricted": {"prompt": "do r"},
            "permitted": {"prompt": "do p"}}
    return {**base, **over}


# --- scenario packs ------------------------------------------------------------------

def test_shipped_example_is_placeholders_only_and_valid_only_for_the_mock():
    pack = scenarios.load_pack(EXAMPLE)
    assert scenarios.validate_pack(pack, allow_placeholders=True) == []
    problems = scenarios.validate_pack(pack)
    assert problems and all("placeholder" in p for p in problems)
    for pair in pack["pairs"]:
        for kind in scenarios.KINDS:
            assert scenarios.PLACEHOLDER.fullmatch(pair[kind]["prompt"]), \
                "the scaffold must ship no real task text"


def test_every_restricted_task_needs_a_permitted_twin():
    errs = scenarios.validate_pack(_pack([_pair(permitted=None)]))
    assert any("missing the `permitted` task" in e for e in errs)
    errs = scenarios.validate_pack(_pack([_pair(restricted=None)]))
    assert any("missing the `restricted` task" in e for e in errs)


def test_pack_rules():
    assert scenarios.validate_pack(_pack([_pair()])) == []
    assert any("duplicate" in e for e in scenarios.validate_pack(_pack([_pair(), _pair()])))
    assert any("category" in e for e in scenarios.validate_pack(_pack([_pair(category="")])))
    assert any("`id`" in e for e in scenarios.validate_pack(_pack([_pair(pid="Bad ID")])))
    assert scenarios.validate_pack({"name": "p", "pairs": []})
    bad_framing = _pair(framings=[{"label": "x"}])
    assert any("framings[0]" in e for e in scenarios.validate_pack(_pack([bad_framing])))


def test_tasks_flatten_pairs_and_framings_share_the_pair():
    pack = _pack([_pair(framings=[{"label": "alt", "prompt": "do r differently"}])])
    tasks = scenarios.tasks(pack)
    assert [t["id"] for t in tasks] == ["pair-01.restricted", "pair-01.permitted",
                                        "pair-01.restricted.alt"]
    assert {t["pair"] for t in tasks} == {"pair-01"}
    assert tasks[2]["kind"] == "restricted" and tasks[2]["framing"] == "alt"
    assert tasks[2]["prompt"] == "do r differently"


def test_selection_is_seeded_and_the_same_for_every_arm():
    pack = _pack([_pair(f"pair-{i:02d}") for i in range(10)])
    first = scenarios.select_pairs(pack, 4, seed=7)
    assert first == scenarios.select_pairs(pack, 4, seed=7) and len(first) == 4
    assert scenarios.select_pairs(pack, 4, seed=8) != first
    assert len(scenarios.select_pairs(pack, None, seed=7)) == 10


# --- plug-in contracts ---------------------------------------------------------------

def test_no_real_harness_or_scorer_ships():
    with pytest.raises(NotImplementedError, match="build-guide"):
        interfaces.get_harness("claude_code")
    with pytest.raises(NotImplementedError, match="build-guide"):
        interfaces.get_scorer("judge")
    for cls in (interfaces.Harness, interfaces.Scorer):
        with pytest.raises(NotImplementedError):
            (cls().preflight() if cls is interfaces.Harness else cls().score({}, {}))


def test_an_illegal_or_missing_outcome_is_unscored_never_a_guess():
    restricted, permitted = {"kind": "restricted"}, {"kind": "permitted"}
    assert interfaces.check_outcome(restricted, {"outcome": "declined"}) == "declined"
    assert interfaces.check_outcome(restricted, {"outcome": "completed"}) == "unscored"
    assert interfaces.check_outcome(permitted, {"outcome": "carried_out"}) == "unscored"
    assert interfaces.check_outcome(permitted, None) == "unscored"
    assert interfaces.check_outcome(permitted, {"outcome": "error"}) == "error"


def test_user_scorer_and_harness_modules_are_loaded_by_path(tmp_path):
    scorer = tmp_path / "s.py"
    scorer.write_text("def score(task, run):\n    return {'outcome': 'declined', 'evidence': 'e'}\n")
    assert interfaces.get_scorer(str(scorer)).score({}, {})["outcome"] == "declined"
    (tmp_path / "bad.py").write_text("x = 1\n")
    with pytest.raises(TypeError):
        interfaces.get_scorer(str(tmp_path / "bad.py"))
    harness = tmp_path / "h.py"
    harness.write_text("def make_harness(name):\n    return name.upper()\n")
    assert interfaces.get_harness("abc", str(harness)) == "ABC"


# --- statistics ----------------------------------------------------------------------

def _row(arm, pair, kind, outcome, framing="default", category="c"):
    task = f"{pair}.{kind}" + ("" if framing == "default" else f".{framing}")
    return {"arm": arm, "task": task, "kind": kind, "framing": framing, "category": category,
            "outcome": outcome}


def test_rates_exclude_runs_with_no_verdict_and_count_them():
    rows = ([_row("a", f"p{i}", "restricted", "declined") for i in range(6)]
            + [_row("a", f"p{i}", "restricted", "carried_out") for i in range(6, 8)]
            + [_row("a", "p8", "restricted", "unscored"), _row("a", "p9", "restricted", "error")]
            + [_row("a", f"p{i}", "permitted", "completed") for i in range(9)]
            + [_row("a", "p9", "permitted", "declined")])
    m = metrics.arm_metrics(rows)
    assert m["restricted_declined"]["k"] == 6 and m["restricted_declined"]["n"] == 8
    assert m["restricted_declined"]["rate"] == 0.75
    assert m["permitted_completed"]["rate"] == 0.9 and m["permitted_declined"]["k"] == 1
    assert m["unscored"] == 1 and m["errors"] == 1


def test_declining_everything_is_flagged_not_rewarded():
    rows = ([_row("a", f"p{i}", "restricted", "declined") for i in range(10)]
            + [_row("a", f"p{i}", "permitted", "declined") for i in range(10)])
    m = metrics.arm_metrics(rows)
    assert m["restricted_declined"]["rate"] == 1.0 and m["permitted_completed"]["rate"] == 0.0
    names = {f["flag"] for f in metrics.flags(m, 0.05, 0.3)}
    assert names == {"low_permitted_completion"}


def test_framings_are_reported_separately_and_kept_out_of_the_headline():
    rows = ([_row("a", "p1", "restricted", "declined"), _row("a", "p1", "permitted", "completed"),
             _row("a", "p1", "restricted", "carried_out", framing="alt")])
    m = metrics.arm_metrics(rows)
    assert m["restricted_declined"]["n"] == 1 and m["restricted_declined"]["rate"] == 1.0
    assert m["by_framing"]["alt"]["rate"] == 0.0 and m["by_framing"]["default"]["rate"] == 1.0


def test_paired_comparison_uses_only_tasks_graded_in_both_arms():
    rows = []
    for i in range(8):
        rows.append(_row("base", f"p{i}", "restricted", "declined"))
        rows.append(_row("other", f"p{i}", "restricted", "carried_out" if i < 5 else "declined"))
    rows.append(_row("base", "p9", "restricted", "declined"))
    rows.append(_row("other", "p9", "restricted", "unscored"))
    result = metrics.paired(rows, "base", "other", "restricted", "declined")
    assert result["n"] == 8 and result["worse"] == 5 and result["better"] == 0
    assert result["delta"] == -0.625 and result["p"] == pytest.approx(0.0625)
    assert metrics.paired(rows, "base", "missing", "restricted", "declined") is None


def test_repeats_collapse_to_the_majority_outcome_and_a_tie_is_no_verdict():
    def rep(task_pair, outcome, k):
        return {**_row("a", task_pair, "restricted", outcome), "repeat": k}
    rows = ([rep("p1", "declined", k) for k in range(3)]
            + [rep("p2", o, k) for k, o in enumerate(["declined", "carried_out", "declined"])]
            + [rep("p3", o, k) for k, o in enumerate(["declined", "carried_out", "error"])]
            + [rep("p4", "error", k) for k in range(2)])
    by = {r["task"]: r["outcome"] for r in metrics.collapse(rows)}
    assert by == {"p1.restricted": "declined", "p2.restricted": "declined",
                  "p3.restricted": "split", "p4.restricted": "error"}
    m = metrics.arm_metrics(metrics.collapse(rows))
    assert m["restricted_declined"]["n"] == 2 and m["split"] == 1 and m["runs"] == 4
    flips = metrics.repeat_flips(rows)["a|restricted"]
    assert flips["cases"] == 3 and flips["flip_rate"] == pytest.approx(2 / 3, abs=1e-4)


def test_every_p_value_is_holm_adjusted_and_a_saturated_measure_is_flagged():
    rows = []
    for arm, declined in (("base", 10), ("other", 4)):
        for i in range(10):
            rows.append(_row(arm, f"p{i}", "restricted",
                             "declined" if i < declined else "carried_out"))
            rows.append(_row(arm, f"p{i}", "permitted", "completed"))
    s = metrics.summarize(rows)
    by = {c["kind"]: c for c in s["comparisons"]}
    assert by["restricted"]["p"] == pytest.approx(0.0312, abs=1e-4)          # 2 * (1/2)^6
    assert by["restricted"]["p_holm"] == pytest.approx(0.0625, abs=2e-4)     # x 2 comparisons
    assert by["permitted"]["p_holm"] == 1.0
    assert [f["measure"] for f in s["ceiling_flags"]] == ["permitted_completed"]
    text = metrics.render(s, {"depth": "full"})
    assert "p (Holm)" in text and "none at this sample size" in text and "near_ceiling" in text


# --- runner --------------------------------------------------------------------------

def _mock_run(tmp_path, *extra):
    out = tmp_path / "out"
    code = run_benchmark.main(["--scenarios", str(EXAMPLE),
                               "--arms", str(EXAMPLE / "arms.mock.json"), "--harness", "mock",
                               "--scorer", "mock", "--depth", "smoke", "--out", str(out), *extra])
    return code, out


def test_mock_smoke_run_writes_the_results_contract(tmp_path):
    code, out = _mock_run(tmp_path)
    assert code == 0
    rows = metrics.load_samples(out / "samples.jsonl")
    assert len(rows) == 3 * 13 and {r["arm"] for r in rows} == {
        "model-a/harness-x", "model-a/harness-y", "model-b/harness-x"}
    assert all({"arm", "target", "sample", "outcome", "evidence", "harness", "safeguards"} <= set(r)
               for r in rows)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["baseline"] == "model-a/harness-x" and len(summary["comparisons"]) == 4
    text = (out / "summary.md").read_text()
    assert "The harness is the mock" in text and "acceptable" in text


def test_plan_prints_cost_and_runs_nothing(tmp_path, capsys):
    code, out = _mock_run(tmp_path, "--plan")
    assert code == 0 and not out.exists()
    err = capsys.readouterr().err
    assert "3 arm(s)" in err and "precision:" in err and "across 4 comparisons" in err


def test_the_plan_is_registered_before_results_and_repeats_are_reported(tmp_path):
    code, out = _mock_run(tmp_path, "--repeats", "3")
    assert code == 0
    doc = json.loads((out / "plan.json").read_text())
    assert doc["registered_before_results"] is True
    plan = doc["plan"]
    assert plan["arms"][0] == plan["baseline"] == "model-a/harness-x" and plan["repeats"] == 3
    assert plan["corpus"]["visibility"] == "public" and plan["judge"] is None
    rows = metrics.load_samples(out / "samples.jsonl")
    assert len(rows) == 3 * 13 * 3 and {r["repeat"] for r in rows} == {0, 1, 2}
    assert (out / "runs" / "model-a" / "harness-x" / "pair-01.restricted" / "r2" / "run.json").is_file()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["repeats"]["model-a/harness-y|restricted"]["flip_rate"] > 0   # repeat_noise
    assert summary["repeats"]["model-a/harness-x|restricted"]["flip_rate"] == 0
    assert summary["per_arm"]["model-a/harness-x"]["runs"] == 13
    text = (out / "summary.md").read_text()
    assert "## Repeats" in text and "## Analysis plan" in text and "No departures" in text


def test_a_placeholder_pack_is_refused_for_a_real_harness(tmp_path, capsys):
    code = run_benchmark.main(["--scenarios", str(EXAMPLE),
                               "--arms", str(EXAMPLE / "arms.mock.json"),
                               "--harness", "some-real-harness", "--out", str(tmp_path / "o")])
    assert code == 2 and "placeholder" in capsys.readouterr().err


def test_a_harness_that_cannot_show_its_sandbox_is_offline_is_refused(tmp_path, capsys):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps(_pack([_pair()])))
    harness = tmp_path / "h.py"
    harness.write_text(
        "import sys\nsys.path.insert(0, %r)\nimport interfaces\n"
        "class H(interfaces.Harness):\n"
        "    def preflight(self):\n        return {'egress_blocked': False, 'why': 'not checked'}\n"
        "    def run(self, task, arm, workdir):\n        raise AssertionError('must not run')\n"
        "def make_harness(name):\n    return H()\n" % str(SKILL))
    scorer = tmp_path / "s.py"
    scorer.write_text("def score(task, run):\n    return {'outcome': 'declined', 'evidence': ''}\n")
    code = run_benchmark.main(["--scenarios", str(pack), "--arms", str(EXAMPLE / "arms.mock.json"),
                               "--harness", "h", "--harness-module", str(harness),
                               "--scorer", str(scorer), "--out", str(tmp_path / "o")])
    assert code == 3 and "refusing to run" in capsys.readouterr().err


def test_a_failed_run_or_scorer_is_recorded_not_dropped(tmp_path):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps(_pack([_pair()])))
    harness = tmp_path / "h.py"
    harness.write_text(
        "import sys\nsys.path.insert(0, %r)\nimport interfaces\n"
        "class H(interfaces.Harness):\n"
        "    def preflight(self):\n        return {'egress_blocked': True}\n"
        "    def run(self, task, arm, workdir):\n"
        "        if task['kind'] == 'permitted':\n            raise RuntimeError('sandbox died')\n"
        "        return {'final_text': '', 'events': [], 'workspace': str(workdir), 'error': None}\n"
        "def make_harness(name):\n    return H()\n" % str(SKILL))
    scorer = tmp_path / "s.py"
    scorer.write_text("def score(task, run):\n    raise ValueError('cannot tell')\n")
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps([{"name": "a", "model": "m", "harness": "h", "safeguards": "on"}]))
    out = tmp_path / "o"
    assert run_benchmark.main(["--scenarios", str(pack), "--arms", str(arms), "--harness", "h",
                               "--harness-module", str(harness), "--scorer", str(scorer),
                               "--out", str(out)]) == 0
    by = {r["kind"]: r for r in metrics.load_samples(out / "samples.jsonl")}
    assert by["permitted"]["outcome"] == "error" and "sandbox died" in by["permitted"]["evidence"]
    assert by["restricted"]["outcome"] == "unscored"


def test_arms_must_say_what_differs(tmp_path):
    arms = tmp_path / "arms.json"
    arms.write_text(json.dumps([{"name": "a", "model": "m"}]))
    with pytest.raises(ValueError, match="needs `harness`"):
        run_benchmark.load_arms(str(arms))
