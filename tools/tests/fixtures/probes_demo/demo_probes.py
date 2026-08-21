import pytest
from probelib import assert_secure


@pytest.mark.cwe("22")
def test_traversal(request, api):
    r = api.get("/files/../../etc/passwd")
    assert_secure(request, "root:" not in r.text, f"GET ../../etc/passwd -> {r.status}", file="app/files.py")


@pytest.mark.cwe("918")
def test_ssrf(request, api):
    r = api.get("/import", params={"url": "http://169.254.169.254/"})
    assert_secure(request, r.status >= 400, f"import metadata url -> {r.status}")


@pytest.mark.acceptance("AC-1")
def test_health(api):
    assert api.get("/health").status == 200


@pytest.mark.acceptance("AC-2")
def test_missing(api):
    assert api.get("/nope").status == 200
