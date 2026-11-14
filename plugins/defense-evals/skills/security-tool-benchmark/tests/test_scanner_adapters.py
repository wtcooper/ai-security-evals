"""extension kind: third-party scanner adapters (Tencent AI-Infra-Guard, Cisco skill-scanner and
mcp-scanner, NVIDIA SkillSpector) and the report converter they share.

Three groups:
  1. Converter tests on outputs captured from the real tools (fixtures/scanner-adapters/README.md
     says how each file was produced). No tool needed.
  2. Adapter logic tests against stub scanners written in the test. No tool needed.
  3. Adapter tests against the real tools, skipped when a tool is not installed. Point at one
     with <PREFIX>_BIN (SKILLSPECTOR_BIN, CISCO_SKILL_SCANNER_BIN, CISCO_MCP_SCANNER_BIN,
     AIG_SKILL_SCAN_BIN, AIG_MCP_SCAN_BIN) or put it on PATH. None needs an API key: the
     LLM-only tools talk to tests/mock_openai_server.py, which replays a canned reply.
"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys

import pytest

SKILL = pathlib.Path(__file__).resolve().parents[1]
EXT = SKILL / "extension"
ADAPTERS = EXT / "adapters"
CONVERTER = ADAPTERS / "scan_report_to_sarif.py"
FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "scanner-adapters"
sys.path.insert(0, str(SKILL / "lib"))
sys.path.insert(0, str(EXT))
import sarif_to_findings as s2f  # noqa: E402
import score_assets as sa  # noqa: E402

SCALE = {"critical", "high", "medium", "low", "info"}
KEY_VARS = ("LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
            "SKILL_SCANNER_LLM_API_KEY", "MCP_SCANNER_LLM_API_KEY", "MCP_SCANNER_API_KEY",
            "NVIDIA_INFERENCE_KEY", "SKILLSPECTOR_PROVIDER")


def keyless_env(**extra):
    env = {k: v for k, v in os.environ.items() if k not in KEY_VARS}
    env.update(extra)
    return env


def convert(*args):
    return subprocess.run([sys.executable, str(CONVERTER), *map(str, args)], capture_output=True, text=True)


def results_of(path):
    doc = json.loads(pathlib.Path(path).read_text())
    assert doc["version"] == "2.1.0" and isinstance(doc["runs"], list)
    return [r for run in doc["runs"] for r in run["results"]]


def rows_of(path, arm="arm", target="asset"):
    ctx = dict(run="t", arm=arm, target=target, sample=1, spec=target, tool=arm, tool_run=1)
    return s2f.convert(pathlib.Path(path), "sarif", ctx)


def location(res):
    phys = res["locations"][0]["physicalLocation"]
    return phys["artifactLocation"]["uri"], (phys.get("region") or {}).get("startLine")


# ------------------------------------------------------------ 1. converter on captured outputs
def test_cisco_mcp_clean_report_gives_valid_sarif_with_zero_results(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("cisco-mcp", FX / "cisco-mcp-scanner" / "clean.json", out,
                "--tools-file", FX / "samples" / "benign-mcp" / "tools.json",
                "--asset-root", FX / "samples" / "benign-mcp", "--require-analyzer", "yara")
    assert r.returncode == 0, r.stderr
    assert results_of(out) == []
    assert rows_of(out) == []


def test_cisco_mcp_flagged_report_maps_severity_rule_and_location(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("cisco-mcp", FX / "cisco-mcp-scanner" / "flagged-poisoned-tools.json", out,
                "--tools-file", FX / "samples" / "poisoned-mcp" / "tools.json",
                "--asset-root", FX / "samples" / "poisoned-mcp", "--meta", "config=static-only")
    assert r.returncode == 0, r.stderr
    res = results_of(out)
    # two poisoned tools: 3 threat names on word_count, 2 on run_helper; to_upper is SAFE
    assert sorted(x["ruleId"] for x in res) == [
        "yara_analyzer:CODE_EXECUTION", "yara_analyzer:CREDENTIAL_HARVESTING",
        "yara_analyzer:DATA_EXFILTRATION", "yara_analyzer:INJECTION_ATTACK",
        "yara_analyzer:PROMPT_INJECTION"]
    for x in res:
        assert x["properties"]["severity"] == "high" and x["properties"]["original_severity"] == "HIGH"
        assert x["level"] == "error" and x["message"]["text"]
    by_tool = {x["properties"]["item_name"]: location(x) for x in res}
    assert by_tool == {"word_count": ("tools.json", 4), "run_helper": ("tools.json", 9)}
    assert json.loads(out.read_text())["runs"][0]["properties"]["adapter"] == {"config": "static-only"}
    rows = rows_of(out)   # what run_scanner.sh appends to findings.jsonl
    assert {(w["severity"], w["file"]) for w in rows} == {("high", "tools.json")}
    assert all(w["rule_id"] and w["line"] in (4, 9) for w in rows)


def test_cisco_mcp_silent_llm_fallback_is_a_failure_not_a_result(tmp_path):
    # Captured with `--analyzers yara,llm` and no LLM key: the tool warned, ran YARA alone, exit 0.
    src = FX / "cisco-mcp-scanner" / "llm-requested-but-not-run.json"
    out = tmp_path / "f.sarif"
    out.write_text("stale")
    r = convert("cisco-mcp", src, out, "--require-analyzer", "yara", "--require-analyzer", "llm")
    assert r.returncode == 3 and "llm_analyzer did not run" in r.stderr
    assert not out.exists()                                  # no stale or partial SARIF left behind
    assert convert("cisco-mcp", src, out, "--require-analyzer", "yara").returncode == 0
    assert len(results_of(out)) == 5                         # as a YARA-only run it is a valid report


def test_cisco_mcp_llm_and_behavioral_shapes(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("cisco-mcp", FX / "cisco-mcp-scanner" / "combined-mockllm.json", out,
                "--require-analyzer", "yara", "--require-analyzer", "llm")
    assert r.returncode == 0, r.stderr
    assert {x["ruleId"] for x in results_of(out)} == {"llm_analyzer:PROMPT_INJECTION"}
    r = convert("cisco-mcp", FX / "cisco-mcp-scanner" / "behavioral-flagged-mockllm.json", out,
                "--require-analyzer", "behavioral")
    assert r.returncode == 0, r.stderr
    locs = sorted(location(x) for x in results_of(out))
    assert [ln for _, ln in locs] == [8, 14] and all(u.endswith("server.py") for u, _ in locs)


def test_cisco_mcp_report_with_no_items_is_not_clean(tmp_path):
    # Captured from `behavioral` when the model reply was unusable: scan_results is [], exit 0.
    src = FX / "cisco-mcp-scanner" / "behavioral-nothing-analysed.json"
    out = tmp_path / "f.sarif"
    r = convert("cisco-mcp", src, out, "--require-analyzer", "behavioral")
    assert r.returncode == 3 and "nothing was analysed" in r.stderr and not out.exists()
    assert convert("cisco-mcp", src, out, "--allow-empty").returncode == 0
    assert results_of(out) == []


@pytest.mark.parametrize("body", [
    "", "{not json", "null", "42", '{"server_url": "x"}', '{"scan_results": "nope"}',
    '{"scan_results": [{"tool_name": "t", "status": "completed"}]}',
    '{"scan_results": [{"tool_name": "t", "status": "completed", "findings": {"yara_analyzer": {}}}]}',
    '{"scan_results": [{"tool_name": "t", "status": "completed", "findings": {"yara_analyzer": '
    '{"severity": "APOCALYPTIC", "threat_names": ["X"], "total_findings": 1}}}]}',
])
def test_cisco_mcp_malformed_input_fails_loudly(tmp_path, body):
    src = tmp_path / "raw.json"
    src.write_text(body)
    out = tmp_path / "f.sarif"
    out.write_text("stale")
    r = convert("cisco-mcp", src, out)
    assert r.returncode == 2 and "malformed input" in r.stderr
    assert not out.exists()


def test_cisco_mcp_incomplete_item_status_fails(tmp_path):
    doc = json.loads((FX / "cisco-mcp-scanner" / "clean.json").read_text())
    doc["scan_results"][0]["status"] = "failed"
    doc["scan_results"][0]["findings"]["yara_analyzer"].update(severity="UNKNOWN", status="error")
    src = tmp_path / "raw.json"
    src.write_text(json.dumps(doc))
    out = tmp_path / "f.sarif"
    assert convert("cisco-mcp", src, out).returncode == 3 and not out.exists()
    assert convert("cisco-mcp", src, out, "--allow-incomplete").returncode == 0
    run = json.loads(out.read_text())["runs"][0]
    assert run["invocations"][0]["executionSuccessful"] is False and run["properties"]["incomplete"]


@pytest.mark.parametrize("tool,fixture", [
    ("skillspector", "skillspector/clean.sarif"),
    ("cisco-skill-scanner", "cisco-skill-scanner/clean.sarif"),
    ("aig-skill-scan", "aig-skill-scan/clean-mockllm.sarif"),
    ("aig-mcp-scan", "aig-mcp-scan/clean-mockllm.sarif"),
])
def test_normalize_clean_asset_gives_zero_results(tmp_path, tool, fixture):
    out = tmp_path / "f.sarif"
    r = convert("normalize", FX / fixture, out, "--tool", tool)
    assert r.returncode == 0, r.stderr
    assert results_of(out) == [] and rows_of(out) == []


def test_normalize_skillspector_flagged(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("normalize", FX / "skillspector" / "flagged-staged-fetch.sarif", out, "--tool", "skillspector")
    assert r.returncode == 0, r.stderr
    got = {x["ruleId"]: (x["properties"]["severity"], x["properties"]["original_severity"], location(x))
           for x in results_of(out)}
    assert got["TT5"] == ("critical", "CRITICAL", ("scripts/setup.py", 4))
    assert got["AST1"] == ("high", "HIGH", ("scripts/setup.py", 4))
    assert got["SSRF2"][0] == "medium" and got["LP3"][2] == ("SKILL.md", 1)
    assert {w["severity"] for w in rows_of(out)} == {"critical", "high", "medium"}


def test_normalize_cisco_skill_scanner_flagged(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("normalize", FX / "cisco-skill-scanner" / "flagged-staged-fetch.sarif", out,
                "--tool", "cisco-skill-scanner")
    assert r.returncode == 0, r.stderr
    got = {x["ruleId"]: (x["properties"]["severity"], x["properties"]["original_severity"], location(x))
           for x in results_of(out)}
    assert got["COMMAND_INJECTION_EVAL"] == ("critical", "CRITICAL", ("scripts/setup.py", 4))
    assert got["ACTIVE_REMOTE_ACQUIRE_EXECUTE"][:2] == ("high", "HIGH")
    assert got["TOOL_ABUSE_UNDECLARED_NETWORK"][0] == "medium"
    assert all(x["properties"]["severity_source"] == "tool-severity" for x in results_of(out))


def test_normalize_aig_maps_english_and_chinese_levels(tmp_path):
    out = tmp_path / "f.sarif"
    for fixture, original in (("flagged-mockllm.sarif", "High"), ("flagged-zh-severity-mockllm.sarif", "高危")):
        src = FX / "aig-skill-scan" / fixture
        r = convert("normalize", src, out, "--tool", "aig-skill-scan")
        assert r.returncode == 0, r.stderr
        (x,) = results_of(out)
        assert x["ruleId"] == "T03" and location(x) == ("scripts/setup.py", 3)
        assert (x["properties"]["severity"], x["properties"]["original_severity"]) == ("high", original)
        assert [w["severity"] for w in rows_of(out)] == ["high"]
    # Why the step exists: read raw, the harness does not know the Chinese level and calls it medium.
    assert [w["severity"] for w in rows_of(FX / "aig-skill-scan" / "flagged-zh-severity-mockllm.sarif")] == ["medium"]
    r = convert("normalize", FX / "aig-mcp-scan" / "flagged-mockllm.sarif", out, "--tool", "aig-mcp-scan")
    assert r.returncode == 0 and [x["properties"]["severity"] for x in results_of(out)] == ["high"]


def test_normalize_unknown_severity_falls_back_to_sarif_level(tmp_path):
    doc = json.loads((FX / "aig-skill-scan" / "flagged-mockllm.sarif").read_text())
    doc["runs"][0]["results"][0]["properties"]["severity"] = "Moderate-ish"
    doc["runs"][0]["results"][0]["level"] = "warning"
    src = tmp_path / "in.sarif"
    src.write_text(json.dumps(doc))
    out = tmp_path / "f.sarif"
    assert convert("normalize", src, out, "--tool", "aig-skill-scan").returncode == 0
    p = results_of(out)[0]["properties"]
    assert (p["severity"], p["original_severity"], p["severity_source"]) == ("medium", "Moderate-ish", "sarif-level")


def test_normalize_degraded_scans_fail_instead_of_reading_as_clean_or_flagged(tmp_path):
    out = tmp_path / "f.sarif"
    # SkillSpector, LLM requested with no provider key, on the BENIGN skill: exit 2, yet the file
    # it wrote carries one HIGH "not completely inspected" result.
    src = FX / "skillspector" / "llm-unavailable.sarif"
    r = convert("normalize", src, out, "--tool", "skillspector")
    assert r.returncode == 3 and "executionSuccessful=false" in r.stderr and not out.exists()
    assert convert("normalize", src, out, "--tool", "skillspector", "--allow-incomplete").returncode == 0
    assert [x["ruleId"] for x in results_of(out)] == ["AE1"]
    # aig-mcp-scan marks an agent run that ended with no output; that is not a clean asset.
    doc = json.loads((FX / "aig-mcp-scan" / "clean-mockllm.sarif").read_text())
    assert doc["runs"][0]["properties"]["scanNote"] == "complete"
    doc["runs"][0]["properties"]["scanNote"] = "possibly-incomplete"
    src2 = tmp_path / "in.sarif"
    src2.write_text(json.dumps(doc))
    out.unlink()
    r = convert("normalize", src2, out, "--tool", "aig-mcp-scan")
    assert r.returncode == 3 and "possibly-incomplete" in r.stderr and not out.exists()


def test_normalize_llm_failures_the_tools_report_with_exit_0_or_1(tmp_path):
    out = tmp_path / "f.sarif"
    # Cisco skill-scanner, `--use-llm`, model reply unusable: exit 0, the rule findings, plus one
    # INFO marker. Recorded as-is it would be a rules-only run under a combined label.
    src = FX / "cisco-skill-scanner" / "llm-analysis-failed-mockllm.sarif"
    assert "LLM_ANALYSIS_FAILED" in {x["ruleId"] for x in results_of(src)} and len(results_of(src)) == 7
    r = convert("normalize", src, out, "--tool", "cisco-skill-scanner")
    assert r.returncode == 3 and "LLM_ANALYSIS_FAILED" in r.stderr and not out.exists()
    # SkillSpector, provider reachable, replies unusable: exit 1, executionSuccessful=true, the
    # static findings, analysis marked partial. Fails only when completeness is asked for.
    src = FX / "skillspector" / "llm-replies-unusable-mockllm.sarif"
    r = convert("normalize", src, out, "--tool", "skillspector", "--require-complete")
    assert r.returncode == 3 and "'partial'" in r.stderr and not out.exists()
    assert convert("normalize", src, out, "--tool", "skillspector").returncode == 0
    assert len(results_of(out)) == 4
    # a complete scan passes the same check
    r = convert("normalize", FX / "skillspector" / "flagged-staged-fetch.sarif", out,
                "--tool", "skillspector", "--require-complete")
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("body", [
    "", "{", "[]", "{}", '{"version": "2.1.0"}', '{"version": "2.1.0", "runs": []}',
    '{"version": "1.0", "runs": [{"tool": {"driver": {"name": "skillspector"}}, "results": []}]}',
    '{"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "skillspector"}}}]}',
    '{"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "skillspector"}}, "results": null}]}',
    '{"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "skillspector"}}, "results": ["x"]}]}',
])
def test_normalize_malformed_sarif_fails_loudly(tmp_path, body):
    src = tmp_path / "in.sarif"
    src.write_text(body)
    out = tmp_path / "f.sarif"
    out.write_text("stale")
    r = convert("normalize", src, out, "--tool", "skillspector")
    assert r.returncode == 2 and "malformed input" in r.stderr
    assert not out.exists()


def test_normalize_rejects_a_report_from_another_tool(tmp_path):
    out = tmp_path / "f.sarif"
    r = convert("normalize", FX / "cisco-skill-scanner" / "clean.sarif", out, "--tool", "skillspector")
    assert r.returncode == 2 and "expected 'skillspector'" in r.stderr and not out.exists()


def test_converted_outputs_score_as_flag_and_clean(tmp_path):
    findings = []
    for arm, mode, fixture, extra in (
            ("skillspector", "normalize", "skillspector/flagged-staged-fetch.sarif", ["--tool", "skillspector"]),
            ("skillspector", "normalize", "skillspector/clean.sarif", ["--tool", "skillspector"]),
            ("cisco-mcp", "cisco-mcp", "cisco-mcp-scanner/flagged-poisoned-tools.json", []),
            ("cisco-mcp", "cisco-mcp", "cisco-mcp-scanner/clean.json", [])):
        out = tmp_path / "f.sarif"
        assert convert(mode, FX / fixture, out, *extra).returncode == 0
        findings += rows_of(out, arm=arm, target="mal" if "flagged" in fixture else "ben")
    labels = {"mal": {"label": "malicious"}, "ben": {"label": "benign"}}
    by = {(v["config"], v["asset"]): v["verdict"]
          for v in sa.build_verdicts_from_findings(findings, labels, severity_gate="medium")}
    assert by == {("skillspector", "mal"): "flag", ("skillspector", "ben"): "clean",
                  ("cisco-mcp", "mal"): "flag", ("cisco-mcp", "ben"): "clean"}


# ---------------------------------------------------------------- 2. adapter logic, stub tools
def run_adapter(name, asset, out, *args, env=None):
    return subprocess.run(["bash", str(ADAPTERS / f"{name}.sh"), str(asset), str(out), *map(str, args)],
                          capture_output=True, text=True, env=env or keyless_env())


def make_benign_skill(dst):
    """The benign sample as a skill folder. The fixture keeps the skill file under another name
    because the repo allows a file called SKILL.md only at a skill's own root."""
    src = FX / "samples" / "benign-skill"
    (dst / "scripts").mkdir(parents=True)
    shutil.copy(src / "skill-md.txt", dst / "SKILL.md")
    shutil.copy(src / "scripts" / "column_stats.py", dst / "scripts" / "column_stats.py")
    return dst


