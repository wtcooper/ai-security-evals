import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lib"))
import status_policy as sp

k = lambda status, body=None, text="": sp.classify(status, body if body is not None else {}, text)["kind"]


def test_answers():
    assert k(200, {"choices": [{"message": {"content": "hi"}}]}) == "answer"
    assert k(None, {"output": "x"}) == "answer"


def test_block_via_body_signal():
    assert k(200, {"action": "block"}) == "block"
    assert k(403, {"error": {"message": "Content blocked",
                             "provider_specific_fields": {"guardrail_name": "content-filter"}}}) == "block"
    assert k(403, {"error": {"message": "Content blocked: keyword"}}) == "block"
    assert k(422, {"blocked": True}) == "block"
    assert k(200, {"guardrails": {"flagged": True}}) == "block"


def test_block_via_status_hint():
    assert k(400, {}, "nope") == "block"


def test_operational_errors():
    for s in (500, 502, 503, 429, 408, 401, 407):
        assert k(s, {}) == "error", s
    assert k(403, {"error": {"message": "invalid api key"}}) == "error"


def test_ambiguous():
    assert k(403, {}, "Forbidden") == "ambiguous"
    assert k(451, {}) == "ambiguous"


def test_block_status_override(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_BLOCK_STATUSES", "400,451")
    assert k(451, {}) == "block"
    assert k(403, {}) == "ambiguous"


def test_field_override(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_BLOCK_FIELD", "result.verdict")
    monkeypatch.setenv("GUARDRAIL_BLOCK_VALUE", "unsafe")
    assert k(200, {"result": {"verdict": "unsafe"}}) == "block"
    assert k(200, {"result": {"verdict": "safe"}}) == "answer"


def test_reason_and_status_carried():
    c = sp.classify(403, {"error": {"message": "Content blocked: bomb"}}, "")
    assert "Content blocked" in c["reason"] and c["http_status"] == 403
