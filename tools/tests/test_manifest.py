"""manifest.py: dotted-path edits on manifest.json + samples.jsonl upsert."""
import json
import pathlib
import subprocess
import sys

M = pathlib.Path(__file__).resolve().parent.parent / "lib" / "manifest.py"


def _m(exp, *args):
    r = subprocess.run([sys.executable, str(M), str(exp), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_set_add_append_todo(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"model": {"id": None}, "cost": {"usd": 0}, "_todo": ["model.id", "k", "scorers"]}))
    _m(tmp_path, "set", "model.id", "claude-sonnet-5")
    _m(tmp_path, "set", "k", "10")
    _m(tmp_path, "add", "cost.usd", "1.25")
    _m(tmp_path, "add", "cost.usd", "0.75")
    _m(tmp_path, "append", "scorers", '{"name":"codeql","repeats":1}')
    _m(tmp_path, "set", "repo.archived", "true")
    d = json.loads((tmp_path / "manifest.json").read_text())
    assert d["model"]["id"] == "claude-sonnet-5" and d["k"] == 10
    assert d["cost"]["usd"] == 2.0 and d["scorers"] == [{"name": "codeql", "repeats": 1}]
    assert d["repo"] == {"archived": True} and d["_todo"] == []
    assert _m(tmp_path, "get", "model.id") == "claude-sonnet-5"
    assert _m(tmp_path, "get", "k") == "10"


def test_append_sample_upserts(tmp_path):
    (tmp_path / "manifest.json").write_text("{}")
    _m(tmp_path, "append-sample", '{"arm":"A","target":"spec-01","sample":1,"build_ok":true,"cost_usd":1.0}')
    _m(tmp_path, "append-sample", '{"arm":"A","target":"spec-01","sample":2,"build_ok":false}')
    _m(tmp_path, "append-sample", '{"arm":"A","target":"spec-01","sample":1,"acceptance_pass":true}')
    rows = [json.loads(l) for l in (tmp_path / "samples.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0] == {"arm": "A", "target": "spec-01", "sample": 1, "build_ok": True, "cost_usd": 1.0, "acceptance_pass": True}
