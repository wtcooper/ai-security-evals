"""criteria.json: the shipped template carries no value, and the tool never supplies one."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
import criteria as cj  # noqa: E402
import expread  # noqa: E402

TEMPLATE = json.loads((SKILL / "criteria.template.json").read_text())
EXAMPLE = json.loads((SKILL / "examples" / "criteria.example.json").read_text())
NUMERIC_TEXT = re.compile(r"^\s*[<>=≤≥]*\s*\d+([.,]\d+)?\s*%?\s*$")


def numeric_values(node, path="") -> list[str]:
    """Paths of every number, or string that is just a number, in a criteria document.
    `schema_version` is the file format's version, not a criterion."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            if path == "" and key == "schema_version":
                continue
            found += numeric_values(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += numeric_values(value, f"{path}[{i}]")
    elif isinstance(node, bool):
        pass
    elif isinstance(node, (int, float)):
        found.append(path)
    elif isinstance(node, str) and NUMERIC_TEXT.match(node):
        found.append(path)
    return found


def _criterion(**over):
    c = copy.deepcopy(EXAMPLE["criteria"][0])
    for dotted, value in over.items():
        cur = c
        parts = dotted.split("__")
        for part in parts[:-1]:
            cur = cur[part]
        cur[parts[-1]] = value
    return c


def _numeric(value=0.123, applies_to="interval_upper", kind="at_most"):
    """A criterion with a number in it. 0.123 is an arbitrary test value, not a suggestion."""
    return _criterion(bound={"type": kind, "value": value, "applies_to": applies_to,
                             "reference": None})


def _exp(tmp_path, skill, name, rows, created="2026-11-12T09:00:00Z", context=None):
    folder = tmp_path / skill / name
    (folder / "results").mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps(
        {"skill": skill, "label": name, "created": created, "context": context or {}}))
    (folder / "summary.md").write_text("# summary\n")
    (folder / "results" / "results.json").write_text(json.dumps({"rows": rows}))
    return folder


def _row(check, value, n, arm="m", **kw):
    return {"check": check, "arm": arm, "value": value, "ci95": [max(0, value - 0.05),
            min(1, value + 0.05)], "samples_completed": n, "status": "ok", **kw}


# --- the shipped files carry no values -----------------------------------------------------------

def test_shipped_template_contains_no_numeric_criterion_value():
    assert numeric_values(TEMPLATE) == [], (
        "criteria.template.json must ship empty: this repo sets no acceptance values")
    assert TEMPLATE["criteria"] == [] and TEMPLATE["no_criterion"] == []


def test_the_detector_catches_a_planted_value_in_any_form():
    for planted in (0.9, 90, "0.9", "90%", ">= 0.95", " 5 "):
        doc = copy.deepcopy(TEMPLATE)
        doc["criteria"].append({"id": "C1", "bound": {"type": "at_least", "value": planted}})
        assert numeric_values(doc) == ["criteria[0].bound.value"], planted
    doc = copy.deepcopy(TEMPLATE)
    doc["default_minimum"] = 0.8
    assert numeric_values(doc) == ["default_minimum"]
    assert numeric_values({"schema_version": 1, "set_on": "2026-11-10", "ok": True}) == []


def test_bundled_example_and_runbook_carry_no_numeric_bound():
    for c in EXAMPLE["criteria"]:
        assert c["bound"]["value"] is None, "the example must not model a cut-off"
        assert c["bound"]["type"] in ("no_worse_than_reference", "qualitative")
    text = (SKILL / "SKILL.md").read_text()
    assert not re.search(r"--value\s+[\d.]", text)
    assert not re.search(r'"value":\s*[\d.]', text)


def test_bundled_example_validates():
    result = cj.validate(EXAMPLE)
    assert result["errors"] == [] and result["criteria"] == 2
    assert any("C2" in w and "after" in w for w in result["warnings"])


# --- validation: who, when, before or after ---------------------------------------------------------

@pytest.mark.parametrize("over,fragment", [
    ({"set_by": ""}, "who set it"),
    ({"set_on": "last week"}, "YYYY-MM-DD"),
    ({"set_on": (dt.date.today() + dt.timedelta(days=3)).isoformat()}, "future"),
    ({"set_relative_to_results": None}, '"before" or "after"'),
    ({"set_relative_to_results": "during"}, '"before" or "after"'),
    ({"statement": " "}, "own words"),
    ({"measure": {"skill": "model-benchmark"}}, "benchmark or metric"),
    ({"bound__type": "roughly"}, "bound.type"),
    ({"bound__reference": ""}, "bound.reference"),
    ({"bound__value": 0.123}, "must be null"),
])
def test_criterion_rules(over, fragment):
    errs, _ = cj.check_criterion(_criterion(**over))
    assert any(fragment in e for e in errs), errs


