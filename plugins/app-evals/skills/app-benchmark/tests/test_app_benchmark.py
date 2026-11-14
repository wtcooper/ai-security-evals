"""The bundled corpus and config are what every app-benchmark run depends on."""
from __future__ import annotations

import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CORPUS = sorted((SKILL / "corpus").glob("*.json"))


def _cases():
    return [c for path in CORPUS for c in json.loads(path.read_text())]


def test_corpus_has_attack_and_benign_sets():
    names = {p.name for p in CORPUS}
    assert {"injection.json", "harmful.json", "data_leakage.json",
            "benign_overrefusal.json"} <= names


def test_every_case_is_gradable_and_tagged():
    cases = _cases()
    assert len(cases) > 1000
    for case in cases:
        assert case["vars"]["prompt"].strip()
        assert case["assert"], "a case with no assertion cannot be scored"
        meta = case["metadata"]
        for key in ("id", "type", "category", "license"):
            assert meta.get(key), f"{meta.get('id')}: missing {key}"
        # attacks are reported by technique; benign cases have none
        if meta["category"] != "benign":
            assert meta.get("technique_family"), f"{meta['id']}: missing technique_family"


def test_case_ids_are_unique():
    ids = [c["metadata"]["id"] for c in _cases()]
    assert len(ids) == len(set(ids))


def test_benign_cases_exist_so_over_refusal_is_measured():
    benign = json.loads((SKILL / "corpus" / "benign_overrefusal.json").read_text())
    assert len(benign) > 50


def test_config_references_only_files_that_ship_with_the_skill():
    for config in SKILL.glob("promptfooconfig*.yaml"):
        for ref in re.findall(r"file://([\w./-]+)", config.read_text()):
            assert (SKILL / ref).exists(), f"{config.name} references missing {ref}"
