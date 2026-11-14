"""The report compiler, run on the fixture review under tests/fixtures.

The fixture is a fictional subject: review.json, evidence.jsonl, test-plan.json, criteria.json
and three experiment folders (one complete with machine-readable results and validity
flags, one with only a summary.md and a context that differs, one interrupted)."""
from __future__ import annotations

import copy
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SKILL / "scripts"))
import compile_report as cr  # noqa: E402
import expread  # noqa: E402

REVIEW = json.loads((FIX / "review.json").read_text())
PLAN = json.loads((FIX / "test-plan.json").read_text())
CRITERIA = json.loads((FIX / "criteria.json").read_text())
EVIDENCE, _ = cr.load_evidence(FIX / "evidence.jsonl")
EXPS = [expread.read_experiment(f) for f in expread.find_experiments(FIX / "evals")]
CORE = next(e for e in EXPS if e["experiment"] == "example-model-1-core_2026-11-12")
HARNESS = next(e for e in EXPS if e["skill"] == "agent-misuse-benchmark")
INTERRUPTED = next(e for e in EXPS if e["experiment"].startswith("example-model-1-extended"))


def _report(**over) -> str:
    kw = dict(evidence=EVIDENCE, exps=EXPS, plan=PLAN, criteria=CRITERIA, criteria_exists=True,
              today="2026-11-14")
    kw.update(over)
    return cr.compile_report(REVIEW, **kw)


def _headings(text: str, level: str = "## ") -> list[str]:
    return [line[len(level):] for line in text.split("\n") if line.startswith(level)]


def _section(text: str, title: str) -> str:
    """Body of the level-2 section whose heading contains `title`."""
    parts = re.split(r"^## ", text, flags=re.M)
    return next(p for p in parts if p.split("\n", 1)[0].endswith(title))


# --- reading experiment folders ---------------------------------------------------------------

def test_reader_finds_metrics_flags_and_failures_in_the_shared_runner_shape():
    assert CORE["json_sources"] == ["summary.json", "results/results.json"]
    by = {m["benchmark"]: m for m in CORE["metrics"]}
    assert len(CORE["metrics"]) == 7, "summary.json and results.json rows must not double count"
    assert by["agentdojo"]["value"] == 0.12 and by["agentdojo"]["n"] == 100
    assert by["agentdojo"]["ci95"] == [0.07, 0.1981]
    assert by["agentdojo"]["direction"] == "lower_is_better"
    assert {f["flag"] for f in CORE["flags"]} == {"partial", "judge_unresolved", "low_utility"}
    assert all("example-model-1" in f["where"] for f in CORE["flags"])
    assert [(f["where"], f["status"]) for f in CORE["failures"]] == [
        ("example-model-1 / cyse4_multilingual_prompt_injection", "error")]
    assert CORE["problems"] == []


def test_reader_handles_other_skills_shapes(tmp_path):
    exp = tmp_path / "voice-model-benchmark" / "x_2026-11-12"
    exp.mkdir(parents=True)
    (exp / "manifest.json").write_text(json.dumps({"skill": "voice-model-benchmark",
                                                   "context": {"surface": "phone"}}))
    (exp / "summary.md").write_text("# s\n\n## Results\n\nnumbers\n")
    (exp / "summary.json").write_text(json.dumps({
        "samples": 50,
        "validity_flags": [{"flag": "not_understood", "observed": 0.4, "limit": 0.2,
                            "meaning": "audio may have been unintelligible", "scope": "noise"}],
        "arms": {"text": {"attack_success": {"n": 25, "graded": 24, "rate": 0.08,
                                             "ci95": [0.02, 0.26]},
                          "validity_flags": [{"flag": "x", "observed": 1, "limit": 0,
                                              "meaning": ""}]},
                 "noise": {"attack_success": {"k": 5, "n": 25, "rate": 0.2, "ci95": None}}},
        "cost": {"value": 3.2},
    }))
    got = expread.read_experiment(exp)
    labels = {m["label"]: m for m in got["metrics"]}
    assert set(labels) == {"arms/text/attack_success", "arms/noise/attack_success"}
    assert labels["arms/text/attack_success"]["n"] == 24, "graded, not attempted, is the n"
    assert {(f["where"], f["flag"]) for f in got["flags"]} == {("noise", "not_understood"),
                                                               ("arms/text", "x")}
    assert expread.match_metrics(got, {"skill": "voice-model-benchmark", "metric":
                                       "attack_success", "arm": "noise"})[0]["value"] == 0.2
    assert expread.match_metrics(got, {"skill": "model-benchmark", "metric": "attack_success"}) == []


