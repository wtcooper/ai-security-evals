"""ephemeral_repo.sh: argument handling + command shapes (dry-run; no network)."""
import pathlib
import subprocess

S = pathlib.Path(__file__).resolve().parent.parent / "ephemeral_repo.sh"


def _r(*args):
    return subprocess.run(["bash", str(S), *args, "--dry-run"], capture_output=True, text=True)


def test_create_and_dispatch_shapes(tmp_path):
    r = _r("create", "--name", "eval-x", "--dir", str(tmp_path / "r"), "--owner", "me")
    assert r.returncode == 0, r.stderr
    assert "gh repo create me/eval-x --public" in r.stdout and "REPO=me/eval-x" in r.stdout
    r = _r("codeql-run", "--repo", "me/eval-x", "--ref", "exp/A/sample1")
    assert "--ref eval-ci -f ref=refs/heads/exp/A/sample1 -f sha=" in r.stdout and "RUN_ID=" in r.stdout
    r = _r("codeql-alerts", "--repo", "me/eval-x", "--ref", "refs/heads/exp/A/sample1", "--out", str(tmp_path / "o"))
    assert "code-scanning/alerts -f ref=refs/heads/exp/A/sample1" in r.stdout and (tmp_path / "o").is_dir()
    r = _r("archive", "--repo", "me/eval-x")
    assert "gh repo archive me/eval-x -y" in r.stdout


def test_private_warns_and_bad_args():
    r = _r("create", "--name", "x", "--dir", "/nonexistent/d", "--owner", "me", "--private")
    assert "WARNING" in r.stderr and "--private" in r.stdout
    assert _r("codeql-run").returncode == 2
    assert _r("bogus").returncode == 2