def make_mutant(benign, dst, cls="staged_fetch"):
    """A synthetic malicious sample from the repo's own generator (scan-only, local sink)."""
    r = subprocess.run([sys.executable, str(EXT / "mutate_skill.py"), str(benign), str(dst), "--class", cls],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (dst / ".label.json").exists()
    return dst


def write_stub(path, body):
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


SKILLSPECTOR_STUB = r'''
import json, os, sys
a = sys.argv[1:]
if a == ["--version"]:
    print("SkillSpector v0.0.0-stub"); sys.exit(0)
assert a[0] == "scan", a
target, out = a[1], a[a.index("--output") + 1]
json.dump({"argv": a, "cwd": os.getcwd()}, open(os.environ["STUB_LOG"], "w"))
rc = int(os.environ.get("STUB_EXIT", "0"))
files = sorted(os.path.relpath(os.path.join(d, f), target) for d, _, fs in os.walk(target) for f in fs)
results = [{"ruleId": "STUB1", "level": "error", "message": {"text": "saw " + f},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": os.path.join(target, f)}}}],
            "properties": {"severity": "CRITICAL", "security-severity": "9.5"}} for f in files]
if os.environ.get("STUB_WRITE", "1") == "1":
    json.dump({"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "skillspector"}},
               "invocations": [{"executionSuccessful": rc != 2}], "results": results}]}, open(out, "w"))
sys.exit(rc)
'''


def test_adapter_scans_a_copy_without_the_label_file_and_handles_exit_1(tmp_path):
    mutant = make_mutant(make_benign_skill(tmp_path / "benign"), tmp_path / "mutant")
    stub = write_stub(tmp_path / "skillspector", SKILLSPECTOR_STUB)
    log = tmp_path / "stub.json"
    out = tmp_path / "out"
    # exit 1 is SkillSpector's "risk score above 50": findings, not a failure
    r = run_adapter("skillspector", mutant, out, "--exclude", "docs/*",
                    env=keyless_env(SKILLSPECTOR_BIN=str(stub), STUB_LOG=str(log), STUB_EXIT="1"))
    assert r.returncode == 0, r.stderr
    seen = sorted(location(x)[0] for x in results_of(out / "findings.sarif"))
    assert seen == ["SKILL.md", "scripts/column_stats.py", "scripts/setup.py"]   # relative, no .label.json
    assert (mutant / ".label.json").exists()                                    # the asset itself is untouched
    call = json.loads(log.read_text())
    assert "--no-llm" in call["argv"]                                           # default config is static-only
    assert call["argv"][-2:] == ["--exclude", "docs/*"]                         # extra args passed through
    assert pathlib.Path(call["cwd"]) != mutant and not (pathlib.Path(call["cwd"]) / "SKILL.md").exists()
    meta = json.loads((out / "findings.sarif").read_text())["runs"][0]["properties"]["adapter"]
    assert meta["config"] == "static-only" and meta["tool_exit"] == "1" and "stub" in meta["tool_version"]
    assert sorted(p.name for p in out.glob("*.sarif")) == ["findings.sarif"]    # the only file run_scanner.sh picks up

    r = run_adapter("skillspector", mutant, out, "--config", "combined", "--in-place",
                    env=keyless_env(SKILLSPECTOR_BIN=str(stub), STUB_LOG=str(log)))
    assert r.returncode == 0, r.stderr
    assert "--no-llm" not in json.loads(log.read_text())["argv"]
    assert ".label.json" in {location(x)[0] for x in results_of(out / "findings.sarif")}   # --in-place scans as given


@pytest.mark.parametrize("stub_env", [{"STUB_EXIT": "2"}, {"STUB_EXIT": "2", "STUB_WRITE": "0"},
                                      {"STUB_EXIT": "0", "STUB_WRITE": "0"}, {"STUB_EXIT": "7"}])
def test_adapter_fails_and_leaves_no_sarif_when_the_tool_fails(tmp_path, stub_env):
    skill = make_benign_skill(tmp_path / "benign")
    stub = write_stub(tmp_path / "skillspector", SKILLSPECTOR_STUB)
    out = tmp_path / "out"
    out.mkdir()
    (out / "findings.sarif").write_text('{"version": "2.1.0", "runs": [{"results": []}]}')   # stale clean result
    r = run_adapter("skillspector", skill, out,
                    env=keyless_env(SKILLSPECTOR_BIN=str(stub), STUB_LOG=str(tmp_path / "l.json"), **stub_env))
    assert r.returncode != 0
    assert not list(out.glob("*.sarif"))


MCP_STUB = r'''
import json, os, sys
a = sys.argv[1:]
json.dump(a, open(os.environ["STUB_LOG"], "w"))
analyzers = a[a.index("--analyzers") + 1].split(",")
ran = [x for x in analyzers if x != "llm" or os.environ.get("MCP_SCANNER_LLM_API_KEY")]
tools = json.load(open(a[a.index("--tools") + 1]))["tools"]
print(json.dumps({"server_url": "stub", "requested_analyzers": analyzers, "scan_results": [
    {"status": "completed", "is_safe": True, "item_type": "tool", "tool_name": t["name"],
     "findings": {x + "_analyzer": {"severity": "SAFE", "threat_names": [], "total_findings": 0} for x in ran}}
    for t in tools]}))
'''


def test_cisco_mcp_adapter_requires_every_analyzer_of_the_config(tmp_path):
    stub = write_stub(tmp_path / "mcp-scanner", MCP_STUB)
    log = tmp_path / "argv.json"
    asset = FX / "samples" / "benign-mcp"
    env = keyless_env(CISCO_MCP_SCANNER_BIN=str(stub), STUB_LOG=str(log))
    out = tmp_path / "static"
    r = run_adapter("cisco-mcp-scanner", asset, out, env=env)
    assert r.returncode == 0, r.stderr
    argv = json.loads(log.read_text())
    assert argv[:4] == ["--analyzers", "yara", "--format", "raw"] and argv[4] == "static"
    assert argv[-1].endswith("/benign-mcp/tools.json") and results_of(out / "findings.sarif") == []
    # the stub copies the real tool: without an LLM key it drops the llm analyzer and still exits 0
    out = tmp_path / "combined"
    r = run_adapter("cisco-mcp-scanner", asset, out, "--config", "combined", env=env)
    assert r.returncode != 0 and "llm_analyzer did not run" in r.stderr
    assert not (out / "findings.sarif").exists()
    r = run_adapter("cisco-mcp-scanner", asset, out, "--config", "combined",
                    env={**env, "MCP_SCANNER_LLM_API_KEY": "dummy"})
    assert r.returncode == 0, r.stderr
    # an MCP asset with no saved tools list has nothing for the offline configs to read
    (tmp_path / "srconly").mkdir()
    (tmp_path / "srconly" / "server.py").write_text("print('hi')\n")
    r = run_adapter("cisco-mcp-scanner", tmp_path / "srconly", tmp_path / "o2", env=env)
    assert r.returncode != 0 and "tools.json" in r.stderr and not (tmp_path / "o2" / "findings.sarif").exists()


@pytest.mark.parametrize("adapter,args,code,needle", [
    ("skillspector", ["--config", "judge-only"], 2, "no LLM-only mode"),
    ("skillspector", ["--config", "nope"], 2, "unknown --config"),
    ("cisco-skill-scanner", ["--config", "nope"], 2, "unknown --config"),
    ("cisco-mcp-scanner", ["--config", "nope"], 2, "unknown --config"),
    ("aig-skill-scan", ["--config", "static-only"], 2, "LLM-only"),
    ("aig-skill-scan", ["--config", "combined"], 2, "LLM-only"),
    ("aig-mcp-scan", ["--config", "static-only"], 2, "LLM-only"),
    ("aig-mcp-scan", ["--server_url", "http://127.0.0.1:9"], 2, "not supported"),
    ("aig-skill-scan", [], 1, "needs a model key"),
    ("aig-mcp-scan", [], 1, "needs a model key"),
])
def test_adapters_reject_unsupported_configs_and_missing_keys_before_running_anything(tmp_path, adapter, args, code, needle):
    r = run_adapter(adapter, FX / "samples" / "benign-mcp", tmp_path / "out", *args)
    assert r.returncode == code and needle in r.stderr
    assert not (tmp_path / "out" / "findings.sarif").exists()


# ------------------------------------------------- 3. the real tools, skipped when not installed
def tool_env(prefix, binary):
    path = os.environ.get(f"{prefix}_BIN") or shutil.which(binary)
    if not path:
        pytest.skip(f"{binary} not installed (set {prefix}_BIN or put it on PATH)")
    return keyless_env(**{f"{prefix}_BIN": path})


@pytest.fixture
def mock_llm():
    """Start tests/mock_openai_server.py with a canned reply; yields a function reply-file -> base URL."""
    procs = []

    def start(reply_file):
        p = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).parent / "mock_openai_server.py"),
                              "--reply-file", str(reply_file)], stdout=subprocess.PIPE, text=True)
        procs.append(p)
        line = p.stdout.readline().strip()
        assert line.startswith("PORT="), line
        return f"http://127.0.0.1:{line.split('=')[1]}/v1"

    yield start
    for p in procs:
        p.terminate()
        p.wait(timeout=10)


