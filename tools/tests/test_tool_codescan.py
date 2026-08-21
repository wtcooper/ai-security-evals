"""tool-codescan: match.py ground-truth matching + mutate.py rename map round-trip."""
import json
import pathlib
import subprocess
import sys

SK = pathlib.Path(__file__).resolve().parents[2] / "skills" / "tool-codescan"


def test_match_levels_and_report(tmp_path):
    gt = [{"target": "T1", "id": "g1", "cwe": "22", "file": "app/files.py", "function": "download", "line": 40},
          {"target": "T1", "id": "g2", "cwe": "89", "file": "app/db.py"},
          {"target": "T2", "id": "g3", "cwe": "918", "file": "src/import.js", "line": 10}]
    F = [{"target": "T1", "tool": "codeql", "cwe": "23", "cwe_family": "22", "file": "app/files.py", "line": 43, "message": "x"},   # line match (family 23->22)
         {"target": "T1", "tool": "scan-code", "cwe": "22", "cwe_family": "22", "file": "app/files.py", "line": 200, "message": "in download()"},  # function match
         {"target": "T1", "tool": "scan-code", "cwe": "89", "cwe_family": "89", "file": "/tmp/x/app/db.py", "line": 5, "message": ""},  # file match
         {"target": "T2", "tool": "codeql", "cwe": "79", "cwe_family": "79", "file": "src/import.js", "line": 10, "message": ""},  # wrong family -> FP
         {"target": "T2", "tool": "scan-code", "cwe": "918", "cwe_family": "918", "file": "src/other.js", "line": 10, "message": ""}]  # wrong file -> FP
    fp, gp = tmp_path / "f.jsonl", tmp_path / "g.jsonl"
    fp.write_text("".join(json.dumps(r) + "\n" for r in F)); gp.write_text("".join(json.dumps(r) + "\n" for r in gt))
    r = subprocess.run([sys.executable, str(SK / "match.py"), str(fp), str(gp), "--out", str(tmp_path / "m.jsonl"),
                        "--report", str(tmp_path / "m.md"), "--adjudicate", str(tmp_path / "adj.csv"), "--group-by", "tool"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in (tmp_path / "m.jsonl").read_text().splitlines()]
    assert [x["matched"] for x in rows] == ["line", "function", "file", None, None]
    assert [x["ground_truth_id"] for x in rows] == ["g1", "g1", "g2", None, None]
    J = json.loads(r.stderr[r.stderr.index("{"):])
    assert J["codeql"]["tp"] == 1 and J["codeql"]["fp_lower_bound"] == 1
    assert abs(J["scan-code"]["recall_file"] - 2 / 3) < 1e-9 and abs(J["scan-code"]["recall_line"] - 0.0) < 1e-9
    md = (tmp_path / "m.md").read_text()
    assert "Complement" in md and "**union**: 2 / 3" in md
    assert (tmp_path / "adj.csv").read_text().count("\n") == 3   # header + 2 unmatched


def test_mutate_roundtrip(tmp_path):
    src = tmp_path / "src"; (src / "app").mkdir(parents=True)
    (src / "app" / "files.py").write_text('def download_file(name):\n    return open(name)\n\n@app.get("/files/{id}")\ndef list_files():\n    return download_file("x")\n')
    (src / "README.md").write_text("Call download_file via /files.\n")
    r = subprocess.run([sys.executable, str(SK / "mutate.py"), str(src), str(tmp_path / "dst"), "--map", str(tmp_path / "map.json"), "--seed", "1"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp_path / "map.json").read_text())["identifiers"]
    assert "download_file" in m and "list_files" in m and "/files" in m
    out = (tmp_path / "dst" / "app" / "files.py").read_text()
    assert "download_file" not in out and m["download_file"] in out and m["/files"] in out
    gt = tmp_path / "gt.jsonl"; gt.write_text(json.dumps({"target": "t", "id": "1", "cwe": "22", "file": "app/files.py", "function": "download_file"}) + "\n")
    r = subprocess.run([sys.executable, str(SK / "translate_gt.py"), str(gt), str(tmp_path / "map.json")], capture_output=True, text=True)
    assert json.loads(r.stdout)["function"] == m["download_file"]
