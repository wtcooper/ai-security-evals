"""The registered plan, the cost/power preview, and the validity notes the kind reports open with
(near-ceiling recall or TPR, run-to-run flips)."""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "extension"))
import plan as planlib  # noqa: E402
import score_assets as sa  # noqa: E402


def _register(exp, *extra):
    return subprocess.run([sys.executable, str(ROOT / "plan.py"), str(exp), "--kind", "code",
                           "--arms", "a,b", "--benchmark", "fixture", "--targets", "40",
                           "--depth", "standard", *extra], capture_output=True, text=True)


def test_plan_is_registered_with_power_and_amendments_are_kept(tmp_path):
    corpus = tmp_path / "gt.jsonl"
    corpus.write_text('{"target":"T1","id":"g1"}\n')
    r = _register(tmp_path, "--repeats", "a=3", "--corpus", str(corpus))
    assert r.returncode == 0, r.stderr
    assert "two arms must differ on at least" in r.stderr and "tool runs per arm: a 120, b 40" in r.stderr
    doc = json.loads((tmp_path / "plan.json").read_text())
    plan = doc["plan"]
    assert doc["registered_before_results"] and plan["repeats"] == {"a": 3, "b": 1}
    assert plan["baseline"] == "a" and plan["judge"] is None
    assert plan["corpus"]["visibility"] == "public" and len(plan["corpus"]["sha256"]) == 64
    assert _register(tmp_path, "--repeats", "a=3", "--corpus", str(corpus)).returncode == 0
    assert json.loads((tmp_path / "plan.json").read_text())["amendments"] == []   # same plan
    _register(tmp_path, "--repeats", "1", "--reason", "the reviewer is deterministic")
    doc = json.loads((tmp_path / "plan.json").read_text())
    assert doc["amendments"][-1]["reason"] == "the reviewer is deterministic"


def test_repeats_default_per_kind_and_must_name_arms():
    assert planlib.parse_repeats(None, ["a", "b"], "pentest") == {"a": 3, "b": 3}
    assert planlib.parse_repeats("2", ["a", "b"], "code") == {"a": 2, "b": 2}
    with pytest.raises(ValueError, match="not an arm"):
        planlib.parse_repeats("c=2", ["a", "b"], "code")


def test_match_report_flags_ceiling_flips_and_shows_the_plan(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    gt = [{"target": "T1", "id": "g1", "cwe": "22", "file": "a.py", "line": 5},
          {"target": "T1", "id": "g2", "cwe": "89", "file": "b.py", "line": 9}]
    hit = lambda arm, cwe, f, line, run: {"target": "T1", "tool": arm, "arm": arm, "cwe": cwe,  # noqa: E731
                                          "cwe_family": cwe, "file": f, "line": line,
                                          "message": "", "tool_run": run}
    F = [hit("a", "22", "a.py", 5, 1), hit("a", "89", "b.py", 9, 1),
         hit("b", "22", "a.py", 5, 1), hit("b", "89", "b.py", 9, 1),
         hit("b", "22", "a.py", 5, 2)]                                  # b misses g2 in run 2
    runs = [{"arm": "a", "target": "T1", "tool_run": 1, "status": "ok"},
            {"arm": "b", "target": "T1", "tool_run": 1, "status": "ok"},
            {"arm": "b", "target": "T1", "tool_run": 2, "status": "ok"}]
    for name, rows in (("findings", F), ("gt", gt), ("runs", runs)):
        (exp / f"{name}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    subprocess.run([sys.executable, str(ROOT / "plan.py"), str(exp), "--kind", "code", "--arms",
                    "a,b", "--benchmark", "fixture", "--targets", "1", "--repeats", "b=3"],
                   check=True, capture_output=True)
    out = subprocess.run([sys.executable, str(ROOT / "code" / "match.py"), str(exp / "findings.jsonl"),
                          str(exp / "gt.jsonl"), "--out", str(exp / "m.jsonl"), "--report",
                          str(exp / "m.md"), "--group-by", "arm", "--runs", str(exp / "runs.jsonl")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    json.loads(out.stderr)                                   # stderr stays the scores JSON
    md = (exp / "m.md").read_text()
    assert md.index("## Read first") < md.index("| arm |")
    assert "`recall@file`: validity flag `near_ceiling`" in md
    assert "`b`: 50% of 2 known vulnerabilities changed outcome across 2 runs" in md
    assert "## Analysis plan" in md and "`repeats`: planned {'a': 1, 'b': 3}" in md


def test_score_assets_flags_a_saturated_stratum_and_flips():
    rows = []
    for cfg in ("yara", "judge"):
        for a in range(4):
            for r in (1, 2):
                flips = cfg == "judge" and a == 0 and r == 2
                rows.append({"asset": f"m{a}", "label": "malicious", "config": cfg, "run": r,
                             "verdict": "clean" if flips else "flag", "stratum": "shipped"})
                rows.append({"asset": f"b{a}", "label": "benign", "config": cfg, "run": r,
                             "verdict": "flag" if a == 0 else "clean", "stratum": "shipped"})
    md, J = sa.summarize(rows, ["config", "stratum"], ceiling=0.95)
    assert md.index("## Read first") < md.index("| config · stratum |")
    assert "`TPR (shipped)`: validity flag `near_ceiling`" in md      # both configs 4/4
    assert "1 − FPR (shipped)" not in md                              # 3/4 benign left clean
    assert "`judge · shipped`: 12% of 8 assets got a different verdict across 2 runs" in md
    assert J["yara · shipped"]["per_run_flag_rate"] == [0.625, 0.625]
    assert "gating" not in md.lower()
