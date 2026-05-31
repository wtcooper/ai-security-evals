import sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from connectors.base import Arm, Connector
from connectors.litellm import LiteLLMConnector
from connectors.openai_passthrough import OpenAIPassthroughConnector
import injection_shim as shim


def test_litellm_named_arm_injects_guardrail_and_model():
    c = LiteLLMConnector()
    body = {"messages": [{"role": "user", "content": "hi"}], "model": "orig"}
    arm = Arm(name="prisma", model="gpt-4o", guardrails=("prisma-airs-pi",))
    out = c.inject(body, arm)
    assert out["guardrails"] == ["prisma-airs-pi"]
    assert out["model"] == "gpt-4o"           # model pinned for the arm
    assert out["messages"] == body["messages"]
    assert "guardrails" not in body            # original not mutated


def test_litellm_baseline_omits_guardrails():
    c = LiteLLMConnector()
    arm = Arm(name="baseline", model="gpt-4o")
    out = c.inject({"guardrails": ["stale"], "model": "x"}, arm)
    assert "guardrails" not in out
    assert out["model"] == "gpt-4o"
    assert arm.is_baseline


def test_openai_passthrough_custom_field(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_PARAM_FIELD", "policies")
    c = OpenAIPassthroughConnector()
    out = c.inject({"messages": []}, Arm(name="a", model="m", guardrails=("p1",)))
    assert out["policies"] == ["p1"]


def test_extra_params_passthrough():
    out = LiteLLMConnector().inject({}, Arm(name="a", model="m", guardrails=("g",),
                                            extra={"metadata": {"experiment": "x"}}))
    assert out["metadata"] == {"experiment": "x"}


def test_connector_registry():
    assert isinstance(Connector.from_id("litellm"), LiteLLMConnector)
    assert isinstance(Connector.from_id("openai"), OpenAIPassthroughConnector)
    try:
        Connector.from_id("nope")
        assert False
    except ValueError:
        pass


def test_arm_from_json():
    arm = shim.arm_from_json('{"name":"a","model":"m","guardrails":["g1","g2"]}')
    assert arm.model == "m" and arm.guardrails == ("g1", "g2")
    base = shim.arm_from_json('{"name":"baseline","model":"m"}')
    assert base.is_baseline


def test_build_forward_injects_and_authsets():
    url, headers, body, model = shim.build_forward(
        "/v1/chat/completions",
        {"Content-Length": "10", "Host": "x", "X-Keep": "1"},
        b'{"messages":[],"model":"orig"}',
        LiteLLMConnector(),
        Arm(name="lakera", model="gpt-4o", guardrails=("lakera-guard",)),
        "http://gw:4000/",
        "secret",
    )
    import json
    sent = json.loads(body)
    assert sent["guardrails"] == ["lakera-guard"]
    assert sent["model"] == "gpt-4o"
    assert model == "gpt-4o"   # post-injection model returned (no re-parse needed)
    assert url == "http://gw:4000/v1/chat/completions"
    assert headers["Authorization"] == "Bearer secret"
    assert "Content-Length" not in headers and "Host" not in headers  # hop-by-hop stripped
    assert headers["X-Keep"] == "1"


def test_build_forward_model_falls_back_to_client_then_arm():
    # baseline arm (model="") keeps the client's model
    _, _, _, model = shim.build_forward("/v1/chat/completions", {}, b'{"model":"client-m"}',
                                        LiteLLMConnector(), Arm(name="baseline", model=""),
                                        "http://gw", None)
    assert model == "client-m"
