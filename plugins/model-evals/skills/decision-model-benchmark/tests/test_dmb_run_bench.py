"""The runner and report end to end against the mock server: plan, rows, refusals, errors.

No test touches the network: the known lane runs on the bundled fixtures (--known-source
fixture) or is switched off (--lanes custom)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import adapter
import known_lane
import metrics
import report
import run_bench
import variants

SECRET = "sk-test-DO-NOT-LEAK-0000"


def arm_arg(server, name, fmt, model, **extra):
    parts = {"name": name, "format": fmt, "url": server.url(fmt), "model": model, **extra}
    return ["--arm", ",".join(f"{k}={v}" for k, v in parts.items())]


def read_rows(out: Path) -> list[dict]:
    return [json.loads(line) for line in (out / "samples.jsonl").read_text().splitlines()]


def run(server, out, *extra, arms=None, depth="smoke"):
    arms = arms or (arm_arg(server, "mock-a", "systemone", "mock-decision-a", auth="none")
                    + arm_arg(server, "mock-b", "openai", "mock-decision-b", auth="none"))
    return run_bench.main([*arms, "--depth", depth, "--out", str(out), "--backoff", "0",
                           "--known-source", "fixture", *extra])


# ---- plan and depth --------------------------------------------------------------------------

def test_plan_prints_requests_and_tokens_and_sends_nothing(server, capsys, tmp_path):
    out = tmp_path / "never"
    code = run_bench.main([*arm_arg(server, "a", "systemone", "mock-decision-a", auth="none"),
                           "--depth", "smoke", "--plan", "--out", str(out),
                           "--known-source", "fixture"])
    err = capsys.readouterr().err
    assert code == 0 and server.requests == [] and not out.exists()
    assert "plan: custom lane 10 cases, known lane 12 cases x 1 arm(s)" in err
    assert "input tokens" in err
    for axis in ("clean", "injection", "injection_twin", "padding", "option_order",
                 "option_rename_twin", "paraphrase", "encoding", "structure",
                 "known:deepset-prompt-injections:fixture", "known:jevbench-original:fixture",
                 "scorecard cases per arm: dm-fail-open custom 10, dm-fail-open known 6"):
        assert axis in err
    assert "power (" in err and "precision:" in err             # smallest separable difference
    assert run_bench.main(["--depth", "full", "--plan", "--lanes", "custom"]) == 0  # no arm needed


def test_depth_names_are_the_shared_three_and_set_cases_and_techniques():
    assert run_bench.resolve_depth("smoke") == {"cases": 10, "mode": "one"}
    assert run_bench.resolve_depth("standard") == {"cases": None, "mode": "one"}
    assert run_bench.resolve_depth("full") == {"cases": None, "mode": "all"}
    assert run_bench.resolve_depth("7") == {"cases": 7, "mode": "one"}
    with pytest.raises(ValueError):
        run_bench.resolve_depth("quick")
    policies, cases = variants.load_corpus()

    def count(depth):
        d = run_bench.resolve_depth(depth)
        chosen = variants.select_cases(cases, d["cases"], 1)
        return len(run_bench.build_requests(chosen, policies, 1, d["mode"], variants.AXES, 3,
                                            "clean"))
    assert count("smoke") < count("standard") < count("full")


def test_repeats_apply_to_clean_requests_unless_scope_is_all():
    policies, cases = variants.load_corpus()
    one = cases[:1]
    base = run_bench.build_requests(one, policies, 1, "all", variants.AXES, 1, "clean")
    clean3 = run_bench.build_requests(one, policies, 1, "all", variants.AXES, 3, "clean")
    all3 = run_bench.build_requests(one, policies, 1, "all", variants.AXES, 3, "all")
    assert len(clean3) == len(base) + 2 and len(all3) == 3 * len(base)
    assert [r["repeat"] for r in clean3 if r["variant"]["id"] == "clean"] == [0, 1, 2]


# ---- a full run ------------------------------------------------------------------------------

def test_every_arm_gets_the_same_requests_and_the_report_is_written(server, tmp_path, capsys):
    out = tmp_path / "exp"
    assert run(server, out) == 0
    rows = read_rows(out)
    plan = json.loads((out / "results" / "run.json").read_text())["plan"]
    assert len(rows) == plan["requests"] * 2

    def keys(arm):
        return sorted((r["benchmark"], r["case"], r["variant"], r["repeat"])
                      for r in rows if r["arm"] == arm)
    assert keys("mock-a") == keys("mock-b") and len(set(keys("mock-a"))) == plan["requests"]
    for r in rows:                                        # the samples.jsonl contract
        assert {"arm", "target", "sample", "case", "seed_case", "variant", "axis", "repeat",
                "outcome", "truth", "error_class", "changed",
                "threat", "lane", "benchmark", "good"} <= set(r)
        assert r["sample"] == f"{r['seed_case']}/{r['variant']}#r{r['repeat']}"
    assert {r["model_echo"] for r in rows if r["arm"] == "mock-a"} == {"mock-decision-a"}

    # variants.jsonl holds exactly what was sent, once per (case, variant).
    sent = [json.loads(l) for l in (out / "results" / "variants.jsonl").read_text().splitlines()]
    assert len(sent) == len({(r["benchmark"], r["seed_case"], r["variant"]) for r in rows})
    assert all(v["parent"] == v["case"] and v["changed"] in ("none", "state", "options")
               for v in sent)

    capsys.readouterr()
    assert report.main([str(out)]) == 0
    text = (out / "summary.md").read_text()
    summary = json.loads((out / "summary.json").read_text())
    assert capsys.readouterr().out == text
    for heading in ("fail-open and fail-closed", "Decision flips under attack", "Consistency",
                    "Calibration", "Refusals, errors, latency and tokens", "Paired comparison",
                    "Read before trusting a number"):
        assert heading in text
    a, b = summary["arms"]["mock-a"], summary["arms"]["mock-b"]
    # The mock is deterministic, so identical re-runs never flip...
    assert a["flips"]["noise_floor"]["flip"]["k"] == 0 and a["flips"]["noise_floor"]["flip"]["n"] > 0
    # ...and it is deliberately sensitive to injected text and to option order.
    assert a["flips"]["axes"]["injection"]["flip"]["k"] > 0
    assert a["consistency"]["option_order"]["rate"] < 1.0
    assert a["flips"]["axes"]["injection"]["targeted_success"]["k"] > 0
    # mock-b refuses base64-wrapped input: those are refusals, not decisions and not errors.
    b64 = [r for r in rows if r["arm"] == "mock-b" and r["variant"] == "encoding.base64_wrapper"]
    assert b["outcomes"]["attacked"]["refusal"]["k"] == len(b64)
    assert all(r["outcome"] == "refusal" and r["decision"] is None and r["correct"] is None
               for r in b64)
    assert b["outcomes"]["all"]["error"]["k"] == 0
    assert summary["baseline"] == "mock-a" and "mock-b" in summary["comparisons"]
    assert summary["comparisons"]["mock-b"]["clean"]["pairs"] == plan["cases"]
    assert set(summary["known"]["mock-a"]) == {"deepset-prompt-injections:fixture",
                                               "jevbench-original:fixture"}
    assert "Known lane" in text
    # smoke is 10 cases: the flag says the flip rates rest on few cases, and the rates are there.
    assert "few_clean_correct_cases" in {f["flag"] for f in a["validity_flags"]}


def test_scores_use_canonical_labels_when_the_permissive_option_is_renamed(server, tmp_path):
    out = tmp_path / "exp"
    run(server, out, "--axes", "option_rename", depth="full",
        arms=arm_arg(server, "mock-a", "systemone", "mock-decision-a", auth="none"))
    renamed = [r for r in read_rows(out) if r["axis"] == "option_rename"]
    assert renamed and all(r["attacker_target"] != r["truth"] for r in renamed)
    for r in renamed:
        assert r["decision"] in r["probs"] and r["truth"] in r["probs"]
        assert r["decision_raw"] in r["options_sent"]
    hits = [r for r in renamed if r["decision"] == r["attacker_target"]]
    assert hits, "the mock is built to fall for a reassuring label"
    assert all(h["decision_raw"] != h["decision"] and h["correct"] is False for h in hits)
    assert {h["error_kind"] for h in hits} <= {"fail_open", "other"}


def test_the_key_is_sent_in_the_header_and_written_nowhere(make_server, tmp_path, monkeypatch):
    srv = make_server(require_auth=True)
    monkeypatch.setenv("MY_BENCH_KEY", SECRET)
    out = tmp_path / "exp"
    arms = arm_arg(srv, "keyed", "gemini", "mock-decision-a", **{"key-env": "MY_BENCH_KEY",
                                                                 "auth": "x-goog-api-key"})
    assert run(srv, out, "--depth", "3", arms=arms) == 0
    assert srv.requests[0]["headers"]["x-goog-api-key"] == SECRET
    for path in out.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(), f"key leaked into {path.name}"
    arm = json.loads((out / "results" / "run.json").read_text())["arms"][0]
    assert arm["key_env"] == "MY_BENCH_KEY" and arm["resolved_models"] == []
    report.main([str(out)])
    flags = {f["flag"] for f in json.loads((out / "summary.json").read_text())
             ["arms"]["keyed"]["validity_flags"]}
    assert {"no_model_echo", "option_order_not_sent"} <= flags


def test_a_key_in_the_url_query_string_is_sent_but_not_recorded(server, tmp_path):
    out = tmp_path / "exp"
    url = server.url("gemini") + "?key=" + SECRET
    arms = ["--arm", f"name=q,format=gemini,url={url},model=mock-decision-a,auth=none"]
    assert run(server, out, "--depth", "2", "--axes", "structure", arms=arms) == 0
    assert SECRET in server.requests[0]["path"]
    for path in out.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(), f"key leaked into {path.name}"
    assert adapter.safe_url("https://user:pw@h.example.com:8443/v1/x?key=abc#f") == \
        "https://h.example.com:8443/v1/x"


def test_a_dead_endpoint_stops_the_arm_after_one_request_and_is_not_a_result(server, tmp_path,
                                                                             capsys):
    out = tmp_path / "exp"
    bad = ["--arm", f"name=bad,format=systemone,url={server.base_url}/nope,model=m,auth=none"]
    good = arm_arg(server, "good", "systemone", "mock-decision-a", auth="none")
    code = run(server, out, "--retries", "0", arms=bad + good)
    assert code == 1                                         # an arm with no answer at all
    rows = read_rows(out)
    bad_rows = [r for r in rows if r["arm"] == "bad"]
    assert len(bad_rows) == 1 and bad_rows[0]["outcome"] == "error"
    assert bad_rows[0]["http_status"] == 404 and bad_rows[0]["decision"] is None
    assert "arm skipped" in capsys.readouterr().err
    assert sum(r["arm"] == "good" for r in rows) > 1
    report.main([str(out)])
    s = json.loads((out / "summary.json").read_text())
    assert s["arms"]["bad"]["clean"]["accuracy"]["rate"] is None      # no number invented
    assert s["arms"]["bad"]["outcomes"]["all"]["error"]["rate"] == 1.0


def test_unknown_model_is_reported_as_an_error_row_with_the_server_message(server, tmp_path):
    out = tmp_path / "exp"
    arms = arm_arg(server, "typo", "openai", "mock-decision-zz", auth="none")
    assert run(server, out, "--no-preflight", "--depth", "2", "--axes", "structure",
               arms=arms) == 1
    rows = read_rows(out)
    assert len(rows) > 1 and all(r["outcome"] == "error" for r in rows)
    assert all(r["http_status"] == 422 and "unknown model" in r["error"] for r in rows)
    assert all(r["correct"] is None and r["error_kind"] is None for r in rows)


def test_jitter_shows_up_as_a_nonzero_noise_floor(make_server, tmp_path):
    srv = make_server(jitter=3.0, jitter_seed=7)
    out = tmp_path / "exp"
    arms = arm_arg(srv, "noisy", "systemone", "mock-decision-b", auth="none")
    run(srv, out, "--repeats", "6", "--axes", "structure", "--concurrency", "1",
        "--lanes", "custom", arms=arms, depth="standard")
    summary = metrics.summarise(read_rows(out))
    noise = summary["arms"]["noisy"]["flips"]["noise_floor"]["flip"]
    assert noise["n"] > 0 and noise["k"] > 0
    assert summary["arms"]["noisy"]["consistency"]["rerun"]["rate"] < 1.0


def test_openai_placement_is_one_axis_between_two_arms_of_the_same_model(server, tmp_path):
    out = tmp_path / "exp"
    arms = (arm_arg(server, "user", "openai", "mock-decision-a", auth="none")
            + arm_arg(server, "tool", "openai", "mock-decision-a", auth="none",
                      placement="tool_output"))
    assert run(server, out, "--axes", "injection", "--lanes", "custom", depth="standard",
               arms=arms) == 0
    s = metrics.summarise(read_rows(out))
    user = s["arms"]["user"]["flips"]["axes"]["injection"]["targeted_success"]
    tool = s["arms"]["tool"]["flips"]["axes"]["injection"]["targeted_success"]
    assert user["n"] > 0 and tool["n"] > 0
    assert tool["rate"] < user["rate"]       # the mock weighs tool-output text less, by design
    bodies = [r["body"] for r in server.requests]
    assert any(isinstance(b["input"], list) and any(
        i.get("type") == "function_call_output" for i in b["input"]) for b in bodies)


def test_the_keyless_smoke_command_covers_all_three_wire_formats(tmp_path, capsys):
    out = tmp_path / "smoke"
    assert run_bench.main(["--mock", "--depth", "smoke", "--out", str(out)]) == 0
    rows = read_rows(out)
    assert {r["wire_format"] for r in rows} == {"systemone", "openai", "gemini"}
    assert {r["arm"] for r in rows} == {"mock-a", "mock-b", "mock-a-gemini"}
    assert all(r["outcome"] in ("answered", "refusal") for r in rows)
    capsys.readouterr()
    assert report.main([str(out)]) == 0
    s = json.loads((out / "summary.json").read_text())
    # The gemini path sorts option keys, so reordering cannot change its decisions.
    assert s["arms"]["mock-a-gemini"]["consistency"]["option_order"]["rate"] == 1.0
    assert s["arms"]["mock-a"]["consistency"]["option_order"]["rate"] < 1.0
    assert s["arms"]["mock-b"]["outcomes"]["attacked"]["refusal"]["k"] > 0
    for arm in s["arms"].values():
        assert arm["flips"]["noise_floor"]["flip"]["rate"] == 0.0


# ---- files and arguments ---------------------------------------------------------------------

def test_existing_samples_are_not_overwritten_without_force(server, tmp_path):
    out = tmp_path / "exp"
    one = arm_arg(server, "a", "systemone", "mock-decision-a", auth="none")
    assert run(server, out, "--depth", "2", arms=one) == 0
    with pytest.raises(SystemExit):
        run(server, out, "--depth", "2", arms=one)
    n = len(read_rows(out))
    assert run(server, out, "--depth", "2", "--force", arms=one) == 0
    assert len(read_rows(out)) == n


def test_the_analysis_plan_is_registered_before_results_and_reported(server, tmp_path, capsys):
    out = tmp_path / "exp"
    assert run(server, out, "--depth", "2") == 0
    doc = json.loads((out / "plan.json").read_text())
    plan = doc["plan"]
    assert doc["registered_before_results"] is True and doc["amendments"] == []
    assert plan["arms"] == ["mock-a", "mock-b"] and plan["baseline"] == "mock-a"
    assert plan["judge"] is None and plan["repeats"] == 3 and plan["depth"] == "2"
    assert {"dm-fail-open", "dm-nondeterminism"} <= set(plan["measures"])
    custom = plan["corpus"]["custom"]
    assert custom["visibility"] == "public" and len(custom["sha256"]) == 64
    assert set(plan["corpus"]["known"]) == {"deepset-prompt-injections:fixture",
                                            "jevbench-original:fixture"}
    rows = read_rows(out)
    assert {r["corpus"] for r in rows if r["lane"] == "custom"} == {custom["sha256"][:12]}
    assert {r["corpus"] for r in rows if r["lane"] == "known"} == {
        b["revision"][:12] for b in known_lane.SOURCES.values()}
    run_doc = json.loads((out / "results" / "run.json").read_text())
    assert run_doc["corpus"]["record"] == custom
    capsys.readouterr()
    assert report.main([str(out)]) == 0
    text = (out / "summary.md").read_text()
    for part in ("## Analysis plan", "No departures", "p (Holm)", "## Repeats",
                 "The custom-lane corpus is public"):
        assert part in text, part
    # A different plan in the same folder is kept as an amendment and reported as a departure.
    assert run(server, out, "--depth", "2", "--seed", "7", "--force",
               "--plan-reason", "second seed") == 0
    doc = json.loads((out / "plan.json").read_text())
    assert doc["amendments"][-1]["reason"] == "second seed"
    report.main([str(out)])
    text = (out / "summary.md").read_text()
    assert "`seed`: planned 20261114, observed 7" in text and "second seed" in text


def test_the_experiment_manifest_is_filled_when_there_is_one(server, tmp_path):
    out = tmp_path / "exp"
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps({
        "schema_version": 2, "skill": "decision-model-benchmark", "command": "FILL IN",
        "corpus": "FILL IN", "context": {"surface": None}, "model": {"id": None},
        "arms": [], "k": None, "scorers": [], "cost": {"usd": 0, "tokens_in": 0},
        "_todo": ["model.id", "k", "arms", "scorers", "model.cutoff", "cost.usd"]}))
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"context": {"surface": "agent tool gate", "tools": ["shell"]}}))
    one = arm_arg(server, "a", "systemone", "mock-decision-a", auth="none",
                  **{"price-per-m": "0.042"})
    assert run(server, out, "--depth", "2", "--review", str(review), arms=one) == 0
    doc = json.loads((out / "manifest.json").read_text())
    assert doc["cost"]["usd"] == pytest.approx(doc["cost"]["tokens_in"] * 0.042 / 1e6, abs=1e-6)
    assert "run_bench.py" in doc["command"] and "seed" in doc["corpus"]
    assert doc["k"] == 2 and doc["arms"][0]["name"] == "a"
    assert doc["model"]["id"] == "mock-decision-a"
    assert doc["context"]["surface"] == "agent tool gate"
    assert doc["cost"]["tokens_in"] > 0
    assert doc["_todo"] == ["model.cutoff"]
    run_doc = json.loads((out / "results" / "run.json").read_text())
    assert run_doc["execution_tier"] == "T0" and run_doc["context"]["tools"] == ["shell"]


def test_arm_arguments_are_checked_before_anything_is_sent(server, tmp_path, monkeypatch):
    monkeypatch.delenv("DMB_API_KEY", raising=False)
    with pytest.raises(SystemExit):                           # bearer auth with no key
        run_bench.main(["--arm", f"format=openai,url={server.url('openai')},model=m",
                        "--out", str(tmp_path / "x")])
    with pytest.raises(SystemExit):                           # no arm at all
        run_bench.main(["--out", str(tmp_path / "x")])
    with pytest.raises(SystemExit):                           # duplicate names
        run_bench.main([*arm_arg(server, "a", "systemone", "m", auth="none"),
                        *arm_arg(server, "a", "openai", "m", auth="none"),
                        "--out", str(tmp_path / "x")])
    assert server.requests == []


def test_runs_with_different_settings_are_marked_not_comparable(server, tmp_path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    run(server, a, "--depth", "2", "--axes", "structure",
        arms=arm_arg(server, "first", "systemone", "mock-decision-a", auth="none"))
    run(server, b, "--depth", "2", "--axes", "structure", "--seed", "5",
        arms=arm_arg(server, "second", "systemone", "mock-decision-b", auth="none"))
    capsys.readouterr()
    report.main([str(a), str(b), "--out", str(tmp_path / "both"), "--baseline", "second"])
    text = (tmp_path / "both" / "summary.md").read_text()
    assert "Not comparable" in text and "Paired comparison against `second`" in text


def test_own_corpus_is_loaded_and_a_bad_one_is_refused(server, tmp_path):
    policies, cases = variants.load_corpus()
    mine = tmp_path / "mine.jsonl"
    mine.write_text("".join(json.dumps(c) + "\n" for c in cases[:4]))
    out = tmp_path / "exp"
    one = arm_arg(server, "a", "systemone", "mock-decision-a", auth="none")
    assert run(server, out, "--cases", str(mine), "--depth", "full", "--axes", "padding",
               "--lanes", "custom", arms=one) == 0
    rows = read_rows(out)
    assert {r["seed_case"] for r in rows} == {c["id"] for c in cases[:4]}
    corpus = json.loads((out / "results" / "run.json").read_text())["corpus"]
    assert corpus["bundled"] is False
    assert {r["benchmark"] for r in rows} == {corpus["benchmark"]} != {"dmb-seed"}
    bad = dict(cases[0], truth="escalate")
    mine.write_text(json.dumps(bad) + "\n")
    with pytest.raises(variants.CorpusError):
        run(server, tmp_path / "exp2", "--cases", str(mine), arms=one)
