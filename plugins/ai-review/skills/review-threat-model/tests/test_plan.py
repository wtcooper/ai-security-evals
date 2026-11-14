"""Threat registry, templates and the plan skeleton: every threat routed once, nothing dropped."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import plan as planner  # noqa: E402
import render_templates  # noqa: E402

THREATS, TEMPLATES = planner.load_references()
CATALOG = json.loads((SKILL / "catalog.json").read_text())
FRAMEWORKS = json.loads((SKILL / "references" / "frameworks.json").read_text())
SUBJECT_TYPES = ("model", "agent", "app", "decision-model", "voice-model", "image-model",
                 "feature")


def _review(stype="agent", tools=("shell",), feature=None, weights_open=True):
    return {"review_id": "t-1",
            "subject": {"type": stype, "name": "s", "version": "v1", "vendor": "x",
                        "feature": feature, "weights": {"open": weights_open, "repo": "o/r"}},
            "context": {"tools": None if tools is None else list(tools)},
            "input_channels": [{"channel": "web pages", "untrusted": True},
                               {"channel": "prompt", "untrusted": False}]}


def _entry(**over):
    entry = {"id": "bench_a", "skill": "some-benchmark", "status": "available",
             "subjects": ["model"], "engine": "custom", "threats": ["jailbreak"], "tier": "T0",
             "needs_judge": False, "needs_sandbox": False, "calls_per_sample": 2,
             "dataset_size": 40, "verified": False, "note": ""}
    entry.update(over)
    return entry


def _plan(review, catalog=CATALOG, **kw):
    return planner.build_plan(review, catalog, THREATS, TEMPLATES, today="2026-11-14", **kw)


# --- registry and templates -------------------------------------------------------------------

def test_a_template_exists_for_every_subject_type_and_the_named_files_are_shipped():
    assert set(planner.TEMPLATE_FOR) == set(SUBJECT_TYPES)
    for name in ("model", "agent-in-harness", "app", "decision-model", "voice-model",
                 "image-model", "feature"):
        assert name in TEMPLATES
        assert (SKILL / "references" / f"{name}.md").is_file()


def test_every_threat_referenced_anywhere_is_in_the_registry():
    used = set()
    for template in TEMPLATES.values():
        groups = [template.get("threats", []), template.get("common", []),
                  *template.get("features", {}).values()]
        used |= {u["threat"] for group in groups for u in group}
    used |= {t for b in CATALOG["benchmarks"] for t in b["threats"]}
    assert used <= set(THREATS), used - set(THREATS)
    assert set(THREATS) <= used, f"registered but used nowhere: {set(THREATS) - used}"


def test_framework_ids_are_only_ones_recorded_as_verified():
    """An id that is not in frameworks.json was not checked against its source: leave it out."""
    allowed = {key: set(FRAMEWORKS[key]["ids"]) for key in ("owasp_llm", "owasp_agentic", "atlas")}
    shape = {"owasp_llm": r"LLM\d{2}:2025", "owasp_agentic": r"ASI\d{2}",
             "atlas": r"AML\.T\d{4}(\.\d{3})?"}
    for threat in THREATS.values():
        for key in allowed:
            for fid in threat[key]:
                assert re.fullmatch(shape[key], fid), (threat["id"], fid)
                assert fid in allowed[key], f"{threat['id']}: {fid} is not a verified id"
    for key in allowed:
        assert FRAMEWORKS[key]["source"].startswith("https://")


def test_every_threat_states_how_it_is_assessed_without_a_benchmark():
    for threat in THREATS.values():
        assert threat["fallback"] in ("custom_probe", "design_review", "uncovered")
        assert threat["fallback_note"].strip() and threat["description"].strip()


def test_rendered_markdown_templates_match_their_json_source():
    for name, text in render_templates.render_all().items():
        assert (SKILL / "references" / name).read_text() == text, f"{name} is stale"


# --- routing ------------------------------------------------------------------------------------

@pytest.mark.parametrize("stype", SUBJECT_TYPES)
def test_every_template_threat_lands_in_exactly_one_route(stype):
    review = _review(stype, feature="memory" if stype == "feature" else None)
    plan = _plan(review)
    expected = [u["threat"] for u in planner.template_threats(
        TEMPLATES[planner.TEMPLATE_FOR[stype]], review["subject"]["feature"])]
    assert [i["threat"] for i in plan["threats"]] == expected
    assert len(set(expected)) == len(expected)
    for item in plan["threats"]:
        assert item["route"] in planner.ROUTES
        assert (item["route"] == "benchmark") == bool(item["benchmarks"])
        if item["route"] != "benchmark":
            assert item["route_note"].strip(), item["threat"]
    totals = plan["totals"]
    assert sum(totals[r] for r in planner.ROUTES) + totals["not_applicable"] == len(expected)


def test_only_available_benchmarks_for_this_subject_type_count_as_coverage():
    catalog = {"benchmarks": [
        _entry(id="ok"),
        _entry(id="planned_one", status="planned"),
        _entry(id="candidate_one", status="candidate"),
        _entry(id="other_subject", subjects=["app"]),
        _entry(id="supervised", tier="T2"),
    ]}
    item = next(i for i in _plan(_review("model"), catalog)["threats"]
                if i["threat"] == "jailbreak")
    assert [b["id"] for b in item["benchmarks"]] == ["ok"]
    assert {e["id"] for e in item["also_exists"]} == {"planned_one", "candidate_one", "supervised"}
    assert all(e["why_not_planned"] for e in item["also_exists"])

    with_t2 = _plan(_review("model"), catalog, tiers=("T0", "T1", "T2"))
    item = next(i for i in with_t2["threats"] if i["threat"] == "jailbreak")
    assert {b["id"] for b in item["benchmarks"]} == {"ok", "supervised"}


def test_threat_with_no_available_benchmark_falls_back_to_its_registry_route():
    plan = _plan(_review("model"), {"benchmarks": [_entry(status="planned")]})
    by_id = {i["threat"]: i for i in plan["threats"]}
    assert plan["totals"]["benchmark"] == 0 and plan["runs"] == []
    assert by_id["jailbreak"]["route"] == THREATS["jailbreak"]["fallback"] == "custom_probe"
    assert by_id["offensive-capability"]["route"] == "uncovered"
    assert by_id["data-retention-hosting"]["route"] == "design_review"
    assert "No available catalogued benchmark" in planner.render_markdown(plan)


def test_threat_ruled_out_by_scope_stays_in_the_plan_with_its_reason():
    plan = _plan(_review("model", tools=()))
    hijack = next(i for i in plan["threats"] if i["threat"] == "agent-goal-hijack")
    assert hijack["applies"] is False and "no tools" in hijack["applies_reason"]
    assert plan["totals"]["not_applicable"] >= 1
    assert all("agent-goal-hijack" not in r["threats"]
               for run in plan["runs"] for r in run["benchmarks"])
    md = planner.render_markdown(plan)
    assert "`agent-goal-hijack`" in md.split("### Not applicable in this scope")[1]


def test_scope_that_review_json_leaves_open_is_listed_not_guessed():
    plan = _plan(_review("model", tools=None, weights_open="unknown"))
    hijack = next(i for i in plan["threats"] if i["threat"] == "agent-goal-hijack")
    assert hijack["applies"] is None
    assert any("agent-goal-hijack" in g for g in plan["scope_gaps"])
    assert any("supply-chain-model" in g for g in plan["scope_gaps"])
    assert "confirm it applies" in planner.render_markdown(plan)


def test_feature_template_is_the_named_feature_plus_common_without_duplicates():
    plan = _plan(_review("feature", feature="memory"))
    ids = [i["threat"] for i in plan["threats"]]
    assert ids[0] == "memory-poisoning" and "privilege-abuse" in ids
    assert "inter-agent-communication" not in ids
    unnamed = [i["threat"] for i in _plan(_review("feature", feature=None))["threats"]]
    assert unnamed[:3] == [u["threat"] for u in TEMPLATES["feature"]["features"]["other"]]


def test_unknown_subject_type_and_bad_depth_are_errors():
    with pytest.raises(ValueError):
        _plan(_review("chatbot"))
    with pytest.raises(ValueError):
        _plan(_review("model"), depth="deep")


# --- cost and interval --------------------------------------------------------------------------

def test_cost_uses_depth_capped_by_dataset_size():
    catalog = {"benchmarks": [_entry(dataset_size=40, calls_per_sample=2),
                              _entry(id="big", dataset_size=5000, calls_per_sample=3),
                              _entry(id="unknown_calls", dataset_size=None,
                                     calls_per_sample=None)]}
    item = next(i for i in _plan(_review("model"), catalog)["threats"]
                if i["threat"] == "jailbreak")
    by = {b["id"]: b for b in item["benchmarks"]}
    assert (by["bench_a"]["samples"], by["bench_a"]["model_calls"]) == (40, 80)
    assert (by["big"]["samples"], by["big"]["model_calls"]) == (100, 300)
    assert by["big"]["at_depth"]["smoke"]["samples"] == 25
    assert by["big"]["at_depth"]["full"]["model_calls"] == 15000
    assert by["unknown_calls"]["model_calls"] is None
    full = next(i for i in _plan(_review("model"), catalog, depth="full")["threats"]
                if i["threat"] == "jailbreak")
    assert {b["id"]: b["samples"] for b in full["benchmarks"]}["unknown_calls"] is None


def test_interval_halfwidth_matches_the_wilson_interval():
    width = planner.interval_halfwidth_pp(100)
    assert width == {"at_rate_0.5": 9.6, "at_rate_0.9": 6.0}
    assert planner.interval_halfwidth_pp(25)["at_rate_0.5"] > 18
    assert planner.interval_halfwidth_pp(None) is None


def test_a_benchmark_covering_two_threats_is_run_once():
    catalog = {"benchmarks": [_entry(threats=["jailbreak", "harmful-assistance"])]}
    plan = _plan(_review("model"), catalog)
    assert len(plan["runs"]) == 1
    rows = plan["runs"][0]["benchmarks"]
    assert len(rows) == 1 and set(rows[0]["threats"]) == {"jailbreak", "harmful-assistance"}
    assert plan["runs"][0]["samples"] == 40 and plan["runs"][0]["model_calls"] == 80


# --- output -----------------------------------------------------------------------------------

def test_plan_carries_no_acceptance_criteria_or_verdict_fields():
    plan = _plan(_review("agent"))

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    banned = {"threshold", "pass", "passed", "criteria", "criterion", "verdict", "acceptable",
              "decision", "controls", "mitigation", "mitigations", "recommendation"}
    assert not banned & set(keys(plan))
    md = planner.render_markdown(plan)
    assert "It sets no acceptance criteria" in md and "recommends no controls" in md


def test_agent_subject_sees_the_bare_api_caveat_on_model_benchmarks():
    plan = _plan(_review("agent"))
    hijack = next(i for i in plan["threats"] if i["threat"] == "agent-goal-hijack")
    assert hijack["route"] == "benchmark" and "bare model API" in hijack["route_note"]
    assert "Caveat for this subject type" in planner.render_markdown(plan)


def test_cli_writes_json_and_markdown_next_to_each_other(tmp_path, capsys):
    review = tmp_path / "review.json"
    review.write_text(json.dumps(_review("decision-model")))
    assert planner.main(["--review", str(review), "--depth", "smoke"]) == 0
    plan = json.loads((tmp_path / "test-plan.json").read_text())
    assert plan["template"] == "decision-model" and plan["depth"] == "smoke"
    md = (tmp_path / "test-plan.md").read_text()
    for heading in ("## Threat model", "## Test plan", "### 1. Covered by a catalogued benchmark",
                    "### 2. Needs a custom probe", "### 3. Design review only",
                    "### 4. Uncovered", "### Not applicable in this scope"):
        assert heading in md
    review.write_text(json.dumps(_review("chatbot")))
    assert planner.main(["--review", str(review)]) == 1
    capsys.readouterr()