def test_reader_reports_what_it_cannot_read_instead_of_raising(tmp_path):
    exp = tmp_path / "some-benchmark" / "broken_2026-11-12"
    exp.mkdir(parents=True)
    (exp / "summary.json").write_text("{not json")
    got = expread.read_experiment(exp)
    joined = " | ".join(got["problems"])
    assert "no manifest.json" in joined and "no summary.md" in joined
    assert "summary.json is not valid JSON" in joined
    assert got["skill"] == "some-benchmark" and got["metrics"] == []


def test_validity_section_is_read_from_a_summary_that_has_no_json():
    assert HARNESS["json_sources"] == [] and len(HARNESS["summary_validity_lines"]) == 2
    assert "proves the wiring only" in HARNESS["summary_validity_lines"][0]
    assert expread.validity_section("# t\n\n## Results\n\n- 0.9\n") == []


# --- report structure -------------------------------------------------------------------------

def test_sections_appear_in_the_required_order():
    assert _headings(_report()) == [
        "1. What was reviewed, and in what context",
        "2. Evidence, with provenance",
        "3. Results",
        "4. Threats not covered",
        "5. The organisation's criteria beside the results",
        "6. Decision",
        "7. Conditions",
        "8. Sign-off",
        "Inputs to this report",
    ]


def test_criteria_section_exists_only_when_criteria_json_exists():
    text = _report(criteria=None, criteria_exists=False)
    assert "criteria beside the results" not in text
    assert "No criteria.json was supplied" in text and "none are implied" in text
    assert _headings(text)[4:7] == ["5. Decision", "6. Conditions", "7. Sign-off"]


def test_embedded_summaries_cannot_add_top_level_sections():
    """A summary's own '## Results' heading must not appear as a section of the report."""
    text = _report()
    assert "##### Results" in text
    assert len([h for h in _headings(text) if "Results" in h]) == 1


def test_demote_leaves_fenced_code_alone():
    assert cr.demote("# a\n```\n# not a heading\n```\n## b") == \
        "#### a\n```\n# not a heading\n```\n##### b"


# --- section 1 and 2 ----------------------------------------------------------------------------

def test_scope_section_prints_every_context_key_and_names_what_is_unknown():
    review = copy.deepcopy(REVIEW)
    review["context"]["safeguards"] = "unknown"
    review["context"]["surface"] = None
    body = _section(_report(), "What was reviewed, and in what context")
    for key in cr.CONTEXT_KEYS:
        assert f"| {key.replace('_', ' ')} |" in body
    assert "Every scoping answer was given." in body
    gaps = cr.section_scope(review)
    tail = "\n".join(gaps[gaps.index("### Not established at scoping"):])
    assert "`context.safeguards`" in tail and "`context.surface (not stated)`" in tail


def test_absent_evidence_is_listed_first_and_kept_out_of_the_claim_tables():
    body = _section(_report(), "Evidence, with provenance")
    absent, rest = body.split("### Measured by this organisation")
    assert "### Looked for and not found" in absent
    assert "| E001 |" in absent and "| E005 |" in absent and "Unscanned is not clean" in absent
    assert "| E001 |" not in rest and "| E005 |" not in rest
    order = [body.index(f"(`{p}`)") for p in ("self_run", "reviewed", "published", "harvested")]
    assert order == sorted(order)
    assert "not checked here (`published`)" in body


def test_no_evidence_file_is_stated_as_not_assessed():
    body = _section(_report(evidence=None), "Evidence, with provenance")
    assert "No evidence.jsonl was supplied" in body and "not assessed" in body