def check_flagged(sarif, tmp_path):
    res = results_of(sarif)
    assert res, "the scanner reported nothing on the synthetic malicious sample"
    for x in res:
        assert x["ruleId"] and x["properties"]["severity"] in SCALE and "original_severity" in x["properties"]
        uri = location(x)[0]
        assert uri and not uri.startswith("/") and str(tmp_path) not in uri and uri != ".label.json"
    return res


@pytest.mark.parametrize("adapter,prefix,binary", [
    ("skillspector", "SKILLSPECTOR", "skillspector"),
    ("cisco-skill-scanner", "CISCO_SKILL_SCANNER", "skill-scanner"),
])
def test_real_skill_scanner_static_only(tmp_path, adapter, prefix, binary):
    env = tool_env(prefix, binary)
    benign = make_benign_skill(tmp_path / "benign")
    mutant = make_mutant(benign, tmp_path / "mutant")
    r = run_adapter(adapter, benign, tmp_path / "b", "--config", "static-only", env=env)
    assert r.returncode == 0, r.stderr
    assert results_of(tmp_path / "b" / "findings.sarif") == []
    r = run_adapter(adapter, mutant, tmp_path / "m", "--config", "static-only", env=env)
    assert r.returncode == 0, r.stderr
    res = check_flagged(tmp_path / "m" / "findings.sarif", tmp_path)
    assert any(location(x)[0] == "scripts/setup.py" for x in res)   # the staged fetch-and-exec script
    assert {w["severity"] for w in rows_of(tmp_path / "m" / "findings.sarif")} & {"critical", "high"}
    # an LLM config with no key must fail, never fall back to a rules-only result
    r = run_adapter(adapter, mutant, tmp_path / "c", "--config", "combined", env=env)
    assert r.returncode != 0 and not (tmp_path / "c" / "findings.sarif").exists()


