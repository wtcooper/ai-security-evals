"""Objective pack and config invariants. A wrong conversation token makes every attack
silently send empty input, so it is checked here."""
from __future__ import annotations

import json
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
OBJ = SKILL / "objectives"


def test_objectives_are_non_empty_unique_strings():
    goals = json.loads((OBJ / "redteam_objectives.json").read_text())
    assert len(goals) >= 50 and all(isinstance(g, str) and g.strip() for g in goals)
    assert len(goals) == len(set(goals))


def test_smoke_pack_is_a_small_subset_of_the_full_pack():
    full = set(json.loads((OBJ / "redteam_objectives.json").read_text()))
    smoke = json.loads((OBJ / "redteam_objectives.smoke.json").read_text())
    assert 1 <= len(smoke) <= 5 and set(smoke) <= full


def test_config_uses_the_prompt_token_and_never_a_messages_variable():
    text = (SKILL / "promptfooconfig.yaml").read_text()
    body_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert any(re.search(r"\{\{\s*prompt\s*\}\}", line) for line in body_lines)
    assert not any("{{messages}}" in line.replace(" ", "") for line in body_lines)


def test_config_references_only_files_that_ship_with_the_skill():
    text = (SKILL / "promptfooconfig.yaml").read_text()
    for ref in re.findall(r"file://([\w./-]+)", text):
        assert (SKILL / ref).exists(), f"config references missing {ref}"