def test_unreadable_evidence_rows_are_counted_not_dropped(tmp_path):
    path = tmp_path / "evidence.jsonl"
    path.write_text((FIX / "evidence.jsonl").read_text() + "{broken\n" + '{"id": "E9"}\n')
    rows, problems = cr.load_evidence(path)
    assert len(rows) == len(EVIDENCE) and len(problems) == 2
    assert "could not be read" in "\n".join(cr.section_evidence(rows, problems))


# --- section 3: validity flags first ---------------------------------------------------------------

def test_validity_flags_come_before_any_summary_text():
    body = _section(_report(), "Results")
    first_summary = body.index("**Summary as written by the skill:**")
    read_first = body.index("### Read before any number")
    assert read_first < first_summary
    head = body[read_first:body.index("### agent-misuse-benchmark")]
    for flag in ("`partial`", "`judge_unresolved`", "`low_utility`"):
        assert flag in head
    assert "status `error`" in head and "not a zero and not a pass" in head
    assert "observed 0.21, validity limit 0.3" in head


def test_each_experiment_repeats_its_own_flags_above_its_summary():
    body = _section(_report(), "Results")
    block = body[body.index("### model-benchmark — example-model-1-core"):]
    assert block.index("**Read first:**") < block.index("**Summary as written by the skill:**")
    assert block.index("`low_utility`") < block.index("**Summary as written by the skill:**")
    assert "0.12 [0.07–0.20] n=100" in block, "a flag must never hide the number"


def test_report_checks_context_mismatch_unfinished_manifest_and_missing_summary():
    notes = cr.read_first(HARNESS, REVIEW)
    assert any("context differs from review.json on `harness_version`" in n and "0.0.2" in n
               for n in notes)
    assert any("`safeguards`" in n for n in notes)
    assert any("unfilled fields: k, cost.usd" in n for n in notes)
    assert all(n.startswith("**Report check**") for n in notes)
    assert any("no summary.md" in n for n in cr.read_first(INTERRUPTED, REVIEW))
    assert not cr.context_differences(CORE, REVIEW)
    blank = dict(CORE, context={k: None for k in cr.CONTEXT_KEYS})
    assert "records no context" in cr.context_differences(blank, REVIEW)[0]


def test_summary_only_experiment_shows_the_summarys_own_validity_section():
    body = _section(_report(), "Results")
    block = body[body.index("### agent-misuse-benchmark"):body.index("### model-benchmark")]
    assert "**The summary's own validity section says:**" in block
    assert "Permission prompts were off" in block


def test_summary_without_validity_section_or_json_is_flagged(tmp_path):
    exp = tmp_path / "app-benchmark" / "x_2026-11-12"
    exp.mkdir(parents=True)
    (exp / "manifest.json").write_text(json.dumps({"skill": "app-benchmark",
                                                   "context": REVIEW["context"]}))
    (exp / "summary.md").write_text("# summary\n\nASR 0.10\n")
    notes = cr.read_first(expread.read_experiment(exp), REVIEW)
    assert any("no validity section" in n for n in notes)


def test_no_experiments_is_stated():
    body = _section(_report(exps=[]), "Results")
    assert "Nothing was measured" in body


# --- section 4: threats not covered ---------------------------------------------------------------

def test_coverage_states():
    cov = {c["threat"]: c for c in cr.coverage(PLAN, EVIDENCE, EXPS)}
    assert cov["agent-goal-hijack"]["state"] == "measured"
    assert cov["agent-goal-hijack"]["measured"] == ["agentdojo"]
    assert cov["agent-goal-hijack"]["missing"] == ["atb_autonomy_hijack"]
    assert cov["agent-goal-hijack"]["flagged"] == ["agentdojo"]
    assert cov["human-trust-exploitation"]["state"] == "examined"
    assert cov["data-retention-hosting"]["state"] == "claims only"
    assert cov["data-leakage"]["state"] == "not assessed"
    assert cov["supply-chain-model"]["state"] == "not assessed", \
        "an absent row is not evidence that the threat was examined"
    assert cov["supply-chain-model"]["absent"] == ["E005"]
    assert cov["rogue-agent"]["state"] == "not assessed"