def test_real_skill_scanners_fail_when_the_model_reply_is_unusable(tmp_path, mock_llm):
    """With a key set and a model that answers rubbish, both tools still exit 0/1 with their rule
    findings. The adapters must not record that as a combined run."""
    mutant = make_mutant(make_benign_skill(tmp_path / "benign"), tmp_path / "mutant")
    url = mock_llm(FX / "mock-replies" / "unusable.txt")
    ran = 0
    for adapter, prefix, binary, llm in (
            ("cisco-skill-scanner", "CISCO_SKILL_SCANNER", "skill-scanner",
             {"SKILL_SCANNER_LLM_API_KEY": "dummy", "SKILL_SCANNER_LLM_MODEL": "openai/mock-model",
              "SKILL_SCANNER_LLM_BASE_URL": url}),
            ("skillspector", "SKILLSPECTOR", "skillspector",
             {"SKILLSPECTOR_PROVIDER": "openai_compatible", "SKILLSPECTOR_COMPAT_API_KEY": "dummy",
              "SKILLSPECTOR_COMPAT_BASE_URL": url, "SKILLSPECTOR_MODEL": "mock-model"})):
        path = os.environ.get(f"{prefix}_BIN") or shutil.which(binary)
        if not path:
            continue
        ran += 1
        out = tmp_path / adapter
        r = run_adapter(adapter, mutant, out, "--config", "combined",
                        env=keyless_env(**{f"{prefix}_BIN": path}, **llm))
        assert r.returncode != 0 and "incomplete scan" in r.stderr, (adapter, r.stderr[-400:])
        assert not (out / "findings.sarif").exists()
    if not ran:
        pytest.skip("neither skill-scanner nor skillspector is installed")


