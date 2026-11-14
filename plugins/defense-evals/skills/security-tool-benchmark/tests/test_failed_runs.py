"""A tool that failed to run on a target must never be scored as having found nothing."""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "extension"))
import score_assets as sa  # noqa: E402

LABELS = {"bad": {"label": "malicious"}, "good": {"label": "benign"}}


def test_failed_scanner_runs_are_errors_not_clean_verdicts():
    findings = [{"arm": "s", "target": "bad", "tool_run": 1, "severity": "high"}]
    runs = [{"arm": "s", "target": "bad", "tool_run": 1, "status": "ok"},
            {"arm": "s", "target": "good", "tool_run": 1, "status": "ok"},
            {"arm": "crashy", "target": "bad", "tool_run": 1, "status": "failed"},
            {"arm": "crashy", "target": "good", "tool_run": 1, "status": "failed"}]
    rows = sa.build_verdicts_from_findings(findings, LABELS, "low", runs)
    by = {(r["config"], r["asset"]): r["verdict"] for r in rows}
    assert by[("s", "bad")] == "flag" and by[("s", "good")] == "clean"
    assert by[("crashy", "bad")] == "error" and by[("crashy", "good")] == "error"
    md, J = sa.summarize(rows, ["config"])
    assert J["s"]["tp"] == 1 and J["s"]["fp"] == 0 and J["s"]["failed_runs"] == 0
    # the crashed scanner has no rate at all, and its failures are counted
    assert J["crashy"]["assets"] == 0 and J["crashy"]["failed_runs"] == 2
    assert "gating" not in md.lower()


def test_without_a_run_log_behaviour_is_unchanged():
    rows = sa.build_verdicts_from_findings(
        [{"arm": "s", "target": "bad", "tool_run": 1, "severity": "high"}], LABELS, "low")
    assert {(r["asset"], r["verdict"]) for r in rows} == {("bad", "flag"), ("good", "clean")}


def test_scoring_cli_builds_verdicts_from_findings_labels_and_runs(tmp_path):
    (tmp_path / "findings.jsonl").write_text(json.dumps(
        {"arm": "s", "target": "bad", "tool_run": 1, "severity": "high"}) + "\n")
    (tmp_path / "labels.jsonl").write_text(
        "".join(json.dumps({"asset": a, **m}) + "\n" for a, m in LABELS.items()))
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"arm": "s", "target": "bad", "tool_run": 1, "status": "ok"},
        {"arm": "s", "target": "good", "tool_run": 1, "status": "failed"}]))
    out = subprocess.run(
        [sys.executable, str(ROOT / "extension" / "score_assets.py"), str(tmp_path / "v.jsonl"),
         "--findings", str(tmp_path / "findings.jsonl"), "--labels", str(tmp_path / "labels.jsonl"),
         "--runs", str(tmp_path / "runs.jsonl"), "--by", "config",
         "--json", str(tmp_path / "s.json")], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    summary = json.loads((tmp_path / "s.json").read_text())["s"]
    assert summary["tp"] == 1 and summary["neg"] == 0 and summary["failed_runs"] == 1


def test_recall_is_computed_only_over_targets_a_tool_scanned(tmp_path):
    gt = [{"target": "T1", "id": "g1", "cwe": "22", "file": "a.py", "line": 5},
          {"target": "T2", "id": "g2", "cwe": "89", "file": "b.py", "line": 5}]
    finding = {"target": "T1", "tool": "a", "arm": "a", "cwe": "22", "cwe_family": "22",
               "file": "a.py", "line": 5, "message": ""}
    runs = [{"arm": "a", "target": "T1", "tool_run": 1, "status": "ok"},
            {"arm": "a", "target": "T2", "tool_run": 1, "status": "failed"},   # crashed on T2
            {"arm": "quiet", "target": "T1", "tool_run": 1, "status": "ok"},
            {"arm": "quiet", "target": "T2", "tool_run": 1, "status": "ok"}]   # ran, found nothing
    for name, rows in (("f", [finding]), ("g", gt), ("r", runs)):
        (tmp_path / f"{name}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    out = subprocess.run(
        [sys.executable, str(ROOT / "code" / "match.py"), str(tmp_path / "f.jsonl"),
         str(tmp_path / "g.jsonl"), "--out", str(tmp_path / "m.jsonl"),
         "--report", str(tmp_path / "m.md"), "--group-by", "arm", "--runs", str(tmp_path / "r.jsonl")],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    scores = json.loads(out.stderr)
    assert scores["a"]["recall_file"] == 1.0 and scores["a"]["ground_truth_scanned"] == 1
    assert scores["quiet"]["recall_file"] == 0.0 and scores["quiet"]["ground_truth_scanned"] == 2
    report = (tmp_path / "m.md").read_text()
    assert "**a** did not complete on 1 target(s)" in report and "T2" in report


def test_planted_script_in_a_mutant_does_not_describe_itself(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
    out = subprocess.run([sys.executable, str(ROOT / "extension" / "mutate_skill.py"), str(src),
                          str(tmp_path / "dst"), "--class", "staged_fetch"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    script = (tmp_path / "dst" / "scripts" / "setup.py").read_text()
    assert "#" not in script, "a comment in the planted file would hand an LLM scanner the answer"
