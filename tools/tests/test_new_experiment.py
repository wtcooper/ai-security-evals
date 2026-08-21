"""new_experiment.sh: creates a legible, auditable experiment folder."""
import json
import os
import pathlib
import subprocess
import tempfile

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "new_experiment.sh"


def _run(skill, label, *, cwd, evals_dir, engine="promptfoo"):
    env = {**os.environ, "EVALS_DIR": str(evals_dir)}
    return subprocess.run(
        ["bash", str(SCRIPT), skill, label, engine],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def _skill_cwd(tmp):
    """A fake skill dir with a config + secret-bearing .env."""
    d = pathlib.Path(tmp) / "skill"
    d.mkdir()
    (d / "promptfooconfig.yaml").write_text("description: x\nproviders: []\n")
    (d / ".env").write_text(
        "TARGET_URL=https://api.acme.test/v1\n"
        "TARGET_API_KEY=sk-supersecret\n"
        "JUDGE_MODEL=gpt-4o-mini\n"
    )
    return d


def test_structure_and_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        evals = pathlib.Path(tmp) / ".evals"
        r = _run("app-eval", "Acme Prod: Cyber Smoke!", cwd=_skill_cwd(tmp), evals_dir=evals)
        assert r.returncode == 0, r.stderr
        exp = pathlib.Path([l for l in r.stdout.splitlines() if l.startswith("EXP=")][0][4:])
        # legible, label-first, date-stamped (no time), slugified
        assert exp.name.startswith("acme-prod-cyber-smoke_")
        assert exp.parent == evals / "app-eval"
        for sub in ("inputs", "results", "transcripts"):
            assert (exp / sub).is_dir()
        m = json.loads((exp / "manifest.json").read_text())
        assert m["skill"] == "app-eval" and m["engine"] == "promptfoo"
        assert m["label"] == "Acme Prod: Cyber Smoke!"
        assert m["host"] == "https://api.acme.test/v1"   # read from .env


def test_inputs_snapshotted_and_secrets_redacted():
    with tempfile.TemporaryDirectory() as tmp:
        evals = pathlib.Path(tmp) / ".evals"
        r = _run("control-isolate", "prisma-smoke", cwd=_skill_cwd(tmp), evals_dir=evals)
        exp = pathlib.Path([l for l in r.stdout.splitlines() if l.startswith("EXP=")][0][4:])
        assert (exp / "inputs" / "promptfooconfig.yaml").exists()
        env = (exp / "inputs" / "env.choices").read_text()
        assert "sk-supersecret" not in env and "***REDACTED***" in env  # key masked
        assert "https://api.acme.test/v1" in env                        # url kept
        assert "gpt-4o-mini" in env                                     # model kept


def test_same_day_rerun_dedupes():
    with tempfile.TemporaryDirectory() as tmp:
        evals = pathlib.Path(tmp) / ".evals"
        cwd = _skill_cwd(tmp)
        a = _run("app-eval", "dup", cwd=cwd, evals_dir=evals)
        b = _run("app-eval", "dup", cwd=cwd, evals_dir=evals)
        pa = [l for l in a.stdout.splitlines() if l.startswith("EXP=")][0][4:]
        pb = [l for l in b.stdout.splitlines() if l.startswith("EXP=")][0][4:]
        assert pa != pb and pb.endswith("-2")


def _run_args(args, *, cwd, evals_dir):
    env = {**os.environ, "EVALS_DIR": str(evals_dir)}
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True)


def _exp(r):
    assert r.returncode == 0, r.stderr
    return pathlib.Path([l for l in r.stdout.splitlines() if l.startswith("EXP=")][0][4:])


def test_git_branch_ab_engine_and_flags():
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "starting-state"], cwd=repo, check=True)
        (repo / "SPEC.md").write_text("spec\n")
        (repo / "build-prompt.md").write_text("build\n")
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "start"], cwd=repo, check=True)
        subprocess.run(["git", "tag", "starting-state-locked"], cwd=repo, check=True)
        evals = pathlib.Path(tmp) / ".evals"
        # $3 starting with -- => engine defaults per skill (control-codegen -> git-branch-ab)
        exp = _exp(_run_args(["control-codegen", "spec-01 A vs D", "--arms", "A,D", "--k", "10", "--spec", "spec-01",
                              "--tool", "claude-code@2.1", "--model", "claude-sonnet-5", "--temperature", "0"],
                             cwd=repo, evals_dir=evals))
        m = json.loads((exp / "manifest.json").read_text())
        assert m["schema_version"] == 2 and m["engine"] == "git-branch-ab"
        for sub in ("inputs", "results", "transcripts", "contamination", "arms", "probes", "branches"):
            assert (exp / sub).is_dir()
        assert (exp / "inputs" / "SPEC.md").exists() and (exp / "inputs" / "build-prompt.md").exists()
        assert [a["name"] for a in m["arms"]] == ["A", "D"] and m["arms"][1]["branch_glob"] == "exp/D/sample*"
        assert m["k"] == 10 and m["benchmark"]["spec"] == "spec-01"
        assert m["tool"] == {"name": "claude-code", "version": "2.1"}
        assert m["model"]["id"] == "claude-sonnet-5" and m["model"]["temperature"] == 0
        assert m["pair_on"] == ["target", "sample"]
        sha = subprocess.check_output(["git", "rev-parse", "starting-state"], cwd=repo, text=True).strip()
        assert m["starting_state"] == {"branch": "starting-state", "sha": sha, "tag_sha": sha}
        assert "k" not in m["_todo"] and "model.id" not in m["_todo"] and "scorers" in m["_todo"]


def test_tripwire_warning_when_starting_state_edited():
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        g = ["git", "-c", "user.email=a@b", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", "-b", "starting-state"], cwd=repo, check=True)
        (repo / "SPEC.md").write_text("spec\n")
        subprocess.run([*g, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*g, "commit", "-qm", "start"], cwd=repo, check=True)
        subprocess.run(["git", "tag", "starting-state-locked"], cwd=repo, check=True)
        (repo / "SPEC.md").write_text("edited\n")
        subprocess.run([*g, "commit", "-qam", "oops"], cwd=repo, check=True)
        r = _run_args(["control-codegen", "x", "git-branch-ab"], cwd=repo, evals_dir=pathlib.Path(tmp) / ".evals")
        assert r.returncode == 0 and "WARNING" in r.stderr and "starting-state-locked" in r.stderr


def test_default_engines_and_detection_bench():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = _skill_cwd(tmp)
        evals = pathlib.Path(tmp) / ".evals"
        m = json.loads((_exp(_run_args(["control-bench", "b"], cwd=cwd, evals_dir=evals)) / "manifest.json").read_text())
        assert m["engine"] == "inspect"
        exp = _exp(_run_args(["tool-codescan", "lcb", "--benchmark", "livecvebench@2026-08", "--arms", "codeql,scan-code"],
                             cwd=cwd, evals_dir=evals))
        m = json.loads((exp / "manifest.json").read_text())
        assert m["engine"] == "detection-bench" and (exp / "targets").is_dir()
        assert m["benchmark"] == {"name": "livecvebench", "version": "2026-08", "spec": None}
        assert "benchmark.name" not in m["_todo"]