def test_real_cisco_skill_scanner_llm_configs_against_mock_model(tmp_path, mock_llm):
    """Plumbing only: a canned "no findings" reply. judge-only must then report nothing, because
    its policy turns the rule analyzers off; combined must still report the rule findings."""
    env = {**tool_env("CISCO_SKILL_SCANNER", "skill-scanner"), "SKILL_SCANNER_LLM_API_KEY": "dummy",
           "SKILL_SCANNER_LLM_MODEL": "openai/mock-model",
           "SKILL_SCANNER_LLM_BASE_URL": mock_llm(FX / "mock-replies" / "cisco-skill-llm-clean.json")}
    mutant = make_mutant(make_benign_skill(tmp_path / "benign"), tmp_path / "mutant")
    r = run_adapter("cisco-skill-scanner", mutant, tmp_path / "j", "--config", "judge-only", env=env)
    assert r.returncode == 0, r.stderr
    assert results_of(tmp_path / "j" / "findings.sarif") == []
    r = run_adapter("cisco-skill-scanner", mutant, tmp_path / "c", "--config", "combined", env=env)
    assert r.returncode == 0, r.stderr
    assert check_flagged(tmp_path / "c" / "findings.sarif", tmp_path)


def test_real_cisco_mcp_scanner(tmp_path, mock_llm):
    env = tool_env("CISCO_MCP_SCANNER", "mcp-scanner")
    r = run_adapter("cisco-mcp-scanner", FX / "samples" / "benign-mcp", tmp_path / "b", env=env)
    assert r.returncode == 0, r.stderr
    assert results_of(tmp_path / "b" / "findings.sarif") == []
    r = run_adapter("cisco-mcp-scanner", FX / "samples" / "poisoned-mcp", tmp_path / "m", env=env)
    assert r.returncode == 0, r.stderr
    res = check_flagged(tmp_path / "m" / "findings.sarif", tmp_path)
    assert {location(x)[0] for x in res} == {"tools.json"} and all(location(x)[1] for x in res)
    r = run_adapter("cisco-mcp-scanner", FX / "samples" / "poisoned-mcp", tmp_path / "c", "--config", "combined", env=env)
    assert r.returncode != 0 and not (tmp_path / "c" / "findings.sarif").exists()   # no key: fail, not YARA-only
    # plumbing of the LLM configs against the mock (canned reply; says nothing about detection)
    llm = {**env, "MCP_SCANNER_LLM_API_KEY": "dummy", "MCP_SCANNER_LLM_MODEL": "openai/mock-model",
           "MCP_SCANNER_LLM_BASE_URL": mock_llm(FX / "mock-replies" / "cisco-mcp-llm-flagged.json")}
    r = run_adapter("cisco-mcp-scanner", FX / "samples" / "benign-mcp", tmp_path / "j", "--config", "judge-only", env=llm)
    assert r.returncode == 0, r.stderr
    assert {x["ruleId"] for x in results_of(tmp_path / "j" / "findings.sarif")} == {"llm_analyzer:PROMPT_INJECTION"}
    llm["MCP_SCANNER_LLM_BASE_URL"] = mock_llm(FX / "mock-replies" / "cisco-mcp-behavioral-flagged.json")
    r = run_adapter("cisco-mcp-scanner", FX / "samples" / "benign-mcp", tmp_path / "h", "--config", "behavioral", env=llm)
    assert r.returncode == 0, r.stderr
    assert {location(x)[0] for x in results_of(tmp_path / "h" / "findings.sarif")} == {"server.py"}


