"""probelib.py: probe/acceptance rows written from a pytest run against a tiny fake app."""
import json
import pathlib
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

DEMO = pathlib.Path(__file__).resolve().parent / "fixtures" / "probes_demo"


class _App(BaseHTTPRequestHandler):
    def do_GET(self):
        p = self.path
        if p.startswith("/files/") and "etc/passwd" in p:
            body, code = b"root:x:0:0", 200                       # vulnerable: traversal works
        elif p.startswith("/import"):
            body, code = b"blocked", 400                          # secure: SSRF blocked
        elif p == "/health":
            body, code = b"ok", 200
        else:
            body, code = b"nf", 404
        self.send_response(code); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_rows(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        fo, ao = tmp_path / "probes.jsonl", tmp_path / "acc.jsonl"
        r = subprocess.run([sys.executable, "-m", "pytest", str(DEMO / "demo_probes.py"), "-q", "-p", "no:cacheprovider",
                            "--base-url", f"http://127.0.0.1:{srv.server_port}",
                            "--findings-out", str(fo), "--acceptance-out", str(ao),
                            "--ctx", json.dumps({"run": "e", "arm": "A", "target": "spec-01", "sample": 1})],
                           capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode != 0                                   # one probe + one acceptance failed
        rows = [json.loads(l) for l in fo.read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["cwe"] == "22" and rows[0]["exploitable"] is True
        assert rows[0]["tool"] == "probe" and rows[0]["oracle_confirmed"] is True and rows[0]["file"] == "app/files.py"
        assert rows[0]["arm"] == "A" and rows[0]["sample"] == 1 and rows[0]["severity"] == "critical"
        neg = [json.loads(l) for l in (tmp_path / "probes.jsonl.negatives").read_text().splitlines()]
        assert len(neg) == 1 and neg[0]["cwe"] == "918" and neg[0]["exploitable"] is False
        acc = {a["criterion"]: a["passed"] for a in map(json.loads, ao.read_text().splitlines())}
        assert acc == {"AC-1": True, "AC-2": False}
    finally:
        srv.shutdown()