def test_numeric_bound_needs_the_organisations_number_and_where_it_is_read():
    assert cj.check_criterion(_numeric())[0] == []
    assert any("this tool supplies none" in e for e in cj.check_criterion(_numeric(None))[0])
    assert any("must be a number" in e for e in cj.check_criterion(_numeric("0.123"))[0])
    assert any("must be a number" in e for e in cj.check_criterion(_numeric(True))[0])
    assert any("applies_to" in e for e in cj.check_criterion(_numeric(applies_to=None))[0])


def test_value_that_looks_like_a_percentage_is_a_warning():
    errs, warns = cj.check_criterion(_numeric(12.3))
    assert errs == [] and any("outside 0..1" in w for w in warns)


def test_after_results_is_recorded_and_warned_never_rejected():
    errs, warns = cj.check_criterion(_criterion(set_relative_to_results="after"))
    assert errs == [] and any("weaker evidence" in w for w in warns)


def test_missing_error_costs_is_a_warning():
    errs, warns = cj.check_criterion(_criterion(error_costs={"if_too_lenient": "x"}))
    assert errs == [] and any("error_costs" in w for w in warns)


def test_document_level_checks():
    doc = {"schema_version": 1, "criteria": [_criterion(), _criterion()],
           "no_criterion": [{"dimension": "x"}]}
    result = cj.validate(doc)
    assert any("duplicate id" in e for e in result["errors"])
    assert any("no_criterion 1" in e for e in result["errors"])
    assert cj.validate({"schema_version": 2, "criteria": []})["errors"] == [
        "schema_version must be 1"]
    assert cj.validate([])["errors"] and cj.validate({"schema_version": 1})["errors"]


def test_before_claim_is_cross_checked_against_experiment_dates(tmp_path):
    folder = _exp(tmp_path, "model-benchmark", "subject_2026-11-12", [_row("agentdojo", 0.2, 100)])
    exps = [expread.read_experiment(folder)]
    late = {"schema_version": 1, "criteria": [_criterion(set_on="2026-11-13")]}
    assert any("confirm which results had been seen" in w
               for w in cj.validate(late, exps)["warnings"])
    early = {"schema_version": 1, "criteria": [_criterion(set_on="2026-11-10")]}
    assert not any("confirm" in w for w in cj.validate(early, exps)["warnings"])
    other_skill = {"schema_version": 1, "criteria": [
        _criterion(set_on="2026-11-13", measure={"skill": "app-benchmark", "benchmark": "x"})]}
    assert not any("confirm" in w for w in cj.validate(other_skill, exps)["warnings"])


# --- init / add / decline -------------------------------------------------------------------------------

def test_init_starts_empty_and_never_overwrites(tmp_path):
    out = tmp_path / "criteria.json"
    review = {"review_id": "r-1", "subject": {"name": "m", "version": "v2"}}
    doc = cj.init(out, review)
    assert doc["criteria"] == [] and doc["review_id"] == "r-1" and doc["subject"] == "m v2"
    assert numeric_values(json.loads(out.read_text())) == []
    with pytest.raises(ValueError):
        cj.init(out, review)


def test_add_records_only_what_was_given_and_rejects_duplicates(tmp_path, capsys):
    path = tmp_path / "criteria.json"
    cj.init(path, None)
    base = ["add", "--file", str(path), "--dimension", "injection via tools",
            "--skill", "model-benchmark", "--benchmark", "agentdojo",
            "--statement", "ours", "--set-by", "CISO", "--timing", "before"]
    # A numeric bound with no --value: the tool has no default to fall back on.
    assert cj.main([*base, "--id", "C1", "--bound-type", "at_most",
                    "--applies-to", "interval_upper"]) == 1
    assert json.loads(path.read_text())["criteria"] == []
    assert cj.main([*base, "--id", "C1", "--bound-type", "at_most", "--value", "0.123",
                    "--applies-to", "interval_upper"]) == 0
    assert cj.main([*base, "--id", "C1", "--bound-type", "qualitative"]) == 1
    assert cj.main([*base, "--id", "C2", "--bound-type", "qualitative"]) == 0
    doc = json.loads(path.read_text())
    assert [c["id"] for c in doc["criteria"]] == ["C1", "C2"]
    c1 = doc["criteria"][0]
    assert c1["bound"]["value"] == 0.123 and c1["set_by"] == "CISO"
    assert c1["set_relative_to_results"] == "before"
    assert c1["set_on"] == dt.date.today().isoformat()
    assert doc["criteria"][1]["bound"]["value"] is None
    assert cj.main(["decline", "--file", str(path), "--dimension", "insecure code",
                    "--reason", "informational", "--decided-by", "CISO"]) == 0
    assert cj.main(["validate", str(path)]) == 0
    capsys.readouterr()