@pytest.mark.parametrize("adapter,prefix,binary", [
    ("aig-skill-scan", "AIG_SKILL_SCAN", "aig-skill-scan"),
    ("aig-mcp-scan", "AIG_MCP_SCAN", "aig-mcp-scan"),
])
def test_real_aig_scanner_against_mock_model(tmp_path, mock_llm, adapter, prefix, binary):
    """Plumbing only: the real tool, its real SARIF writer, a canned model reply."""
    env = {**tool_env(prefix, binary), "LLM_API_KEY": "dummy"}
    benign = make_benign_skill(tmp_path / "benign")
    mutant = make_mutant(benign, tmp_path / "mutant")
    url = mock_llm(FX / "mock-replies" / "aig-clean.txt")
    r = run_adapter(adapter, benign, tmp_path / "b", "-m", "mock-model", "-u", url, env=env)
    assert r.returncode == 0, r.stderr
    assert results_of(tmp_path / "b" / "findings.sarif") == []
    url = mock_llm(FX / "mock-replies" / "aig-flagged.txt")
    r = run_adapter(adapter, mutant, tmp_path / "m", "-m", "mock-model", "-u", url, env=env)
    assert r.returncode == 0, r.stderr
    (x,) = check_flagged(tmp_path / "m" / "findings.sarif", tmp_path)
    assert (x["ruleId"], x["properties"]["severity"], x["properties"]["original_severity"]) == ("T03", "high", "High")
    assert location(x) == ("scripts/setup.py", 3)
    # an unreachable model endpoint is a failed run, not a clean asset
    r = run_adapter(adapter, mutant, tmp_path / "u", "-m", "mock-model", "-u", "http://127.0.0.1:9/v1", env=env)
    assert r.returncode != 0 and not (tmp_path / "u" / "findings.sarif").exists()
