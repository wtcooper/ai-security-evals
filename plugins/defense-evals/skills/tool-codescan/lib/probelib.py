#!/usr/bin/env python3
"""pytest helpers for dynamic exploit probes and acceptance suites (design doc §3.3.2 / §3.3.4).

Load from a probes/ or acceptance/ directory's conftest.py:

    from probelib import *          # registers --base-url/--findings-out options + fixtures

Probe convention: a probe test **fails when the app is exploitable**. Decorate with
`@pytest.mark.cwe("22")` and call `mark(exploitable=True, evidence=...)` (or `assert_secure(cond,
evidence)`) so one findings.jsonl row per probe is written with `tool="probe"`,
`exploitable`, `oracle_confirmed`. Acceptance tests use `@pytest.mark.acceptance("AC-3")` — the
plugin writes a per-criterion pass/fail row to --acceptance-out.

    pytest probes/spec-01 --base-url http://localhost:18080 --findings-out results/A/sample1/probes.jsonl \
        --ctx '{"run":"e","arm":"A","target":"spec-01","sample":1}'
    pytest acceptance/spec-01 --base-url ... --acceptance-out results/A/sample1/acceptance.jsonl

Uses only stdlib (urllib) so it runs anywhere pytest does.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import pytest

__all__ = ["pytest_addoption", "pytest_configure", "pytest_runtest_makereport", "base_url", "api", "ctx",
           "two_users", "mark", "assert_secure", "Api", "Resp", "wait_for_http", "poll"]

_STATE: dict = {"marks": {}}


# ---------------------------------------------------------------- pytest hooks
def pytest_addoption(parser):
    g = parser.getgroup("probes")
    g.addoption("--base-url", default=os.environ.get("BASE_URL", "http://localhost:18080"))
    g.addoption("--findings-out", default=None, help="findings.jsonl to append probe rows to")
    g.addoption("--acceptance-out", default=None, help="jsonl to append acceptance rows to")
    g.addoption("--ctx", default="{}", help='JSON with run/arm/target/sample/spec for the rows')
    g.addoption("--sink-url", default=os.environ.get("SINK_URL", ""),
                help="probe-controlled HTTP sink reachable from the app (for SSRF egress checks)")


def pytest_configure(config):
    config.addinivalue_line("markers", "cwe(id): CWE id the probe exercises")
    config.addinivalue_line("markers", "acceptance(id): acceptance criterion id")
    _STATE["ctx"] = json.loads(config.getoption("--ctx") or "{}")
    _STATE["findings_out"] = config.getoption("--findings-out")
    _STATE["acceptance_out"] = config.getoption("--acceptance-out")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call":
        return
    ctx = _STATE.get("ctx", {})
    cwe = item.get_closest_marker("cwe")
    acc = item.get_closest_marker("acceptance")
    if cwe is not None and _STATE.get("findings_out"):
        info = _STATE["marks"].get(item.nodeid, {})
        exploitable = bool(info.get("exploitable", rep.failed))     # failing probe == exploitable
        row = {"run": ctx.get("run"), "arm": ctx.get("arm"), "target": ctx.get("target"),
               "sample": ctx.get("sample"), "spec": ctx.get("spec", ctx.get("target")),
               "tool": "probe", "tool_run": 1, "rule_id": item.name, "cwe": str(cwe.args[0]),
               "cwe_family": _family(str(cwe.args[0])), "file": info.get("file"), "line": None,
               "severity": info.get("severity", "critical" if exploitable else "info"),
               "confidence": "oracle", "oracle_confirmed": exploitable, "exploitable": exploitable,
               "ground_truth_id": None, "matched": None,
               "message": (info.get("evidence") or (str(rep.longrepr)[:300] if rep.failed else "not exploitable"))[:500],
               "outcome": rep.outcome}
        if exploitable or os.environ.get("PROBE_KEEP_NEGATIVES"):
            _append(_STATE["findings_out"], row)
        else:
            _append(_STATE["findings_out"] + ".negatives", row)   # audit trail: probes that ran clean
    if acc is not None and _STATE.get("acceptance_out"):
        _append(_STATE["acceptance_out"], {"run": ctx.get("run"), "arm": ctx.get("arm"), "target": ctx.get("target"),
                                           "sample": ctx.get("sample"), "criterion": str(acc.args[0]),
                                           "test": item.name, "passed": rep.passed,
                                           "detail": (str(rep.longrepr)[:300] if rep.failed else "")})


def _family(cwe: str) -> str:
    try:
        from cwe_map import family_of
        return family_of(cwe)
    except Exception:
        return cwe


def _append(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row) + "\n")


# --------------------------------------------------------------- HTTP client
class Resp:
    def __init__(self, status: int, headers, body: bytes, url: str):
        self.status, self.headers, self.body, self.url = status, headers, body, url

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.body or b"null")
        except json.JSONDecodeError:
            return None

    def __repr__(self):
        return f"<Resp {self.status} {self.url} {self.text[:120]!r}>"


class Api:
    """Minimal HTTP client: json/form/multipart/raw, bearer token, no redirects by default."""

    def __init__(self, base: str, token: str | None = None, follow_redirects: bool = False):
        self.base, self.token = base.rstrip("/"), token
        self.follow = follow_redirects
        self.jar = http.cookiejar.CookieJar()

    def with_token(self, token: str | None) -> "Api":
        return Api(self.base, token, self.follow)

    def request(self, method: str, path: str, *, json_body=None, data: bytes | None = None,
                headers: dict | None = None, form: dict | None = None,
                files: dict | None = None, params: dict | None = None, timeout: int = 20) -> Resp:
        url = path if path.startswith("http") else self.base + (path if path.startswith("/") else "/" + path)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        h = {"Accept": "application/json, */*"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(headers or {})
        body = data
        if json_body is not None:
            body = json.dumps(json_body).encode()
            h.setdefault("Content-Type", "application/json")
        elif files is not None:
            boundary = "----probe" + uuid.uuid4().hex
            parts = []
            for k, v in (form or {}).items():
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            for k, (fname, content, ctype) in files.items():
                parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\n"
                             f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif form is not None:
            body = urllib.parse.urlencode(form).encode()
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        handlers = [urllib.request.HTTPCookieProcessor(self.jar)]
        if not self.follow:
            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            handlers.append(_NoRedirect())
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(req, timeout=timeout) as r:
                return Resp(r.status, r.headers, r.read(), url)
        except urllib.error.HTTPError as e:
            return Resp(e.code, e.headers, e.read() if e.fp else b"", url)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def wait_for_http(url: str, timeout: float = 60.0, ok=lambda s: s < 500) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if ok(r.status):
                    return True
        except urllib.error.HTTPError as e:
            if ok(e.code):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def poll(fn, timeout: float = 15.0, every: float = 0.5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


# ------------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def base_url(request):
    return request.config.getoption("--base-url")


@pytest.fixture(scope="session")
def ctx(request):
    return _STATE.get("ctx", {})


@pytest.fixture(scope="session")
def api(base_url):
    return Api(base_url)


def _signup_login(api: Api, email: str, password: str, display_name: str) -> str:
    """Try the common shapes the specs allow; return a bearer token."""
    api.post("/auth/signup", json_body={"email": email, "password": password, "display_name": display_name})
    api.post("/auth/register", json_body={"email": email, "password": password, "display_name": display_name})
    api.post("/signup", json_body={"email": email, "password": password, "display_name": display_name})
    for path in ("/auth/login", "/login", "/auth/token"):
        r = api.post(path, json_body={"email": email, "password": password})
        if r.status < 300 and r.json():
            j = r.json()
            tok = j.get("token") or j.get("access_token") or j.get("session_token") or (j.get("data") or {}).get("token")
            if tok:
                return tok
        r = api.post(path, form={"username": email, "password": password})
        if r.status < 300 and r.json():
            j = r.json()
            tok = j.get("token") or j.get("access_token")
            if tok:
                return tok
    raise RuntimeError(f"could not obtain a token for {email} via /auth/login|/login|/auth/token")


@pytest.fixture(scope="session")
def two_users(api):
    """Two authenticated clients (u1, u2) — the IDOR pair. Adapt _signup_login if the app's auth
    routes differ; the spec fixes only 'session tokens (bearer) issued at login'."""
    tag = uuid.uuid4().hex[:8]
    t1 = _signup_login(api, f"u1-{tag}@probe.test", "Str0ngPass!" + tag, "User One")
    t2 = _signup_login(api, f"u2-{tag}@probe.test", "Str0ngPass!" + tag, "User Two")
    return api.with_token(t1), api.with_token(t2)


# --------------------------------------------------------------- probe helpers
def mark(request_or_item, *, exploitable: bool, evidence: str = "", file: str | None = None,
         severity: str | None = None) -> None:
    """Record probe outcome for the findings row (call before asserting)."""
    item = getattr(request_or_item, "node", request_or_item)
    _STATE["marks"][item.nodeid] = {"exploitable": exploitable, "evidence": evidence, "file": file,
                                    **({"severity": severity} if severity else {})}


def assert_secure(request, condition: bool, evidence: str = "", **kw) -> None:
    """Probe passes when `condition` (== app behaved securely) holds; else marks exploitable and fails."""
    mark(request, exploitable=not condition, evidence=evidence, **kw)
    assert condition, f"EXPLOITABLE: {evidence}"
