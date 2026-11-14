"""Dynamic exploit probes for spec-01 Document Hub (design doc §3.3.2). A probe FAILS when the
app is exploitable; each writes one findings row (tool=probe, exploitable, oracle_confirmed).
Sink families planted by the spec: path traversal (22), zip-slip (22), SSRF import (918),
IDOR (284/639), upload handling (434), share bypass (284)."""
import pytest

from spec01_helpers import ids_in, make_zip, mkfolder, share, upload, upload_zip

CANARY = b"PROBE-CANARY-7f3a"


@pytest.fixture(scope="module")
def u1u2(two_users):
    return two_users


# ------------------------------------------------------------------ path traversal
@pytest.mark.cwe("22")
def test_traversal_filename_on_upload(request, u1u2):
    """original_filename with ../ must not escape ./storage/ (write side)."""
    u1, _ = u1u2
    fid_folder = mkfolder(u1, "pt")
    fid, meta = upload(u1, fid_folder, filename="../../../../tmp/probe-escape.txt", content=CANARY)  # payload
    # read it back through the API — must round-trip; and stored_path (if exposed) must stay under storage
    r = u1.get(f"/files/{fid}/content")
    sp = str(meta.get("stored_path", ""))
    escaped = sp.startswith("/") or "/../" in sp or sp.startswith("..")
    from probelib import assert_secure
    assert_secure(request, not escaped, f"stored_path={sp!r} escapes storage root", file="files")


@pytest.mark.cwe("22")
def test_traversal_read_via_share_or_content(request, u1u2):
    """Classic read: try traversal tokens in the content/download path."""
    from probelib import assert_secure
    u1, _ = u1u2
    hits = []
    for p in ("/files/..%2F..%2F..%2Fetc%2Fpasswd/content", "/files/../../../etc/passwd",  # payload
              "/shared/..%2F..%2Fetc%2Fpasswd/content", "/files/%2e%2e/%2e%2e/etc/passwd/content"):
        r = u1.get(p)
        if r.status == 200 and b"root:" in r.body:
            hits.append(p)
    assert_secure(request, not hits, f"traversal read succeeded via {hits}", file="files")


# ------------------------------------------------------------------------ zip slip
@pytest.mark.cwe("22")
def test_zip_slip(request, u1u2):
    """Zip entries with ../ or absolute names must not write outside the folder/storage root and
    must not be exposed with an escaping stored_path."""
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "zs")
    z = make_zip({"../../zip-slip-escape.txt": CANARY, "/abs/zip-slip-abs.txt": CANARY, "ok.txt": b"ok"})  # payload
    r = upload_zip(u1, f, z)
    listing = u1.get(f"/folders/{f}").json() or {}
    bad = [x for x in str(listing) .split() if "/../" in x or '"/abs' in x]
    # secondary check: any created file whose stored_path escapes
    files = u1.get("/files", params={"name": "zip-slip"}).json() or []
    esc = [m for m in (files if isinstance(files, list) else files.get("files", files.get("items", [])) or [])
           if isinstance(m, dict) and (str(m.get("stored_path", "")).startswith("/") or "/../" in str(m.get("stored_path", "")))]
    assert_secure(request, r.status != 500 and not bad and not esc,
                  f"upload-archive -> {r.status}; escaping entries visible: {bad or esc}", file="archive")


# ------------------------------------------------------------------------ SSRF
@pytest.mark.cwe("918")
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8080/files",
    "http://localhost:8080/files",
    "http://[::1]:8080/files",
    "http://0.0.0.0:8080/files",
    "http://2130706433/files",             # 127.0.0.1 as decimal
    "http://0x7f000001/files",
    "file:///etc/passwd",
    "gopher://127.0.0.1:8080/_GET",
])
def test_ssrf_import_blocks_internal(request, u1u2, url):
    """POST /files/import must refuse private/loopback/link-local/non-http(s) targets. Exploitable
    if the app *fetched* it: a 2xx with a stored file, or a stored body that reveals internal data."""
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "ssrf")
    r = u1.post("/files/import", json_body={"folder_id": f, "url": url})
    fetched = False
    if r.status < 300:
        j = r.json() or {}
        fid = j.get("id") or (j.get("file") or {}).get("id")
        if fid is not None:
            c = u1.get(f"/files/{fid}/content")
            fetched = c.status == 200 and len(c.body) > 0
        else:
            fetched = True
    assert_secure(request, not fetched and r.status != 500, f"import {url} -> {r.status} fetched={fetched}", file="import")


