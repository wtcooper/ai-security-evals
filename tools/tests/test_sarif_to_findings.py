"""sarif_to_findings.py + cwe_map.py: normalise scanner output into findings.jsonl rows."""
import json
import pathlib
import subprocess
import sys

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"
FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(LIB))
import cwe_map  # noqa: E402
import sarif_to_findings as s2f  # noqa: E402

CTX = dict(run="exp", arm="A", target="spec-01", sample=1, spec="spec-01", tool="x", tool_run=1)


def test_family_of():
    assert cwe_map.family_of("639") == "284"
    assert cwe_map.family_of("CWE-023") == "22"
    assert cwe_map.family_of(787) == "119"
    assert cwe_map.family_of("918") == "918"          # identity
    assert cwe_map.family_of(None) == "uncwe"
    assert cwe_map.family_of("nope") == "uncwe"


def test_cwe_from_text():
    assert cwe_map.cwe_from_text("see CWE-078 details") == "78"
    assert cwe_map.cwe_from_text("Path traversal in download") == "22"
    assert cwe_map.cwe_from_text("URL import allows SSRF to metadata") == "918"
    assert cwe_map.cwe_from_text("IDOR on /files/{id}") == "284"
    assert cwe_map.cwe_from_text("Zip slip during archive expansion") == "22"
    assert cwe_map.cwe_from_text("mass assignment of price") == "915"
    assert cwe_map.cwe_from_text("totally benign") is None


def test_codeql_sarif():
    rows = s2f.convert(FIX / "codeql.sarif", "sarif", {**CTX, "tool": "codeql"})
    assert [r["cwe"] for r in rows] == ["22", "78", "312"]
    assert [r["cwe_family"] for r in rows] == ["22", "78", "312"]
    assert [r["severity"] for r in rows] == ["high", "critical", "high"]
    assert rows[0]["file"] == "app/files.py" and rows[0]["line"] == 42
    assert set(rows[0]) == set(s2f.FIELDS)
    assert rows[0]["arm"] == "A" and rows[0]["tool"] == "codeql"


def test_semgrep_sarif_strip_prefix():
    rows = s2f.convert(FIX / "semgrep.sarif", "sarif", {**CTX, "tool": "semgrep"}, strip_prefix="/tmp/wt")
    assert [r["cwe"] for r in rows] == ["78", "798"]
    assert rows[0]["file"] == "app/run.py"
    assert rows[0]["severity"] == "medium"          # from SARIF level


def test_scancode_sarif_free_text():
    rows = s2f.convert(FIX / "scancode.sarif", "sarif", {**CTX, "tool": "scan-code", "tool_run": 2})
    assert [r["cwe"] for r in rows] == ["22", "918", "uncwe"]
    assert [r["severity"] for r in rows] == ["critical", "high", "low"]
    assert rows[0]["confidence"] == "high" and rows[0]["tool_run"] == 2


def test_gh_alerts_skips_dismissed():
    rows = s2f.convert(FIX / "gh_alerts.json", "gh-alerts", {**CTX, "tool": "codeql"})
    assert len(rows) == 2
    assert [r["cwe"] for r in rows] == ["22", "918"]
    assert [r["severity"] for r in rows] == ["high", "critical"]
    assert rows[1]["file"] == "src/import.js" and rows[1]["line"] == 8


def test_cli_append(tmp_path):
    out = tmp_path / "findings.jsonl"
    for i in (1, 2):
        r = subprocess.run([sys.executable, str(LIB / "sarif_to_findings.py"), str(FIX / "codeql.sarif"),
                            "--tool", "codeql", "--run", "e", "--arm", "A", "--target", "spec-01",
                            "--sample", str(i), "--append", str(out)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 6 and {r["sample"] for r in rows} == {1, 2}