def test_a_benchmark_that_ran_without_a_score_does_not_count_as_measured():
    plan = copy.deepcopy(PLAN)
    item = next(i for i in plan["threats"] if i["threat"] == "jailbreak")
    item["benchmarks"][0]["id"] = "cyse4_multilingual_prompt_injection"
    cov = {c["threat"]: c for c in cr.coverage(plan, [], EXPS)}
    assert cov["jailbreak"]["failed"] == ["cyse4_multilingual_prompt_injection"]
    assert cov["jailbreak"]["state"] == "not assessed"
    body = "\n".join(cr.section_not_covered(plan, [], EXPS, REVIEW))
    assert "ran without producing a score: `cyse4_multilingual_prompt_injection`" in body


def test_not_covered_section_lists_every_gap_by_kind():
    body = _section(_report(), "Threats not covered")

    def block(title):
        return body.split(f"### {title}")[1].split("###")[0]

    assert "`data-leakage`" in block("Planned for measurement, no result found")
    assert "`atb_autonomy_hijack`" in block("Measured in part")
    todo = block("Custom probe or design review planned, nothing recorded")
    assert "`tool-misuse`" in todo and "`harness-divergence`" in todo
    assert "`human-trust-exploitation`" not in todo, "it has a reviewed evidence row"
    assert "vendor or third-party claims only (E004)" in todo
    uncovered = block("Uncovered by the plan")
    assert "`rogue-agent`" in uncovered and "`offensive-capability`" in uncovered
    assert "agentdojo ⚑" in block("Every threat in the plan")
    assert "Excluded at scoping and therefore not assessed at all" in body


def test_threats_ruled_out_or_unconfirmed_at_scoping_are_listed_with_reasons():
    plan = copy.deepcopy(PLAN)
    by = {i["threat"]: i for i in plan["threats"]}
    by["tool-misuse"].update(applies=False, applies_reason="review.json lists no tools")
    by["memory-poisoning"].update(applies=None, applies_reason="memory not stated")
    body = "\n".join(cr.section_not_covered(plan, EVIDENCE, EXPS, REVIEW))
    assert "`tool-misuse` Tool misuse — review.json lists no tools" in \
        body.split("### Ruled out at scoping")[1]
    assert "`memory-poisoning`" in body.split("### Applicability never confirmed")[1].split("###")[0]
    assert "| ruled out at scoping |" in body


def test_no_plan_is_itself_reported_as_a_gap():
    body = _section(_report(plan=None), "Threats not covered")
    assert "No test plan (test-plan.json) was supplied" in body
    assert "`data-retention-hosting`: published" in body
    assert "`supply-chain-model`: absent" in body


# --- section 5: criteria beside results, never evaluated ---------------------------------------------

def test_criteria_are_placed_beside_results_and_not_evaluated():
    body = _section(_report(), "The organisation's criteria beside the results")
    row = next(line for line in body.split("\n") if line.startswith("| C1 |"))
    assert "agentdojo · example-model-1: 0.120 [0.070–0.198] n=100" in row
    assert "Head of Security" in row and "| before |" in row
    assert row.rstrip().endswith("|  |"), "the Met? cell is for the organisation"
    for word in ("met:", "not met", "passes", "fails", "✅", "❌"):
        assert word not in body.lower()
    assert "This report does not evaluate them" in body


def test_criteria_set_after_results_are_called_out():
    body = _section(_report(), "The organisation's criteria beside the results")
    assert "1 of 2 criteria were set after results" in body and "(C2)" in body
    assert "weaker evidence" in body


def test_before_claim_dated_after_the_first_experiment_is_queried_not_corrected():
    criteria = copy.deepcopy(CRITERIA)
    criteria["criteria"][0]["set_on"] = "2026-11-13"       # experiments start 2026-11-12
    body = "\n".join(cr.section_criteria(criteria, None, EXPS))
    assert "**Timing to confirm:**" in body
    assert "C1 is recorded as set before results, but is dated 2026-11-13" in body
    assert "| before |" in body, "the organisation's own record is shown unchanged"


