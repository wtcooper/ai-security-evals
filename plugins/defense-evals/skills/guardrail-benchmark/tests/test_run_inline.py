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


def test_plan_shows_epochs_as_extra_calls_not_extra_cases(tmp_path, capsys):
    path = _arms(tmp_path, [{"name": "baseline"}, {"name": "g", "guardrails": ["x"]}])
    assert run_inline.main(["--arms", path, "--checks", "cyse4_mitre_frr", "--depth", "10",
                            "--epochs", "3", "--plan"]) == 0
    err = capsys.readouterr().err
    assert "x3 epochs" in err and "n=10" in err and "two arms must differ" in err


def _fake_run(captured):
    import evalkit

    def run(arms, checks, **kw):
        captured.update(kw, arms=arms)
        evalkit.register_plan(kw["out"], kw["plan"], reason=kw.get("plan_reason"))
        return [{"status": "ok"}]
    return run


def test_run_registers_the_plan_and_passes_epochs_and_ceiling(tmp_path, monkeypatch):
    path = _arms(tmp_path, [{"name": "baseline"}, {"name": "g", "guardrails": ["x"]}])
    captured = {}
    monkeypatch.setenv("SHIM_GATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(run_inline, "start_shims", lambda *a, **k: {})
    monkeypatch.setattr(run_inline.inspect_runner, "run", _fake_run(captured))
    out = tmp_path / "results"
    assert run_inline.main(["--arms", path, "--model", "m", "--judge", "j", "--checks",
                            "cyse4_mitre_frr", "--depth", "10", "--epochs", "2",
                            "--ceiling", "0.9", "--out", str(out)]) == 0
    assert captured["epochs"] == 2 and captured["ceiling"] == 0.9
    plan = json.loads((out / "plan.json").read_text())["plan"]
    assert plan["baseline"] == "baseline" and plan["epochs"] == 2
    assert plan["judge"] == "openai-api/gbjudge/j" and plan["guardrails"] == {"baseline": [], "g": ["x"]}
    assert plan["measures"] == ["cyse4_mitre_frr"]


def test_the_judge_cannot_be_the_model_under_test(tmp_path, monkeypatch):
    path = _arms(tmp_path, [{"name": "baseline"}])
    monkeypatch.setenv("SHIM_GATEWAY_URL", "http://127.0.0.1:1")
    with pytest.raises(SystemExit):
        run_inline.main(["--arms", path, "--model", "m", "--judge", "m", "--depth", "smoke"])


def test_regrade_writes_a_judge_check_and_refuses_the_same_judge(tmp_path, monkeypatch):
    res = tmp_path / "results.json"
    res.write_text(json.dumps({"model": "m", "judge": "openai-api/gbjudge/j1", "rows": [
        {"arm": "baseline", "model": "openai-api/gb-baseline/m"}]}))
    rows = [{"arm": a, "target": "cyse4_mitre_frr", "sample": str(i), "epoch": 1,
             "good": (i % 3 != 0) if a == "g" else True, "response_chars": 40 + i}
            for a in ("baseline", "g") for i in range(12)]
    (tmp_path / "samples.jsonl").write_text(
        "".join(json.dumps({**r, "judge": "openai-api/gbjudge/j1"}) + "\n" for r in rows))

    def fake_regrade(results_json, judge, out=None, limit=None):
        dest = Path(results_json).with_name("samples_regrade.jsonl")
        dest.write_text("".join(json.dumps({**r, "judge": judge}) + "\n" for r in rows))
        return dest
    monkeypatch.setenv("SHIM_GATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(run_inline.inspect_runner, "regrade", fake_regrade)
    monkeypatch.delenv("GB_BASELINE_BASE_URL", raising=False)
    assert run_inline.main(["--regrade", str(res), "--judge", "j2"]) == 0
    assert "kappa" in (tmp_path / "judge_check.md").read_text().lower()
    import os
    assert os.environ["GB_BASELINE_BASE_URL"] == "http://127.0.0.1:9/v1"   # no arm is reachable
    for same in ("j1", "m"):
        with pytest.raises(SystemExit):
            run_inline.main(["--regrade", str(res), "--judge", same])
