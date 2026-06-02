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