def test_results_without_a_criterion_and_declined_dimensions_are_listed():
    body = _section(_report(), "The organisation's criteria beside the results")
    unmatched = body.split("### Measured, with no criterion set")[1].split("###")[0]
    assert "cyse4_mitre · example-model-1" in unmatched
    assert "agentdojo" not in unmatched and "cyse4_mitre_frr" not in unmatched
    assert "chose to set no criterion for" in body and "insecure code" in body


def test_criterion_with_no_matching_result_says_so():
    criteria = copy.deepcopy(CRITERIA)
    criteria["criteria"][0]["measure"]["benchmark"] = "atb_data_exfil"
    body = "\n".join(cr.section_criteria(criteria, None, EXPS))
    assert "no matching result found" in body


def test_unreadable_or_empty_criteria_file_still_gets_its_section():
    text = _report(criteria=None, criteria_problem="criteria.json is not valid JSON (x)")
    assert "exists but could not be read" in _section(text, "criteria beside the results")
    text = _report(criteria={"schema_version": 1, "criteria": []})
    assert "contains no criteria" in _section(text, "criteria beside the results")


# --- decision, conditions, sign-off: blank ------------------------------------------------------------

def test_decision_conditions_and_signoff_are_left_blank():
    text = _report()
    decision = _section(text, "Decision")
    for field in ("- Decision:", "- Decided by (name, role):", "- Date:"):
        line = next(ln for ln in decision.split("\n") if ln.startswith(field))
        assert line.strip() == field, f"{field} must be empty"
    for title in ("Conditions", "Sign-off"):
        rows = [ln for ln in _section(text, title).split("\n") if ln.startswith("|")]
        assert len(rows) >= 4
        for row in rows[2:]:
            assert set(row) <= {"|", " "}, f"{title} has a pre-filled cell: {row!r}"
    people = decision + _section(text, "Conditions") + _section(text, "Sign-off")
    assert not re.search(r"\b(approv\w*|reject\w*|recommend\w*|accept(ed|able)|go-live|no-go)\b",
                         people, re.I)
    assert "contains no verdict" in text.split("## 1.")[0]


# --- CLI ----------------------------------------------------------------------------------------------

def test_cli_finds_sibling_inputs_and_writes_report_next_to_review(tmp_path, capsys):
    for name in ("review.json", "evidence.jsonl", "test-plan.json"):
        shutil.copy(FIX / name, tmp_path / name)
    shutil.copytree(FIX / "evals", tmp_path / ".evals")
    assert cr.main(["--review", str(tmp_path / "review.json"), "--date", "2026-11-14"]) == 0
    text = (tmp_path / "report.md").read_text()
    assert "3 experiment(s)" in capsys.readouterr().out
    assert "criteria beside the results" not in text
    assert "| criteria.json | not supplied | — |" in text
    assert "| review.json | review.json |" in text
    assert "`model-benchmark/example-model-1-core_2026-11-12` (summary.json, results/results.json)" \
        in text


def test_cli_with_explicit_inputs_matches_the_library_call(tmp_path, capsys):
    out = tmp_path / "report.md"
    assert cr.main(["--review", str(FIX / "review.json"), "--evidence", str(FIX / "evidence.jsonl"),
                    "--evals", str(FIX / "evals"), "--plan", str(FIX / "test-plan.json"),
                    "--criteria", str(FIX / "criteria.json"), "--out", str(out),
                    "--date", "2026-11-14"]) == 0
    text = out.read_text()
    assert text.split("## Inputs to this report")[0] == _report().split("## Inputs to this report")[0]
    capsys.readouterr()


def test_cli_fails_only_when_review_json_is_unreadable(tmp_path, capsys):
    bad = tmp_path / "review.json"
    bad.write_text("[]")
    assert cr.main(["--review", str(bad)]) == 1
    assert cr.main(["--review", str(tmp_path / "missing.json")]) == 1
    capsys.readouterr()


@pytest.mark.parametrize("value,text", [(None, "not stated"), ("", "not stated"), (True, "yes"),
                                        ([], "none"), (["a", "b"], "a, b"),
                                        ({"k": False}, "k: no")])
def test_show_never_hides_an_absent_value(value, text):
    assert cr.show(value) == text
