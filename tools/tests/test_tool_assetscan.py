"""tool-assetscan: score_assets classification + mutate_pickle carriers (scan-only)."""
import json
import pathlib
import pickle
import subprocess
import sys

SK = pathlib.Path(__file__).resolve().parents[2] / "skills" / "tool-assetscan"
sys.path.insert(0, str(SK))
import score_assets as sa  # noqa: E402


def test_score_tpr_fpr_flip_kappa(tmp_path):
    rows = []
    # combined config, shipped stratum: 4 malicious (3 flagged both runs, 1 flips), 4 benign (1 FP)
    for a in range(4):
        for r in (1, 2):
            v = "flag" if (a < 3 or r == 1) else "clean"        # asset 3 flips
            rows.append({"asset": f"m{a}", "label": "malicious", "config": "combined", "run": r, "verdict": v, "stratum": "shipped"})
    for a in range(4):
        for r in (1, 2):
            v = "flag" if a == 0 else "clean"                    # 1 false positive, stable
            rows.append({"asset": f"b{a}", "label": "benign", "config": "combined", "run": r, "verdict": v, "stratum": "shipped"})
    vp = tmp_path / "v.jsonl"; vp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    r = subprocess.run([sys.executable, str(SK / "score_assets.py"), str(vp), "--by", "config,stratum",
                        "--out", str(tmp_path / "s.md"), "--json", str(tmp_path / "s.json")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    J = json.loads((tmp_path / "s.json").read_text())["combined · shipped"]
    assert J["pos"] == 4 and J["neg"] == 4 and J["tp"] == 4 and J["fp"] == 1   # asset m3: majority(1,0)->flag
    assert abs(J["tpr"][0] - 1.0) < 1e-9 and abs(J["fpr"][0] - 0.25) < 1e-9
    assert abs(J["flip_rate"] - 1 / 8) < 1e-9 and J["fleiss_kappa"] is not None


def test_build_verdicts_from_findings():
    findings = [{"target": "m0", "tool_run": 1, "severity": "high"}, {"target": "m0", "tool_run": 2, "severity": "high"},
                {"target": "b0", "tool_run": 1, "severity": "low"}]
    labels = {"m0": {"label": "malicious"}, "b0": {"label": "benign"}, "b1": {"label": "benign"}}
    rows = sa.build_verdicts_from_findings(findings, labels, severity_gate="medium")
    by = {(r["asset"], r["run"]): r["verdict"] for r in rows}
    assert by[("m0", 1)] == "flag" and by[("m0", 2)] == "flag"
    assert by[("b0", 1)] == "clean"                              # low < medium gate
    assert ("b1", 1) in by and by[("b1", 1)] == "clean"          # zero-finding benign present


def test_build_verdicts_segments_by_scanner_arm():
    # two scanners over the SAME asset must not collide: the LLM judge flags m0, YARA misses it.
    findings = [{"target": "m0", "arm": "scan-skill-combined", "tool_run": 1, "severity": "high"},
                {"target": "m0", "arm": "yara", "tool_run": 1, "severity": "low"}]  # low < gate -> clean
    labels = {"m0": {"label": "malicious"}}
    rows = sa.build_verdicts_from_findings(findings, labels, severity_gate="medium")
    by = {(r["config"], r["asset"], r["run"]): r["verdict"] for r in rows}
    assert by[("scan-skill-combined", "m0", 1)] == "flag"        # judge catches it
    assert by[("yara", "m0", 1)] == "clean"                      # signature baseline misses it
    assert {r["config"] for r in rows} == {"scan-skill-combined", "yara"}


def test_mutate_pickle_scan_only(tmp_path):
    for carrier in ("raw", "torch_zip", "base64_exec", "nested"):
        r = subprocess.run([sys.executable, str(SK / "mutate_pickle.py"), str(tmp_path / carrier),
                            "--payload", "print", "--carrier", carrier], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        labels = list((tmp_path / carrier).glob("*.label.json"))
        assert labels and json.loads(labels[0].read_text())["expected"] == "malicious"
        # file exists and is NOT unpickled by the test (scan-only); just confirm bytes present
        art = next(p for p in (tmp_path / carrier).iterdir() if not p.name.endswith(".label.json"))
        assert art.stat().st_size > 0
