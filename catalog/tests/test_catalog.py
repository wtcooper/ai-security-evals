"""Catalogue cross-checks. These read files in several places on purpose: a skill may not
look outside its own folder, so the checks that span folders live here."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "catalog" / "benchmarks.json"
CATALOG = json.loads(CATALOG_PATH.read_text())
ENTRIES = CATALOG["benchmarks"]
BY_ID = {e["id"]: e for e in ENTRIES}
REVIEW_SKILLS = ROOT / "plugins" / "ai-review" / "skills"

# model-benchmark's suite has lived under more than one name; take the first that exists.
SUITE_PATHS = ("plugins/model-evals/skills/model-benchmark/suite.py",
               "plugins/model-evals/skills/model-benchmark/lib/inspect_suite.py",
               "tools/lib/inspect_suite.py")

REQUIRED = ("id", "name", "skill", "status", "subjects", "engine", "threats", "tier",
            "needs_judge", "needs_sandbox", "calls_per_sample", "dataset_size", "licence",
            "verified", "verified_from", "source", "note")
SUBJECTS = {"model", "agent", "app", "decision-model", "voice-model", "image-model", "feature"}


def _load_suite():
    for rel in SUITE_PATHS:
        path = ROOT / rel
        if path.is_file():
            spec = importlib.util.spec_from_file_location("catalog_suite_under_test", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module      # dataclasses needs the module registered
            spec.loader.exec_module(module)
            return module, rel
    pytest.fail(f"model-benchmark suite not found at any of {SUITE_PATHS}")


def test_every_suite_check_is_in_the_catalogue_with_matching_facts():
    suite, rel = _load_suite()
    assert len(suite.CHECKS) >= 11, f"{rel} lists fewer checks than the catalogue was seeded from"
    for check in suite.CHECKS:
        assert check.id in BY_ID, f"{check.id} is in {rel} but not in catalog/benchmarks.json"
        entry = BY_ID[check.id]
        assert entry["skill"] == "model-benchmark" and entry["engine"] == "inspect"
        assert entry["status"] == "available" and entry["verified"] is True
        got = {k: entry.get(k) for k in ("dataset_size", "calls_per_sample", "needs_judge",
                                         "metric_key", "direction")}
        want = {"dataset_size": check.dataset_size, "calls_per_sample": check.calls_per_sample,
                "needs_judge": check.needs_judge, "metric_key": check.metric_key,
                "direction": check.direction}
        assert got == want, f"{check.id} drifted from {rel}"


def test_no_catalogue_entry_claims_a_model_benchmark_check_the_suite_lacks():
    suite, rel = _load_suite()
    ids = {c.id for c in suite.CHECKS}
    stale = [e["id"] for e in ENTRIES if e["skill"] == "model-benchmark"
             and e["engine"] == "inspect" and e["status"] == "available" and e["id"] not in ids]
    assert not stale, f"available in the catalogue but not in {rel}: {stale}"


def test_entries_have_every_field_and_values_from_the_closed_lists():
    assert len(BY_ID) == len(ENTRIES), "duplicate ids"
    for e in ENTRIES:
        missing = [k for k in REQUIRED if k not in e]
        assert not missing, f"{e.get('id')}: missing {missing}"
        assert e["status"] in ("available", "planned", "candidate"), e["id"]
        assert e["engine"] in ("inspect", "promptfoo", "pyrit", "custom"), e["id"]
        assert e["tier"] in ("T0", "T1", "T2", None), e["id"]
        if e["status"] != "candidate":
            assert e["tier"] is not None, f"{e['id']}: tier is required unless candidate"
        assert e["subjects"] and set(e["subjects"]) <= SUBJECTS, e["id"]
        assert isinstance(e["verified"], bool), e["id"]
        for key in ("needs_judge", "needs_sandbox"):
            assert e[key] in (True, False, None), f"{e['id']}.{key}"
        for key in ("calls_per_sample", "dataset_size"):
            assert e[key] is None or (isinstance(e[key], int) and e[key] > 0), f"{e['id']}.{key}"
        assert e["source"] is None or e["source"].startswith("https://"), e["id"]
        assert e["note"].strip(), f"{e['id']}: note is empty"


def test_verified_entries_say_where_the_facts_were_read():
    for e in ENTRIES:
        if e["verified"]:
            assert e["verified_from"], f"{e['id']}: verified without verified_from"
        else:
            assert not e["verified_from"], f"{e['id']}: verified_from on an unverified entry"


def test_available_entries_name_a_skill_that_exists():
    skills = {p.name for p in ROOT.glob("plugins/*/skills/*") if p.is_dir()}
    for e in ENTRIES:
        if e["status"] == "available":
            assert e["skill"] in skills, f"{e['id']}: skill {e['skill']} is not in plugins/"


def test_threat_ids_exist_in_the_threat_registry():
    registry = json.loads((REVIEW_SKILLS / "review-threat-model" / "references"
                           / "threats.json").read_text())
    known = {t["id"] for t in registry["threats"]}
    for e in ENTRIES:
        assert e["threats"], f"{e['id']}: bears on no threat"
        assert set(e["threats"]) <= known, f"{e['id']}: unknown threat {set(e['threats']) - known}"


def test_copy_inside_review_threat_model_is_identical():
    copy = REVIEW_SKILLS / "review-threat-model" / "catalog.json"
    assert copy.read_text() == CATALOG_PATH.read_text(), (
        "review-threat-model/catalog.json differs from catalog/benchmarks.json: copy it over")


def test_catalogue_holds_no_scores_or_acceptance_values():
    banned = {"threshold", "pass_mark", "target", "acceptable", "minimum", "maximum", "score"}
    for e in ENTRIES:
        assert not banned & set(e), f"{e['id']}: {banned & set(e)}"


def test_experiment_reader_copies_in_criteria_and_report_are_identical():
    """review-criteria and review-report each ship the same reader for experiment folders."""
    a = REVIEW_SKILLS / "review-criteria" / "scripts" / "expread.py"
    b = REVIEW_SKILLS / "review-report" / "scripts" / "expread.py"
    assert a.read_text() == b.read_text()