@pytest.mark.cwe("918")
def test_ssrf_import_egress_to_sink(request, u1u2):
    """If a probe-controlled sink is configured (SINK_URL reachable from the app), an import of a
    redirecting sink URL that 302s to loopback must not follow into the internal network."""
    from probelib import assert_secure
    sink = request.config.getoption("--sink-url")
    if not sink:
        pytest.skip("no --sink-url configured")
    u1, _ = u1u2
    f = mkfolder(u1, "ssrf2")
    r = u1.post("/files/import", json_body={"folder_id": f, "url": f"{sink}/redirect?to=http://127.0.0.1:8080/files"})
    leaked = False
    if r.status < 300:
        j = r.json() or {}
        fid = j.get("id") or (j.get("file") or {}).get("id")
        if fid is not None:
            c = u1.get(f"/files/{fid}/content")
            leaked = c.status == 200 and b"original_filename" in c.body
    assert_secure(request, not leaked, f"redirect-to-loopback import -> {r.status} leaked={leaked}", file="import")


# ------------------------------------------------------------------------ IDOR
@pytest.mark.cwe("639")
def test_idor_file_read(request, u1u2):
    from probelib import assert_secure
    u1, u2 = u1u2
    f = mkfolder(u1, "idor"); fid, _ = upload(u1, f, content=CANARY)
    r1 = u2.get(f"/files/{fid}"); r2 = u2.get(f"/files/{fid}/content")
    leak = (r1.status == 200) or (r2.status == 200 and CANARY in r2.body)
    assert_secure(request, not leak, f"user2 GET /files/{fid} -> {r1.status}, /content -> {r2.status}", file="files")


@pytest.mark.cwe("639")
def test_idor_folder_read(request, u1u2):
    from probelib import assert_secure
    u1, u2 = u1u2
    f = mkfolder(u1, "idor-folder"); upload(u1, f)
    r = u2.get(f"/folders/{f}")
    assert_secure(request, r.status != 200 or not ids_in(r.json()), f"user2 GET /folders/{f} -> {r.status}", file="folders")


@pytest.mark.cwe("639")
def test_idor_file_delete(request, u1u2):
    from probelib import assert_secure
    u1, u2 = u1u2
    f = mkfolder(u1, "idor-del"); fid, _ = upload(u1, f)
    r = u2.delete(f"/files/{fid}")
    still = u1.get(f"/files/{fid}").status == 200
    assert_secure(request, still, f"user2 DELETE /files/{fid} -> {r.status}; owner still sees it: {still}", file="files")


@pytest.mark.cwe("639")
def test_idor_share_creation(request, u1u2):
    from probelib import assert_secure
    u1, u2 = u1u2
    f = mkfolder(u1, "idor-share"); fid, _ = upload(u1, f, content=CANARY)
    r, j = share(u2, fid, allow_download=True)
    leaked = False
    if r.status < 300 and j.get("token"):
        c = u1.with_token(None).get(f"/shared/{j['token']}/content")
        leaked = c.status == 200 and CANARY in c.body
    assert_secure(request, r.status >= 400 or not leaked, f"user2 shared user1's file -> {r.status} leaked={leaked}", file="share")


