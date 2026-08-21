"""evalstats.py: paired statistics over findings.jsonl / samples.jsonl."""
import json
import math
import pathlib
import random
import subprocess
import sys

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB))
import evalstats as es  # noqa: E402


def test_wilson_known():
    p, lo, hi = es.wilson_ci(0, 10)
    assert p == 0 and lo == 0 and abs(hi - 0.2775) < 0.001
    p, lo, hi = es.wilson_ci(5, 10)
    assert abs(lo - 0.2366) < 0.001 and abs(hi - 0.7634) < 0.001
    assert all(math.isnan(v) for v in es.wilson_ci(0, 0))


def test_mcnemar_exact_hand_values():
    assert es.mcnemar_exact(0, 0) == 1.0
    assert abs(es.mcnemar_exact(1, 6) - 0.125) < 1e-9        # 2 * (7+1)/128
    assert abs(es.mcnemar_exact(0, 5) - 0.0625) < 1e-9       # 2 * 1/32
    assert es.mcnemar_exact(4, 4) == 1.0


def test_fleiss_kappa_textbook():
    # Fleiss (1971) example, N=10 subjects, n=14 raters, k=5 categories -> kappa ~ 0.210
    m = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
         [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    assert abs(es.fleiss_kappa(m) - 0.210) < 0.002
    assert es.fleiss_kappa([[3, 0], [0, 3]]) == 1.0
    assert es.fleiss_kappa([]) is None


def test_wilcoxon_exact_and_approx():
    x = [1, 2, 3, 4, 5, 6]
    y = [3, 4, 5, 6, 7, 8]                # all positive diffs, n=6 -> exact two-sided p = 2/64
    W, p, n = es.wilcoxon_signed_rank(x, y)
    assert n == 6 and W == 0 and abs(p - 2 / 64) < 1e-9
    W, p, n = es.wilcoxon_signed_rank([1, 1], [1, 1])
    assert n == 0 and p == 1.0
    rng = random.Random(1)
    a = [rng.random() for _ in range(40)]
    b = [v + 0.5 for v in a]
    W, p, n = es.wilcoxon_signed_rank(a, b)
    assert n == 40 and p < 1e-6


def test_paired_bootstrap_contains_truth_and_seeded():
    rng = random.Random(0)
    x = [rng.gauss(4, 1) for _ in range(30)]
    y = [v - 1.0 + rng.gauss(0, 0.3) for v in x]         # true delta -1
    m, lo, hi = es.paired_bootstrap_ci(x, y, B=2000, seed=7)
    assert lo < -1.0 < hi and abs(m + 1.0) < 0.2
    assert es.paired_bootstrap_ci(x, y, B=2000, seed=7) == (m, lo, hi)
    assert es.paired_bootstrap_ci([1.0], [2.0]) == (1.0, 1.0, 1.0)


def _synthetic(tmp_path, k=12):
    """2 arms; arm D has 1 fewer high finding per sample and never exploitable; sample 3 of A didn't build;
    zero-finding sample exists in D; scan-code repeated 3x with one flaky cell."""
    findings, samples = [], []
    for arm in ("A", "D"):
        for i in range(1, k + 1):
            built = not (arm == "A" and i == 3)
            samples.append({"run": "e", "arm": arm, "target": "spec-01", "sample": i, "build_ok": built,
                            "acceptance_pass": True if built else None, "cost_usd": 1.0 if arm == "A" else 1.5,
                            "contaminated": False, "wall_s": 100})
            if not built:
                continue
            n_high = 3 if arm == "A" else 2
            if arm == "D" and i == 1:
                n_high = 0                                   # zero-finding sample
            for j in range(n_high):
                findings.append({"run": "e", "arm": arm, "target": "spec-01", "sample": i, "tool": "codeql",
                                 "tool_run": 1, "cwe": "22", "cwe_family": "22", "file": f"f{j}.py",
                                 "line": j, "severity": "high", "exploitable": None, "oracle_confirmed": None})
            if arm == "A":
                findings.append({"run": "e", "arm": arm, "target": "spec-01", "sample": i, "tool": "probe",
                                 "tool_run": 1, "cwe": "918", "cwe_family": "918", "file": "imp.py",
                                 "severity": "critical", "exploitable": True, "oracle_confirmed": True})
            for r in (1, 2, 3):
                findings.append({"run": "e", "arm": arm, "target": "spec-01", "sample": i, "tool": "scan-code",
                                 "tool_run": r, "cwe": "22", "cwe_family": "22", "file": "f0.py",
                                 "severity": "high", "exploitable": None, "oracle_confirmed": None})
                if r == 1:  # flaky: only in run 1
                    findings.append({"run": "e", "arm": arm, "target": "spec-01", "sample": i, "tool": "scan-code",
                                     "tool_run": r, "cwe": "79", "cwe_family": "79", "file": "v.py",
                                     "severity": "medium", "exploitable": None, "oracle_confirmed": None})
    fp, sp = tmp_path / "findings.jsonl", tmp_path / "samples.jsonl"
    fp.write_text("".join(json.dumps(r) + "\n" for r in findings))
    sp.write_text("".join(json.dumps(r) + "\n" for r in samples))
    return fp, sp


def test_majority_vote_and_flip_rate(tmp_path):
    fp, sp = _synthetic(tmp_path)
    f = es.load_jsonl(fp)
    fr, cells = es.flip_rate(f, "scan-code")
    assert cells == 2 * 23 and abs(fr - 0.5) < 1e-9          # 2 cells/sample, one flaky
    kept = es.majority_vote(f, "scan-code", 2, 3)
    sc = [r for r in kept if r["tool"] == "scan-code"]
    assert len(sc) == 23 and all(r["cwe_family"] == "22" and r["agree_frac"] == 1.0 for r in sc)
    kap, n = es.scanner_kappa(f, "scan-code")
    assert n == 46 and kap is not None and kap < 0.6


def test_end_to_end_summary(tmp_path):
    fp, sp = _synthetic(tmp_path)
    out, js = tmp_path / "summary.md", tmp_path / "summary.json"
    r = subprocess.run([sys.executable, str(LIB / "evalstats.py"), str(fp), "--samples", str(sp),
                        "--baseline", "A", "--majority", "scan-code=2/3", "--boot", "500",
                        "--out", str(out), "--json", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    J = json.loads(js.read_text())
    assert J["arms"] == ["A", "D"]
    assert J["arms_summary"]["A"]["built"] == 11 and J["arms_summary"]["D"]["built"] == 12
    # zero-finding sample counted in D's denominator (12 samples), and pairs exclude A's failed build
    assert J["paired"]["D"]["pairs"] == 11
    d = J["paired"]["D"]["delta_sev"]
    # per sample: A = 3 codeql + 1 probe(critical) + 1 scan-code = 5 high+; D = 2 + 1 = 3 (sample1: 0+1) -> mean delta ≈ -2.18
    assert d[1] <= d[0] <= d[2] and -2.6 < d[0] < -1.8
    b, c, p = J["paired"]["D"]["mcnemar_any_exploitable"]
    assert (b, c) == (11, 0) and p < 0.001
    assert J["arms_summary"]["D"]["correct_and_secure"][0] == 1.0
    assert J["arms_summary"]["A"]["correct_and_secure"][0] == 0.0
    assert J["scanner_repeats"]["scan-code"]["flip_rate"] == 0.5
    assert abs(J["cost"]["A"]["usd_total"] - 11.0) < 1e-9
    md = out.read_text()
    assert "## Paired deltas vs A" in md and "CWE-22" in md and "CWE-918" in md and "not for CI gating" in md


def test_derive_samples_when_missing(tmp_path):
    fp, _ = _synthetic(tmp_path)
    (tmp_path / "samples.jsonl").unlink()
    r = subprocess.run([sys.executable, str(LIB / "evalstats.py"), str(fp), "--baseline", "A", "--boot", "200"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "deriving samples" in r.stderr and "| A |" in r.stdout
