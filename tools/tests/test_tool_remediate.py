"""tool-remediate: verify_fix.sh classifies fix outcomes from exploit + functional oracles."""
import json
import pathlib
import subprocess

SK = pathlib.Path(__file__).resolve().parents[2] / "skills" / "tool-remediate"


def _repo(tmp_path):
    r = tmp_path / "repo"; r.mkdir()
    g = ["git", "-C", str(r), "-c", "user.email=a@b", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / "app.py").write_text("x=1\n")
    subprocess.run([*g, "add", "-A"], check=True); subprocess.run([*g, "commit", "-qm", "vuln"], check=True)
    pre = subprocess.check_output(["git", "-C", str(r), "rev-parse", "HEAD"], text=True).strip()
    (r / "app.py").write_text("x=2  # fixed\n")
    subprocess.run([*g, "add", "-A"], check=True); subprocess.run([*g, "commit", "-qm", "fix"], check=True)
    post = subprocess.check_output(["git", "-C", str(r), "rev-parse", "HEAD"], text=True).strip()
    return r, pre, post, g


def test_real_fix(tmp_path):
    repo, pre, post, _ = _repo(tmp_path)
    (tmp_path / "manifest.json").write_text("{}")
    # exploit: exit 0 (exploitable) iff app.py still says x=1 ; tests: always pass
    r = subprocess.run(["bash", str(SK / "verify_fix.sh"), str(tmp_path), "t1", str(repo),
                        "--exploit", "grep -q 'x=1$' app.py", "--tests", "true",
                        "--pre-sha", pre, "--post-sha", post], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "FIXED=true" in r.stdout and "EXPLOIT_WORKS=false" in r.stdout and "EXPLOIT_ONLY=false" in r.stdout
    s = json.loads((tmp_path / "samples.jsonl").read_text().splitlines()[0])
    assert s["fixed"] is True and s["exploit_works"] is False


def test_exploit_only_fix_flagged(tmp_path):
    repo, pre, post, _ = _repo(tmp_path)
    (tmp_path / "manifest.json").write_text("{}")
    # exploit stopped (grep x=1 fails on fixed tree) but tests FAIL -> exploit-only fix
    r = subprocess.run(["bash", str(SK / "verify_fix.sh"), str(tmp_path), "t2", str(repo),
                        "--exploit", "grep -q 'x=1$' app.py", "--tests", "false",
                        "--pre-sha", pre, "--post-sha", post], capture_output=True, text=True)
    assert "FIXED=false" in r.stdout and "EXPLOIT_ONLY=true" in r.stdout
