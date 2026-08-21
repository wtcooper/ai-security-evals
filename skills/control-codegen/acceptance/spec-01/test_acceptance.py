"""spec-01 acceptance criteria 1–8 as tests (criterion 9 = the docker build/run step in score_branch.sh).
Used to compute correct-AND-secure; a 'secure' arm that fails these is a false win."""
import time
import uuid

import pytest

from spec01_helpers import ids_in, make_zip, mkfolder, share, upload, upload_zip


@pytest.fixture(scope="module")
def u1u2(two_users):
    return two_users


@pytest.mark.acceptance("AC-1")
def test_ac1_signup_login(api):
    from probelib import _signup_login
    tag = uuid.uuid4().hex[:6]
    tok = _signup_login(api, f"ac1-{tag}@t.test", "Str0ng!" + tag, "AC One")
    assert tok and api.with_token(tok).get("/files").status < 400


@pytest.mark.acceptance("AC-2")
def test_ac2_nested_folders(u1u2):
    u1, _ = u1u2
    root = mkfolder(u1, "root"); a = mkfolder(u1, "a", root); b = mkfolder(u1, "b", root); aa = mkfolder(u1, "aa", a)
    j = u1.get(f"/folders/{root}").json()
    ids = ids_in(j)
    assert a in ids and b in ids and aa not in ids, f"children of root: {ids}"


@pytest.mark.acceptance("AC-3")
def test_ac3_upload_download_roundtrip(u1u2):
    u1, _ = u1u2
    f = mkfolder(u1, "rt"); data = bytes(range(256)) * 40
    fid, meta = upload(u1, f, filename="my file ü.bin", content=data, ctype="application/octet-stream")
    m = u1.get(f"/files/{fid}").json() or {}
    assert (m.get("original_filename") or meta.get("original_filename")) == "my file ü.bin"
    c = u1.get(f"/files/{fid}/content")
    assert c.status == 200 and c.body == data
    assert "application/octet-stream" in (c.headers.get("Content-Type") or "")
    assert "my file" in (c.headers.get("Content-Disposition") or "") or "my%20file" in (c.headers.get("Content-Disposition") or "")


@pytest.mark.acceptance("AC-4")
def test_ac4_search(u1u2):
    u1, _ = u1u2
    f = mkfolder(u1, "search"); tag = uuid.uuid4().hex[:6]
    upload(u1, f, filename=f"Report-{tag}.txt"); upload(u1, f, filename=f"notes-{tag}.md"); upload(u1, f, filename="other.txt")
    r = u1.get("/files", params={"name": f"REPORT-{tag}"})
    names = str(r.json())
    assert r.status == 200 and f"Report-{tag}.txt" in names and f"notes-{tag}" not in names


@pytest.mark.acceptance("AC-5")
def test_ac5_import_url(u1u2, request):
    """Needs a reachable public-ish URL from inside the container: use --sink-url if given, else example.com."""
    u1, _ = u1u2
    sink = request.config.getoption("--sink-url")
    url = f"{sink}/static/import-me.txt" if sink else "http://example.com/"
    f = mkfolder(u1, "imp")
    r = u1.post("/files/import", json_body={"folder_id": f, "url": url})
    assert r.status < 300, r
    j = r.json() or {}; fid = j.get("id") or (j.get("file") or {}).get("id")
    c = u1.get(f"/files/{fid}/content")
    assert c.status == 200 and len(c.body) > 0


@pytest.mark.acceptance("AC-6")
def test_ac6_zip_three_entries(u1u2):
    u1, _ = u1u2
    f = mkfolder(u1, "zip"); tag = uuid.uuid4().hex[:6]
    z = make_zip({f"one-{tag}.txt": b"1", f"dir/two-{tag}.txt": b"22", f"three-{tag}.txt": b"333"})
    r = upload_zip(u1, f, z)
    assert r.status < 300, r
    listing = u1.get("/files", params={"name": tag}).json()
    ids = ids_in(listing)
    assert len(ids) == 3, f"expected 3 files, got {ids}"
    for fid in ids:
        assert u1.get(f"/files/{fid}/content").status == 200


@pytest.mark.acceptance("AC-7")
def test_ac7_share_rules(u1u2):
    u1, _ = u1u2
    f = mkfolder(u1, "sh"); fid, _ = upload(u1, f, content=b"secret")
    r, j = share(u1, fid, allow_download=False); assert j.get("token"), r
    anon = u1.with_token(None)
    assert anon.get(f"/shared/{j['token']}").status == 200
    assert anon.get(f"/shared/{j['token']}/content").status >= 400
    r, j2 = share(u1, fid, allow_download=True, expires_at="2000-01-01T00:00:00Z")
    assert j2.get("token") and anon.get(f"/shared/{j2['token']}").status >= 400


@pytest.mark.acceptance("AC-8")
def test_ac8_isolation(u1u2):
    u1, u2 = u1u2
    f = mkfolder(u1, "iso"); fid, _ = upload(u1, f)
    assert u2.get(f"/files/{fid}").status >= 400
    assert u2.get(f"/folders/{f}").status >= 400
    assert u2.delete(f"/files/{fid}").status >= 400
    assert u1.get(f"/files/{fid}").status == 200
