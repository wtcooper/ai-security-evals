import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import redteam_summary as rs  # noqa: E402


def _res(goal, success, failure_reason=0):
    return {"testCase": {"vars": {"prompt": goal}}, "success": success,
            "failureReason": failure_reason}


def test_attack_success_is_a_failed_grade_and_errors_are_excluded():
    doc = {"results": {"results": [
        _res("a", False), _res("a", True), _res("a", True),     # broken once of three
        _res("b", True), _res("b", True), _res("b", True),      # held every time
        _res("c", False, failure_reason=2),                     # operational error
    ]}}
    m = rs.summarize(doc)
    assert m["attempts"] == 6 and m["errors_excluded"] == 1 and m["objectives"] == 2
    assert m["attack_success_rate"] == round(1 / 6, 4)
    assert m["ci95"][0] < 1 / 6 < m["ci95"][1]
    assert m["objectives_broken_at_least_once"] == 1
    assert m["objectives_with_mixed_outcomes"] == 1
    assert m["by_objective"]["a"] == {"succeeded": 1, "attempts": 3}


def test_an_all_error_run_is_not_reported_as_clean():
    m = rs.summarize({"results": {"results": [_res("a", False, 2), _res("b", False, 2)]}})
    assert m["attempts"] == 0 and m["attack_success_rate"] is None
    assert "nothing was scored" in rs.render(m)


def test_single_attempt_runs_carry_a_noise_note():
    text = rs.render(rs.summarize({"results": {"results": [_res("a", False), _res("b", True)]}}))
    assert "Attack success rate: 0.50" in text and "--repeat 3" in text


def test_flip_rate_over_repeated_objectives():
    import redteam_summary as R
    def r(goal, ok):
        return {"success": ok, "testCase": {"metadata": {"goal": goal}, "vars": {"goal": goal}}}
    doc = {"results": {"results": [r("a", True), r("a", False), r("b", True), r("b", True)]}}
    m = R.summarize(doc)
    assert m["flip_rate"] == 0.5 and "flip rate 50%" in R.render(m)
