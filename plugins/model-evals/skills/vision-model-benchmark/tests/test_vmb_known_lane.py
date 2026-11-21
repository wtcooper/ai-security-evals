"""Known-lane importers on tiny fixtures in each benchmark's real upstream layout."""
import json
import re

import pytest

import known_lane
import vmb_core as core

UPSTREAM_KEYS = {"id", "system_prompt", "user_input_text", "image_description", "image_text",
                 "judge_question", "injection_technique", "injection_type", "risk_category"}


def test_revisions_are_pinned():
    for src in (core.CYSE3, core.FIGSTEP):
        assert re.fullmatch(r"[0-9a-f]{40}", src["revision"])
        assert "MIT" in src["license"]
    assert len(core.CYSE3["test_cases_sha256"]) == 64 and len(core.FIGSTEP["csv_sha256"]) == 64


def test_cyse3_fixture_is_in_upstream_format_and_splits_by_threat():
    d = known_lane.cyse3_dir("fixture", None)
    records = known_lane.cyse3_records("fixture", d)
    assert all(set(r) == UPSTREAM_KEYS for r in records)
    split = core.cyse3_split(records)
    assert {k: len(v) for k, v in split.items()} == {"secret": 3, "indirect": 2, "direct": 3,
                                                     "unclassified": 0}
    assert core.cyse3_secret(records[0]) == "Fx7Qm2"
    captcha = next(r for r in records if "CAPTCHA" in r["system_prompt"])
    assert core.cyse3_secret(captcha) is None and captcha in split["direct"]
    assert core.cyse3_split([{"id": 9, "risk_category": "other"}])["unclassified"]


def test_cyse3_spec_keeps_upstream_messages_and_judge_question():
    d = known_lane.cyse3_dir("fixture", None)
    rec = known_lane.cyse3_records("fixture", d)[0]
    img = known_lane.cyse3_image("fixture", d, rec["id"])
    spec = core.cyse3_spec(rec, str(img), "secret")
    assert img.is_file() and spec["id"] == "cyse3-0"
    assert spec["system"] == rec["system_prompt"] and spec["user"] == rec["user_input_text"]
    assert spec["meta"]["judge_question"] == rec["judge_question"]
    assert spec["meta"]["secret"] == "Fx7Qm2"


def test_figstep_fixture_filters_topics_and_finds_images():
    d = known_lane.figstep_dir("fixture", None)
    text = known_lane.figstep_csv("fixture", d)
    rows = core.figstep_rows(text)
    assert len(rows) == 7 and "Legal Opinion" not in {r["category_name"] for r in rows}
    assert len(core.figstep_rows(text, topics=("Legal Opinion",))) == 1
    img = known_lane.figstep_image("fixture", d, rows[0])
    assert img.is_file() and img.name == "query_ForbidQI_1_1_6.png"
    image, typed = core.figstep_spec(rows[0], str(img), "image"), core.figstep_spec(rows[0], None,
                                                                                   "text")
    assert image["id"] == typed["id"] == "figstep-1-1"
    assert image["user"] == core.FIGSTEP_PROMPT and image["image"]
    assert typed["user"] == rows[0]["question"] and typed["image"] is None
    assert image["request"] == typed["request"] == rows[0]["question"]


def test_figstep_column_change_is_refused():
    with pytest.raises(ValueError):
        core.figstep_rows("dataset,question\nForbidQI,x\n")


def test_download_verifies_the_pinned_hash(tmp_path, monkeypatch):
    payload = b"changed upstream"

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return payload
    monkeypatch.setattr(known_lane.urllib.request, "urlopen", lambda *a, **k: Resp())
    with pytest.raises(ValueError):
        known_lane._download("https://example.invalid/x", tmp_path / "x.json", "0" * 64)
    assert not (tmp_path / "x.json").exists()
    out = known_lane._download("https://example.invalid/y", tmp_path / "y.json")
    assert out.read_bytes() == payload


def test_prepared_specs_never_mix_fixture_and_fetched_provenance():
    assert known_lane.provenance("fixture")["source"] == "fixture"
    fetched = known_lane.provenance("fetch")
    assert fetched["cyse3"]["revision"] == core.CYSE3["revision"]
    assert json.dumps(fetched)  # serialisable into results.json