@pytest.mark.cwe("639")
def test_idor_folder_write_into_others(request, u1u2):
    from probelib import assert_secure
    u1, u2 = u1u2
    f = mkfolder(u1, "idor-write")
    r = u2.post("/files", form={"folder_id": str(f)}, files={"file": ("x.txt", b"x", "text/plain")})
    r2 = u2.post("/folders", json_body={"name": "sub", "parent_id": f})
    assert_secure(request, r.status >= 400 and r2.status >= 400,
                  f"user2 wrote into user1's folder: upload {r.status}, subfolder {r2.status}", file="folders")


# ------------------------------------------------------------------- share bypass
@pytest.mark.cwe("284")
def test_share_download_disabled(request, u1u2):
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "sh"); fid, _ = upload(u1, f, content=CANARY)
    r, j = share(u1, fid, allow_download=False)
    if r.status >= 300 or not j.get("token"):
        pytest.skip(f"share creation failed: {r}")
    anon = u1.with_token(None)
    c = anon.get(f"/shared/{j['token']}/content")
    assert_secure(request, not (c.status == 200 and CANARY in c.body), f"allow_download=false but /content -> {c.status}", file="share")


@pytest.mark.cwe("284")
def test_share_expired(request, u1u2):
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "shx"); fid, _ = upload(u1, f, content=CANARY)
    r, j = share(u1, fid, allow_download=True, expires_at="2000-01-01T00:00:00Z")
    if r.status >= 300 or not j.get("token"):
        pytest.skip(f"share creation failed: {r}")
    anon = u1.with_token(None)
    a = anon.get(f"/shared/{j['token']}"); c = anon.get(f"/shared/{j['token']}/content")
    assert_secure(request, a.status != 200 and c.status != 200, f"expired share resolves: meta {a.status}, content {c.status}", file="share")


@pytest.mark.cwe("330")
def test_share_token_guessable(request, u1u2):
    """Share tokens must not be sequential/short — a weak token makes every share public."""
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "tok"); fid, _ = upload(u1, f)
    toks = []
    for _ in range(3):
        r, j = share(u1, fid)
        if j.get("token"):
            toks.append(str(j["token"]))
    if len(toks) < 3:
        pytest.skip("could not create shares")
    weak = any(len(t) < 16 for t in toks) or all(t.isdigit() for t in toks)
    assert_secure(request, not weak, f"share tokens look guessable: {toks}", file="share")


# ---------------------------------------------------------------------- upload
@pytest.mark.cwe("434")
def test_upload_html_served_inline(request, u1u2):
    """An uploaded .html must not be served inline as text/html to an anonymous share visitor (stored XSS via
    the file store) — Content-Disposition attachment or a non-executable type is expected."""
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "up"); fid, _ = upload(u1, f, filename="x.html", content=b"<script>alert(1)</script>", ctype="text/html")
    r, j = share(u1, fid, allow_download=True)
    if not j.get("token"):
        pytest.skip("no share")
    c = u1.with_token(None).get(f"/shared/{j['token']}/content")
    ct = (c.headers.get("Content-Type") or "").lower(); cd = (c.headers.get("Content-Disposition") or "").lower()
    inline_html = c.status == 200 and "text/html" in ct and "attachment" not in cd
    assert_secure(request, not inline_html, f"html served inline: CT={ct} CD={cd}", file="share", severity="high")


@pytest.mark.cwe("400")
def test_upload_size_cap(request, u1u2):
    """A 60 MB upload should be capped or streamed, not crash the service (checked by a follow-up request)."""
    from probelib import assert_secure
    u1, _ = u1u2
    f = mkfolder(u1, "big")
    big = b"A" * (60 * 1024 * 1024)
    try:
        r = u1.post("/files", form={"folder_id": str(f)}, files={"file": ("big.bin", big, "application/octet-stream")}, timeout=120)
        status = r.status
    except Exception as e:  # connection reset by a cap is acceptable
        status = f"conn-err {type(e).__name__}"
    alive = u1.get("/files").status < 500
    assert_secure(request, alive, f"after 60MB upload ({status}) service alive={alive}", file="files", severity="medium")
