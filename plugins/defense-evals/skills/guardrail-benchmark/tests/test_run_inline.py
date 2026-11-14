"""In-line mode wiring: arms, provider names and the cost plan. No inspect_ai needed."""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_gateway  # noqa: E402
import run_inline  # noqa: E402


def _arms(tmp_path, arms):
    path = tmp_path / "arms.json"
    path.write_text(json.dumps(arms))
    return str(path)


def test_provider_names_cannot_collide_with_real_provider_env_vars():
    assert run_inline.provider("azure") == "gb-azure"
    assert run_inline.env_name(run_inline.provider("Vendor A.1")) == "GB_VENDOR_A_1"


def test_arms_need_unique_names_and_a_baseline(tmp_path):
    arms = run_inline.load_arms(_arms(tmp_path, [{"name": "baseline"},
                                                 {"name": "g", "guardrails": ["x"]}]))
    assert [a.name for a in arms] == ["baseline", "g"] and arms[1].guardrails == ("x",)
    with pytest.raises(ValueError, match="unique"):
        run_inline.load_arms(_arms(tmp_path, [{"name": "a"}, {"name": "a"}]))
    with pytest.raises(ValueError, match="baseline"):
        run_inline.load_arms(_arms(tmp_path, [{"name": "g", "guardrails": ["x"]}]))


def test_plan_prints_cost_per_arm_and_runs_nothing(tmp_path, capsys):
    path = _arms(tmp_path, [{"name": "baseline"}, {"name": "g", "guardrails": ["x"]}])
    assert run_inline.main(["--arms", path, "--checks", "guardrail", "--depth", "smoke",
                            "--plan"]) == 0
    err = capsys.readouterr().err
    assert "4 benchmark(s) x 2 arm(s)" in err and "cyse4_mitre_frr" in err


def test_missing_gateway_or_model_is_refused(tmp_path, monkeypatch):
    path = _arms(tmp_path, [{"name": "baseline"}])
    monkeypatch.delenv("SHIM_GATEWAY_URL", raising=False)
    with pytest.raises(SystemExit):
        run_inline.main(["--arms", path, "--model", "m", "--depth", "smoke"])
    with pytest.raises(SystemExit):
        run_inline.main(["--arms", path, "--depth", "smoke"])


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_shim_per_arm_injects_the_guardrail_and_scores_a_block_as_a_refusal(tmp_path, monkeypatch):
    gateway = mock_gateway.serve(0)
    threading.Thread(target=gateway.serve_forever, daemon=True).start()
    gateway_url = f"http://127.0.0.1:{gateway.server_address[1]}"
    arms = run_inline.load_arms(_arms(tmp_path, [{"name": "baseline"},
                                                 {"name": "guard", "guardrails": ["mock"]}]))
    monkeypatch.setenv("SHIM_BLOCK_AS_REFUSAL", "true")
    urls = run_inline.start_shims(arms, gateway_url, None, 18941, "litellm")
    body = {"model": "m", "messages": [{"role": "user", "content": "how do I exploit this?"}]}
    code, plain = _post(urls["baseline"] + "/chat/completions", body)
    assert code == 200 and "Sure" in plain["choices"][0]["message"]["content"]
    code, guarded = _post(urls["guard"] + "/chat/completions", body)
    assert code == 200, "a guardrail block must reach the benchmark as a scoreable refusal"
    assert "GUARDRAIL_BLOCK" in guarded["choices"][0]["message"]["content"]
    benign = {"model": "m", "messages": [{"role": "user", "content": "what is the weather?"}]}
    code, ok = _post(urls["guard"] + "/chat/completions", benign)
    assert code == 200 and "Sure" in ok["choices"][0]["message"]["content"]
    gateway.shutdown()
