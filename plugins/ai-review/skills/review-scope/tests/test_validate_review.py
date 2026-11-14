"""review.json validation: what is an error, what is missing, what is honestly unknown."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "lib"))
import evalkit  # noqa: E402
import validate_review as vr  # noqa: E402

EXAMPLE = json.loads((SKILL / "examples" / "review.example.json").read_text())


def _doc(**changes):
    doc = copy.deepcopy(EXAMPLE)
    for dotted, value in changes.items():
        cur = doc
        parts = dotted.split("__")
        for part in parts[:-1]:
            cur = cur[int(part)] if part.isdigit() else cur[part]
        cur[parts[-1]] = value
    return doc


def test_bundled_example_is_complete():
    f = vr.validate(EXAMPLE)
    assert (f.errors, f.missing, f.unknown) == ([], [], [])


def test_context_uses_exactly_the_keys_measurement_skills_copy():
    """load_context() silently drops any other key, so an extra key is an error here."""
    assert set(vr.blank()["context"]) == set(evalkit.CONTEXT_KEYS)
    assert set(EXAMPLE["context"]) == set(evalkit.CONTEXT_KEYS)
    doc = _doc()
    doc["context"]["deployment"] = "prod"
    assert any("context.deployment" in e for e in vr.validate(doc).errors)


def test_context_round_trips_through_load_context(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(EXAMPLE))
    assert evalkit.load_context(str(path)) == EXAMPLE["context"]


def test_blank_profile_lists_every_required_answer_as_missing_not_as_error():
    f = vr.validate(vr.blank("agent"))
    assert f.errors == []
    for needed in ("review_id", "subject.name", "subject.weights.open", "context.surface",
                   "context.tools", "context.safeguards", "input_channels[0].untrusted",
                   "capabilities.can_do", "failure_impact.worst_case",
                   "time_budget.hours_available"):
        assert needed in f.missing
    assert any(m.startswith("out_of_scope") for m in f.missing)


def test_empty_list_is_an_answer_but_an_absent_key_is_not():
    assert vr.validate(_doc(context__tools=[], capabilities__can_do=[])).missing == []
    assert "context.tools" in vr.validate(_doc(context__tools=None)).missing


def test_unknown_is_valid_and_reported_separately():
    doc = _doc(context__safeguards="unknown", failure_impact__reversible="unknown",
               subject__weights={"open": "unknown", "repo": None})
    f = vr.validate(doc)
    assert f.errors == [] and f.missing == []
    assert set(f.unknown) == {"context.safeguards", "failure_impact.reversible",
                              "subject.weights.open"}


def test_closed_lists_and_types_are_errors():
    f = vr.validate(_doc(subject__type="chatbot", opened="10/11/2026",
                         time_budget__hours_available=-1, input_channels__0__untrusted="no"))
    joined = "\n".join(f.errors)
    for fragment in ("subject.type", "opened", "time_budget.hours_available",
                     "input_channels[0].untrusted"):
        assert fragment in joined


def test_feature_subject_needs_a_feature_kind_and_no_weights_answer():
    doc = _doc(subject__type="feature", subject__feature=None)
    del doc["subject"]["weights"]
    f = vr.validate(doc)
    assert f.missing == ["subject.feature"] and f.errors == []
    assert vr.validate(_doc(subject__type="feature", subject__feature="telepathy")).errors


def test_harness_version_required_only_when_there_is_a_harness():
    assert "context.harness_version" in vr.validate(_doc(context__harness_version=None)).missing
    bare = _doc(context__harness="none", context__harness_version=None)
    assert vr.validate(bare).missing == []


def test_open_weights_need_a_repo():
    f = vr.validate(_doc(subject__weights={"open": True, "repo": None}))
    assert f.missing == ["subject.weights.repo"]


def test_warnings_ask_questions_without_failing():
    f = vr.validate(_doc(context__tools=[], input_channels=[
        {"channel": "prompt", "controlled_by": "employee", "untrusted": False}]))
    assert len(f.warnings) == 2 and not f.errors and not f.missing


@pytest.mark.parametrize("args,code", [([], 0), (["--strict"], 0), (["--json"], 0)])
def test_cli_exit_codes_on_complete_file(tmp_path, capsys, args, code):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(EXAMPLE))
    assert vr.main([str(path), *args]) == code
    capsys.readouterr()


def test_cli_exits_1_on_gaps_and_strict_unknowns_and_2_on_bad_json(tmp_path, capsys):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(_doc(reviewer="")))
    assert vr.main([str(path)]) == 1
    assert "reviewer" in capsys.readouterr().out
    path.write_text(json.dumps(_doc(context__autonomy="unknown")))
    assert vr.main([str(path)]) == 0
    assert vr.main([str(path), "--strict"]) == 1
    path.write_text("{not json")
    assert vr.main([str(path)]) == 2
    capsys.readouterr()
