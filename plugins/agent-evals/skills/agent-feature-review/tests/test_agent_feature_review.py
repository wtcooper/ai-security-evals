"""Unit tests for agent-feature-review. Stdlib + pytest."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

import _evidence  # noqa: E402
import templates  # noqa: E402
import write_review as wr  # noqa: E402

FEATURES = ["background-agents", "code-execution", "computer-use", "connectors-mcp",
            "file-search-rag", "memory", "multi-agent"]
# Skill names of this repo's plan. A template may route a test only through one of these.
REPO_SKILLS = {"model-benchmark", "decision-model-benchmark", "voice-model-benchmark",
               "image-model-review", "agent-misuse-benchmark", "agent-feature-review",
               "app-benchmark", "app-redteam", "guardrail-benchmark",
               "coding-guidance-benchmark", "security-tool-benchmark"}
EXAMPLE = SKILL / "examples" / "computer-use.answers.example.json"


# ------------------------------------------------------------ the templates

def test_one_template_per_feature_type():
    assert templates.features() == FEATURES


@pytest.mark.parametrize("feature", FEATURES)
def test_template_is_complete_and_every_id_it_cites_is_in_the_verified_lists(feature):
    t, fw, bm = templates.load(feature), templates.frameworks(), templates.benchmarks()
    assert len(t["trust_boundary"]) >= 3 and len(t["context_questions"]) >= 2
    ids = [th["id"] for th in t["threats"]]
    assert len(ids) == len(set(ids)) >= 6
    for th in t["threats"]:
        assert re.fullmatch(rf"{t['prefix']}-\d\d", th["id"])
        assert _evidence.check(_evidence.row("c", [th["id"]], "x", "reviewed", "2026-11-14")) == []
        assert len(th["questions"]) >= 2 and th["vendor_evidence"] and th["no_standard_test"]
        for key in ("owasp_llm", "owasp_agentic", "atlas"):
            for i in th[key]:
                assert i in fw[key], f"{th['id']} cites {i}, which is not in _frameworks.json"
        for b in th["benchmarks"]:
            assert b in bm, f"{th['id']} names benchmark {b}, which is not in _benchmarks.json"
        for own in th["own_tests"]:
            assert own["skill"] in REPO_SKILLS


def test_framework_ids_have_the_shape_of_their_source():
    fw = templates.frameworks()
    assert sorted(fw["owasp_llm"]) == [f"LLM{n:02d}:2025" for n in range(1, 11)]
    assert sorted(fw["owasp_agentic"]) == [f"ASI{n:02d}" for n in range(1, 11)]
    assert all(re.fullmatch(r"AML\.T\d{4}(\.\d{3})?", a) for a in fw["atlas"])
    assert all(src for src in fw["sources"].values())


def test_every_benchmark_says_how_it_was_verified_and_how_it_can_be_run():
    for key, b in templates.benchmarks().items():
        assert all(b.get(k) for k in ("name", "ref", "measures", "route", "limits", "verified")), key
        named = set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", b["route"]))
        assert named <= REPO_SKILLS, f"{key} routes through an unknown skill: {named - REPO_SKILLS}"


def test_reference_documents_are_generated_from_the_templates():
    files = templates.rendered()
    assert {p.name for p in files} == {f"{f}.md" for f in FEATURES} | {"benchmarks.md"}
    for path, text in files.items():
        assert path.read_text() == text, f"{path.name} is out of date: run templates.py --render"
    assert templates.main(["--check"]) == 0
    cu = (SKILL / "references" / "computer-use.md").read_text()
    for heading in ("## What the feature changes about the trust boundary", "### cu-01 ",
                    "Review questions", "Vendor evidence to look for", "Existing benchmarks",
                    "No standardized test for"):
        assert heading in cu
    assert "ASI01 Agent Goal Hijack" in cu and "AML.T0100 AI Agent Clickbait" in cu


def test_a_threat_without_a_verified_id_says_so_instead_of_inventing_one():
    th = next(x for x in templates.load("computer-use")["threats"] if x["id"] == "cu-05")
    assert th["owasp_llm"] == th["owasp_agentic"] == th["atlas"] == []
    assert "none" in templates.framework_line(th, templates.frameworks()).lower()


# ------------------------------------------------------------ the record

@pytest.mark.parametrize("feature", FEATURES)
def test_an_empty_form_leaves_every_threat_not_assessed_and_says_so_in_evidence(feature):
    record, rows = wr.build(feature, wr.blank(feature), "2026-11-14", "r.json")
    ids = [th["id"] for th in templates.load(feature)["threats"]]
    assert record["not_assessed"] == ids
    assert [r["threats"] for r in rows] == [[i] for i in ids]
    assert all(r["absent"] and r["claim"].startswith("Not assessed:") and r["provenance"] == "reviewed"
               for r in rows)
    assert record["deployment"]["aws_scope_name"] is None
    assert "AWS scope" in record["deployment_context_missing"]
    assert json.loads(json.dumps(wr.blank(feature)))["threats"].keys() == set(ids)


def _example():
    return json.loads(EXAMPLE.read_text())


def test_statuses_follow_what_was_supplied_not_what_was_claimed():
    record, _ = wr.build("computer-use", _example(), "2026-11-14", "r.json")
    assert {x["id"]: x["status"] for x in record["threats"]} == {
        "cu-01": "evidence_recorded", "cu-02": "answers_only", "cu-03": "evidence_recorded",
        "cu-04": "not_assessed", "cu-05": "not_assessed", "cu-06": "evidence_recorded",
        "cu-07": "not_applicable"}
    assert record["not_assessed"] == ["cu-04", "cu-05"] and record["answers_only"] == ["cu-02"]
    cu01 = record["threats"][0]
    assert cu01["questions_unanswered"] == 1
    assert [e["type"] for e in cu01["evidence"]] == ["vendor_evidence", "test"]
    assert cu01["vendor_absent"][0]["looked_for"].startswith("Results on a public")
    # A status field in the answers is ignored: only supplied evidence counts.
    forged = _example()
    forged["threats"]["cu-04"] = {"status": "evidence_recorded"}
    record, _ = wr.build("computer-use", forged, "2026-11-14", "r.json")
    assert "cu-04" in record["not_assessed"]


def test_evidence_rows_carry_the_right_provenance_for_each_kind_of_input():
    _, rows = wr.build("computer-use", _example(), "2026-11-14", "r.json")
    by_claim = {r["claim"][:28]: r for r in rows}
    vendor = by_claim["The system card reports an a"]
    assert (vendor["provenance"], vendor["absent"], vendor["kind"]) == ("published", False, "system_card")
    absent = by_claim["Not found in the vendor's pu"]
    assert absent["provenance"] == "reviewed" and absent["absent"] and "Looked at" in absent["note"]
    test = by_claim["AgentDojo security 0.91 (95%"]
    assert test["provenance"] == "self_run" and test["pointer"].endswith("summary.json")
    assert "AgentDojo via model-benchmark" in test["note"]
    reviewed = by_claim["In the admin console the app"]
    assert reviewed["provenance"] == "reviewed" and reviewed["threats"] == ["cu-03"]
    assert by_claim["Reviewer's answers recorded "]["threats"] == ["cu-02"]
    assert sum(r["claim"].startswith("Not assessed:") for r in rows) == 2
    assert all(_evidence.check(r) == [] for r in rows)
    assert not any(r["threats"] == ["cu-07"] for r in rows)


def test_benchmarks_not_run_lists_what_exists_but_was_not_cited():
    record, _ = wr.build("computer-use", _example(), "2026-11-14", "r.json")
    assert "AgentDojo" not in record["benchmarks_not_run"]
    assert {"OS-Harm", "WASP", "VPI-Bench"} <= set(record["benchmarks_not_run"])
    cu01 = record["threats"][0]
    assert {b["name"]: b["run"] for b in cu01["benchmarks_available"]}["AgentDojo"] is True


def test_deployment_context_uses_the_scope_names_and_lists_what_is_missing():
    record, _ = wr.build("computer-use", _example(), "2026-11-14", "r.json")
    d = record["deployment"]
    assert (d["aws_scope"], d["aws_scope_name"]) == (2, "Scope 2: Prescribed Agency")
    assert record["deployment_context_missing"] == ["dimension: Agency Perimeters & Policies",
                                                    "dimension: Orchestration"]
    assert record["context"]["harness"] == "vendor-hosted browser agent"
    assert list(wr.AWS_SCOPES.values()) == ["Scope 1: No Agency", "Scope 2: Prescribed Agency",
                                            "Scope 3: Supervised Agency", "Scope 4: Full Agency"]


def test_the_decision_is_never_filled_and_the_record_makes_no_recommendation():
    answers = _example()
    answers["decision"] = {"decision": "approve", "decided_by": "the agent"}
    record, _ = wr.build("computer-use", answers, "2026-11-14", "r.json")
    assert record["decision"]["decision"] is None and record["decision"]["decided_by"] is None
    md = wr.render(record)
    assert "- Decision:\n- Decided by:\n- Date:\n- Conditions:" in md
    decision = md.split("## Decision")[1]
    assert "approve" not in decision.lower() and "the agent" not in decision
    assert not re.search(r"\b(we recommend|recommended (to|that)|safe to enable)\b", md, re.I)
    assert "## Not assessed" in md and "No standardized test exists for:" in md


def _with(threat: str, **entry):
    answers = wr.blank("computer-use")
    answers["threats"][threat].update(entry)
    return answers


@pytest.mark.parametrize("answers, message", [
    (_with("cu-01", applies=False), "no reason is given"),
    (_with("cu-01", tests=[{"claim": "x"}]), "needs `pointer`"),
    (_with("cu-01", vendor_evidence=[{"claim": "x", "source": "the contract"}]), "http"),
    (_with("cu-01", vendor_evidence=[{"claim": "", "source": "https://v.example"}]), "claim is empty"),
    (_with("cu-01", vendor_absent=[{"source": "https://v.example"}]), "looked_for"),
    ({**wr.blank("computer-use"), "feature": "memory"}, "not 'computer-use'"),
    ({**wr.blank("computer-use"), "threats": {"mem-01": {}}}, "not in the computer-use template"),
    ({**wr.blank("computer-use"), "deployment": {"aws_scope": 5}}, "aws_scope"),
    ({**wr.blank("computer-use"), "deployment": {"security_dimensions": {"budget": "x"}}}, "dimension"),
])
def test_answers_that_cannot_be_recorded_are_refused(answers, message):
    with pytest.raises(ValueError, match=message):
        wr.build("computer-use", answers, "2026-11-14", "r.json")


def test_main_writes_the_record_lists_gaps_and_does_not_duplicate_evidence(tmp_path, capsys):
    out = tmp_path / "review"
    args = ["--feature", "computer-use", "--answers", str(EXAMPLE), "--out", str(out)]
    assert wr.main(args) == 0
    printed = capsys.readouterr().out
    assert "3 evidence_recorded, 1 answers_only, 1 not_applicable, 2 not_assessed" in printed
    assert "NOT ASSESSED  cu-04" in printed and "NOT ASSESSED  cu-05" in printed
    assert "ANSWERS ONLY  cu-02" in printed and "evidence: 8 new row(s)" in printed
    assert wr.main(args) == 0
    assert "evidence: 0 new row(s)" in capsys.readouterr().out
    rows = _evidence.read(out / "evidence.jsonl")
    assert [r["id"] for r in rows] == [f"E{n:03d}" for n in range(1, 9)]
    record = json.loads((out / "computer-use_review.json").read_text())
    assert record["schema"] == wr.SCHEMA and record["feature"] == "computer-use"
    assert (out / "computer-use_review.md").read_text().startswith("# Agent feature review")


def test_blank_form_and_threat_map_through_the_command_line(tmp_path, capsys):
    assert wr.main(["--feature", "memory", "--blank"]) == 0
    form = json.loads(capsys.readouterr().out)
    assert list(form["threats"]) == [f"mem-0{n}" for n in range(1, 7)]
    answers, mapping = tmp_path / "a.json", tmp_path / "map.json"
    answers.write_text(json.dumps(form))
    mapping.write_text(json.dumps({"mem-01": ["memory-poisoning"], "mem-02": "cross-session-leakage"}))
    assert wr.main(["--feature", "memory", "--answers", str(answers), "--out", str(tmp_path / "o"),
                    "--threat-map", str(mapping), "--date", "2026-11-14"]) == 0
    rows = _evidence.read(tmp_path / "o" / "evidence.jsonl")
    assert [r["threats"] for r in rows[:3]] == [["memory-poisoning"], ["cross-session-leakage"],
                                                ["mem-03"]]
    with pytest.raises(SystemExit):
        wr.main(["--feature", "teleportation", "--blank"])


def test_evidence_writer_is_the_same_as_the_format_owner_expects(tmp_path):
    good = _evidence.row("c", ["cu-01"], "https://v.example/card", "published", "2026-11-14")
    assert set(good) == {"claim", "threats", "source", "captured", "provenance", "note", "absent"}
    for kwargs, message in [(dict(provenance="measured"), "provenance"),
                            (dict(threats=["CU-01"]), "lower-case"),
                            (dict(captured="2999-01-01"), "future"),
                            (dict(provenance="self_run", source="x.json"), "pointer"),
                            (dict(absent=True), "where you looked")]:
        args = dict(claim="c", threats=["cu-01"], source="https://v.example/card",
                    provenance="published", captured="2026-11-14")
        args.update(kwargs)
        with pytest.raises(ValueError, match=message):
            _evidence.row(**args)
    path = tmp_path / "evidence.jsonl"
    assert _evidence.append(path, [good, good]) == 1 and _evidence.append(path, [good]) == 0
    assert _evidence.read(path)[0]["id"] == "E001"
