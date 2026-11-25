import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import judgecheck as jc  # noqa: E402


def rows(judge, arm, goods, lengths=None, target="t"):
    lengths = lengths or [100] * len(goods)
    return [{"arm": arm, "target": target, "sample": str(i), "epoch": 1, "good": g,
             "judge": judge, "response_chars": n} for i, (g, n) in enumerate(zip(goods, lengths))]


def test_agreement_kappa_and_order_change():
    prim = rows("j1", "a", [True] * 8 + [False] * 2) + rows("j1", "b", [True] * 6 + [False] * 4)
    sec = rows("j2", "a", [True] * 5 + [False] * 5) + rows("j2", "b", [True] * 6 + [False] * 4)
    res = jc.check(prim, sec)
    g = res["groups"]["t"]
    assert res["paired_cases"] == 20 and g["primary_only_good"] == 3 and g["secondary_only_good"] == 0
    assert g["order_primary"] == ["a", "b"] and g["order_secondary"] == ["b", "a"]
    assert g["order_changes"] and g["leader_changes"]
    assert "order of arms reverses" in jc.render(res) and g["reversed_pairs"] == [("a", "b")]


def test_kappa_values():
    assert jc.cohen_kappa([(True, True), (False, False)] * 5) == 1.0
    assert jc.cohen_kappa([(True, False), (False, True)] * 5) == -1.0
    assert jc.cohen_kappa([(True, True)] * 4) is None     # no variation: undefined
    assert jc.cohen_kappa([]) is None


def test_length_correlation_and_unpaired_rows():
    prim = rows("j1", "a", [True, True, False, False], [400, 300, 20, 30])
    r, n = jc.point_biserial(prim)
    assert n == 4 and r > 0.9
    res = jc.check(prim, rows("j2", "a", [True, True]))
    assert res["paired_cases"] == 2 and res["unpaired_primary"] == 2


def test_cli_refuses_the_same_judge(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(json.dumps(r) for r in rows("j1", "a", [True, False])))
    b.write_text("\n".join(json.dumps(r) for r in rows("j1", "a", [True, True])))
    assert jc.main(["--primary", str(a), "--secondary", str(b), "--out", str(tmp_path)]) == 2
    b.write_text("\n".join(json.dumps(r) for r in rows("j2", "a", [True, True])))
    assert jc.main(["--primary", str(a), "--secondary", str(b), "--out", str(tmp_path)]) == 0
    assert "Second-judge check" in (tmp_path / "judge_check.md").read_text()


def test_a_tie_under_one_judge_is_not_a_reversal():
    prim = rows("j1", "a", [True] * 6 + [False] * 4) + rows("j1", "b", [True] * 8 + [False] * 2)
    sec = rows("j2", "a", [True] * 7 + [False] * 3) + rows("j2", "b", [True] * 7 + [False] * 3)
    assert jc.check(prim, sec)["groups"]["t"]["order_changes"] is False