def test_add_requires_timing_on_the_command_line(tmp_path, capsys):
    path = tmp_path / "criteria.json"
    cj.init(path, None)
    with pytest.raises(SystemExit):
        cj.main(["add", "--file", str(path), "--id", "C1", "--dimension", "d", "--skill", "s",
                 "--benchmark", "b", "--statement", "x", "--bound-type", "qualitative",
                 "--set-by", "CISO"])
    capsys.readouterr()


# --- worksheet ---------------------------------------------------------------------------------------------

PLAN = {"threats": [
    {"threat": "agent-goal-hijack", "applies": True, "benchmarks": [
        {"id": "agentdojo", "skill": "model-benchmark", "depth": "standard", "samples": 100,
         "reads_as": "share of agent episodes where the injected goal was EXECUTED",
         "direction": "lower_is_better", "note": "Read next to utility.",
         "subject_note": "Bare API baseline only."}]},
    {"threat": "tool-misuse", "applies": False, "benchmarks": [
        {"id": "ruled_out", "skill": "x", "depth": "standard", "samples": 10}]},
]}
REVIEW = {"failure_impact": {"worst_case": "credentials leave", "affected": "developers",
                             "reversible": False, "detection": "code review"}}


def test_interval_width_comes_from_the_wilson_interval():
    assert cj.halfwidth_pp(0.5, 100) == 9.6
    assert cj.halfwidth_pp(0.5, 25) > 18 > cj.halfwidth_pp(0.5, 1000)


def test_worksheet_explains_the_number_the_interval_and_the_error_costs():
    text = cj.worksheet(PLAN, REVIEW, [], [], False, today="2026-11-14")
    assert "## `agentdojo` — model-benchmark" in text and "ruled_out" not in text
    assert "share of agent episodes where the injected goal was EXECUTED" in text
    assert "A lower value is better for the defender." in text
    assert "Bare API baseline only." in text
    assert "With 100 tests (as planned at depth `standard`)" in text and "±9.6" in text
    assert "If the criterion is too lenient" in text and "If the criterion is too strict" in text
    assert "credentials leave" in text and "Reversible: no" in text
    assert "contains no suggested value" in text


def test_worksheet_hides_the_subjects_results_unless_asked(tmp_path):
    subject = expread.read_experiment(_exp(
        tmp_path, "model-benchmark", "subject_2026-11-12", [_row("agentdojo", 0.137, 64)]))
    hidden = cj.worksheet(PLAN, REVIEW, [], [subject], False)
    assert "0.137" not in hidden and "`--timing before`" in hidden
    assert "With 64 tests (as run)" in hidden, "the n actually run replaces the planned n"
    shown = cj.worksheet(PLAN, REVIEW, [], [subject], True)
    assert "0.137 [0.087–0.187] n=64" in shown
    assert "must be recorded with `--timing after`" in shown


def test_worksheet_offers_the_organisations_own_results_as_reference_points(tmp_path):
    ref = expread.read_experiment(_exp(
        tmp_path, "model-benchmark", "current-model_2026-10-20",
        [_row("agentdojo", 0.21, 100, arm="current-model"), _row("cyse4_mitre", 0.9, 100)],
        created="2026-10-20T10:00:00Z", context={"surface": "api", "harness": "none"}))
    text = cj.worksheet(PLAN, REVIEW, [ref], [], False)
    block = text.split("**Your own reference points.**")[1].split("**The organisation's")[0]
    assert "agentdojo · current-model" in block and "0.210 [0.160–0.260] n=100" in block
    assert "current-model_2026-10-20" in block and "surface: api; harness: none" in block
    assert "cyse4_mitre" not in block
    assert "same depth and seed" in block
    none = cj.worksheet(PLAN, REVIEW, [], [], False)
    assert "None found in the reference folders given" in none


def test_worksheet_with_nothing_measured_says_so():
    text = cj.worksheet({"threats": []}, None, [], [], False)
    assert "No measured dimension was found" in text


def test_worksheet_adds_dimensions_measured_but_missing_from_the_plan(tmp_path):
    subject = expread.read_experiment(_exp(
        tmp_path, "app-benchmark", "s_2026-11-12", [_row("app_corpus_injection", 0.3, 80)]))
    text = cj.worksheet(None, None, [], [subject], False)
    assert "## `app_corpus_injection` — app-benchmark" in text
    assert "direction of this number is not recorded" in text
