"""Shim behavior: param injection over the wire + block→refusal conversion."""
import sys, pathlib, json, threading, urllib.request, time
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "_shared" / "tests"))

import mock_server  # noqa: E402
import injection_shim as shim  # noqa: E402
from connectors.base import Arm  # noqa: E402
from connectors.litellm import LiteLLMConnector  # noqa: E402


def _serve(handler, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.getcode(), json.loads(r.read())


def test_shim_injects_guardrail_over_the_wire():
    gw = _serve(mock_server.Handler, 8791)
    h = shim.make_handler(LiteLLMConnector(), Arm("prisma", "gpt-4o", ("prisma-airs-pi",)),
                          "http://127.0.0.1:8791", "gw-secret", block_as_refusal=False)
    sh = _serve(h, 8792)
    time.sleep(0.2)
    try:
        _, echoed = _post("http://127.0.0.1:8792/echo",
                          {"messages": [{"role": "user", "content": "hi"}], "model": "orig"})
        assert echoed["received"]["guardrails"] == ["prisma-airs-pi"]
        assert echoed["received"]["model"] == "gpt-4o"
    finally:
        gw.shutdown(); sh.shutdown()


def test_baseline_arm_strips_guardrail():
    gw = _serve(mock_server.Handler, 8793)
    h = shim.make_handler(LiteLLMConnector(), Arm("baseline", "gpt-4o"),
                          "http://127.0.0.1:8793", None, block_as_refusal=False)
    sh = _serve(h, 8794)
    time.sleep(0.2)
    try:
        _, echoed = _post("http://127.0.0.1:8794/echo",
                          {"messages": [], "model": "x", "guardrails": ["stale"]})
        assert "guardrails" not in echoed["received"]
    finally:
        gw.shutdown(); sh.shutdown()


def test_block_to_refusal_converts_400():
    body = json.dumps({"error": {"message": "Blocked by policy: 'bomb'"}}).encode()
    code, data = shim.block_to_refusal(body, 400, "gpt-4o", {400})
    assert code == 200
    doc = json.loads(data)
    assert doc["choices"][0]["finish_reason"] == "content_filter"
    assert "[GUARDRAIL_BLOCK]" in doc["choices"][0]["message"]["content"]
    assert "bomb" in doc["choices"][0]["message"]["content"]


def test_block_to_refusal_reason_from_string_error():
    # {"error": "..."} (string, not object) must not lose the reason via AttributeError
    body = json.dumps({"error": "Blocked by policy: 'bomb'"}).encode()
    code, data = shim.block_to_refusal(body, 400, "m", {400})
    assert code == 200
    assert "bomb" in json.loads(data)["choices"][0]["message"]["content"]


def test_block_to_refusal_passthrough_non_block():
    body = b'{"ok":true}'
    code, data = shim.block_to_refusal(body, 200, "m", {400})
    assert code == 200 and data == body
    # operational errors are NOT converted (so they stay visible)
    code, data = shim.block_to_refusal(b'{"error":{}}', 500, "m", {400})
    assert code == 500


def test_arm_from_dict():
    arm = shim.arm_from_dict({"name": "a", "model": "m", "guardrails": ["g1", "g2"]})
    assert arm.model == "m" and arm.guardrails == ("g1", "g2")
