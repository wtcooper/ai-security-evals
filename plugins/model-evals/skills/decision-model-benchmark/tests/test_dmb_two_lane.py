"""The two-lane shape: threats.json, the declared case counts, the scorecard fields, the
deterministic `good` verdicts, and the known-lane importers on fixtures in the upstream
formats. Nothing here touches the network."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

import known_lane
import run_bench
import variants

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import scorecard  # noqa: E402

THREATS = json.loads((ROOT / "threats.json").read_text())
IDS = [t["id"] for t in THREATS["threats"]]
SEED = 20261114
PAGE_FIXTURE = ROOT / "tests" / "fixtures" / "deepset_rows_page.json"


def custom_requests(depth: str, repeats: int = 3) -> list[dict]:
    policies, cases = variants.load_corpus()
    d = run_bench.resolve_depth(depth)
    chosen = variants.select_cases(cases, d["cases"], SEED)
    return run_bench.build_requests(chosen, policies, SEED, d["mode"], variants.AXES, repeats,
                                    "clean")


def by_threat(requests: list[dict]) -> dict:
    out: dict = {}
    for r in requests:
        if r["threat"]:
            out[r["threat"]] = out.get(r["threat"], 0) + 1
    return out


# ---- threats.json and the declared counts ----------------------------------------------------

def test_threats_json_lists_four_to_seven_threats_with_both_lanes_named():
    assert 4 <= len(IDS) <= 7 and len(set(IDS)) == len(IDS)
    for t in THREATS["threats"]:
        assert t["id"].startswith("dm-") and t["id"] == t["id"].lower()
        assert t["name"] and t["risk_source"] and t["measures"]
        assert set(t["lanes"]) == {"known", "custom"}
        if not t["lanes"]["known"]:
            assert t.get("known_lane_note"), f"{t['id']}: say why the known lane is empty"
    known = {b for t in THREATS["threats"] for b in t["lanes"]["known"]}
    custom = {b for t in THREATS["threats"] for b in t["lanes"]["custom"]}
    assert known == set(known_lane.SOURCES) and len(known) <= 2
    assert custom == {run_bench.CUSTOM_BENCHMARK}


def test_every_threat_names_the_incidents_where_its_pattern_was_observed():
    import re
    for t in THREATS["threats"]:
        assert isinstance(t["observed_in"], list), t["id"]
        assert all(re.fullmatch(r"INC-\d{3}", i) for i in t["observed_in"]), t["id"]
    observed = {t["id"]: t["observed_in"] for t in THREATS["threats"]}
    assert observed["dm-injection"] == ["INC-005", "INC-007"]
    assert observed["dm-nondeterminism"] == []        # documented vendor behaviour, no incident


def test_the_custom_set_has_the_declared_counts_per_threat_at_every_depth():
    for depth in ("smoke", "standard", "full"):
        declared = THREATS["cases_per_arm"][depth]["custom"]
        assert by_threat(custom_requests(depth)) == declared, depth
    standard = THREATS["cases_per_arm"]["standard"]["custom"]
    assert all(n >= 10 for n in standard.values())          # about 10-20 or more per threat


def test_the_known_lane_declared_counts_follow_the_pinned_upstream_sizes():
    test = known_lane.SOURCES["deepset-prompt-injections"]["splits"]["test"]["rows"]
    train = known_lane.SOURCES["deepset-prompt-injections"]["splits"]["train"]["rows"]
    jev = known_lane.SOURCES["jevbench-original"]["rows"]
    smoke_rows, smoke_pairs = known_lane.KNOWN_DEPTH["smoke"]["deepset-prompt-injections"][1], \
        known_lane.KNOWN_DEPTH["smoke"]["jevbench-original"]
    expect = {
        "smoke": {"dm-fail-open": smoke_rows, "dm-perturbation": smoke_pairs,
                  "dm-nondeterminism": (smoke_rows + 2 * smoke_pairs) * 2},
        "standard": {"dm-fail-open": test, "dm-perturbation": jev // 2,
                     "dm-nondeterminism": (test + jev) * 2},
        "full": {"dm-fail-open": test + train, "dm-perturbation": jev // 2,
                 "dm-nondeterminism": (test + train + jev) * 2},
    }
    for depth, want in expect.items():
        assert THREATS["cases_per_arm"][depth]["known"] == want, depth


def test_every_request_maps_to_a_threat_in_threats_json():
    reqs = custom_requests("full") + run_bench.build_known_requests(
        known_lane.load("fixture", "standard", SEED)[0], 3)
    lanes = {(t["id"], lane): set(t["lanes"][lane]) for t in THREATS["threats"]
             for lane in ("known", "custom")}
    for r in reqs:
        if r["threat"] is None:                   # a JevBench anchor: scored on its pair row
            assert r["case"]["pair_role"] == "anchor" and r["repeat"] == 0
            continue
        assert r["threat"] in IDS
        assert r["benchmark"].split(":")[0] in lanes[(r["threat"], r["lane"])], r["benchmark"]
    assert set(run_bench.AXIS_THREAT.values()) <= set(IDS)
    assert {s["threat"] for s in known_lane.SOURCES.values()} <= set(IDS)
    assert run_bench.RERUN_THREAT in IDS
    # Case ids are unique within a benchmark, as the scorecard requires.
    keys = [(r["benchmark"], r["threat"], r["score_case"]) for r in reqs if r["threat"]]
    assert len(keys) == len(set(keys))


# ---- scorecard keys and the deterministic verdicts -------------------------------------------

def test_scorecard_keys_name_the_threat_and_a_stable_case():
    policies, cases = variants.load_corpus()
    allow = next(c for c in cases if c["policy"] == "tool_gate" and c["truth"] == "allow")
    pol = policies["tool_gate"]
    clean = variants.clean_variant(allow, pol)
    twin = variants.make_variant(allow, pol, "injection", "direct_command", SEED)
    rename = variants.make_variant(allow, pol, "option_rename", "misleading_permissive", SEED)
    pad = variants.make_variant(allow, pol, "padding", "log_lines", SEED)
    key = run_bench.scorecard_key
    assert key("custom", allow, clean, 0) == ("dm-fail-open", f"{allow['id']}/clean")
    assert key("custom", allow, clean, 2) == ("dm-nondeterminism", f"{allow['id']}/clean#r2")
    assert key("custom", allow, twin, 0) == ("dm-injection",
                                             f"{allow['id']}/injection_twin.direct_command")
    assert key("custom", allow, rename, 0)[0] == "dm-option-channel"
    assert key("custom", allow, pad, 0)[0] == "dm-perturbation"
    jev = known_lane.load("fixture", "standard", SEED, benchmarks=("jevbench-original",))[0]
    anchor, para = jev[0], jev[1]
    assert key("known", anchor, clean, 0) == (None, anchor["id"])
    assert key("known", para, clean, 0) == ("dm-perturbation", para["pair"])
    assert key("known", anchor, clean, 1) == ("dm-nondeterminism", anchor["id"] + "#r1")


def _row(seed_case, repeat, decision, truth, outcome="answered", lane="custom",
         variant="clean", **extra):
    return {"lane": lane, "benchmark": "b", "seed_case": seed_case, "variant": variant,
            "repeat": repeat, "outcome": outcome,
            "decision": decision if outcome == "answered" else None,
            "correct": (decision == truth) if outcome == "answered" else None,
            "good": None, **extra}


def test_finalize_scores_re_sends_against_the_first_send_and_pairs_on_both_phrasings():
    rows = [
        _row("c1", 0, "block", "block"), _row("c1", 1, "block", "block"),
        _row("c1", 2, "allow", "block"),                     # re-send changed: not good
        _row("c2", 0, "allow", "block"), _row("c2", 1, "allow", "block"),  # same wrong: good
        _row("c3", 0, None, "allow", outcome="refusal"), _row("c3", 1, "allow", "allow"),
        _row("p-0", 0, "yes", "yes", lane="known", pair_role="anchor", pair_anchor="p-0"),
        _row("p-1", 0, "yes", "yes", lane="known", pair_role="paraphrase", pair_anchor="p-0"),
        _row("q-0", 0, "no", "yes", lane="known", pair_role="anchor", pair_anchor="q-0"),
        _row("q-1", 0, "yes", "yes", lane="known", pair_role="paraphrase", pair_anchor="q-0"),
        _row("s-0", 0, "no", "no", lane="known", pair_role="anchor", pair_anchor="s-0"),
        _row("s-1", 0, None, "no", lane="known", outcome="error", pair_role="paraphrase",
             pair_anchor="s-0"),
    ]
    got = {(r["seed_case"], r["repeat"]): r for r in run_bench.finalize_rows(rows)}
    assert got[("c1", 1)]["good"] is True and got[("c1", 2)]["good"] is False
    assert got[("c2", 1)]["good"] is True                 # agreement, not correctness
    assert got[("c3", 1)]["good"] is None                 # first send unanswered: no verdict
    assert got[("p-1", 0)]["good"] is True and got[("p-1", 0)]["consistent"] is True
    assert got[("q-1", 0)]["good"] is False and got[("q-1", 0)]["consistent"] is False
    assert got[("s-1", 0)]["good"] is None and got[("s-1", 0)]["consistent"] is None
    assert got[("p-0", 0)]["good"] is None                # the anchor carries no verdict


# ---- known-lane importers on fixtures in the upstream formats --------------------------------

def test_deepset_rows_page_parses_and_a_truncated_cell_is_refused():
    page = json.loads(PAGE_FIXTURE.read_text())
    rows = known_lane.parse_rows_page(page)
    assert [r["row_idx"] for r in rows] == [0, 1, 2]
    assert {r["label"] for r in rows} == {0, 1}
    page["rows"][1]["truncated_cells"] = ["text"]
    with pytest.raises(known_lane.KnownSourceError, match="truncated"):
        known_lane.parse_rows_page(page)


def test_deepset_rows_become_yes_no_screen_cases():
    rows = known_lane.read_jsonl(known_lane.FIXTURE_DIR / "deepset-prompt-injections" / "test.jsonl")
    cases = known_lane.import_deepset(rows, "test")
    assert [c["id"] for c in cases[:2]] == ["test-0000", "test-0001"]
    for row, case in zip(rows, cases):
        assert case["truth"] == ("yes" if row["label"] == 1 else "no")
        assert case["error_class"] == ("fail_open" if row["label"] == 1 else "fail_closed")
        assert case["state"] == row["text"] and case["restrictive_labels"] == ["yes"]
        assert [o["label"] for o in case["question"]["options"]] == ["yes", "no"]
        assert case["threat"] == "dm-fail-open"
    with pytest.raises(known_lane.KnownSourceError):
        known_lane.import_deepset([{"text": "x", "label": 2}], "test")


def test_jevbench_records_become_canonical_pairs():
    path = known_lane.FIXTURE_DIR / "jevbench-original" / "original.jsonl"
    raw = known_lane.read_jsonl(path)
    cases = known_lane.import_jevbench(raw)
    assert len(cases) == len(raw) and len({c["pair"] for c in cases}) == len(raw) // 2
    by_id = {c["id"]: c for c in cases}
    noul = by_id["fixture-policy-01-0"]
    assert [o["label"] for o in noul["question"]["options"]] == ["yes", "no"]
    src = raw[0]["question"]["criteria"]
    assert noul["question"]["options"][0]["criteria"] == src["true"]
    assert noul["question"]["options"][1]["criteria"] == src["false"]
    choice = by_id["fixture-intent-01-1"]
    assert [o["label"] for o in choice["question"]["options"]] == \
        list(next(r for r in raw if r["id"] == "fixture-intent-01-1")["question"]["criteria"])
    score = by_id["fixture-ordinal-01-0"]
    assert [o["label"] for o in score["question"]["options"]] == ["0", "1", "2", "3"]
    assert score["truth"] == "2" and score["pair_role"] == "anchor"
    assert by_id["fixture-ordinal-01-1"]["pair_role"] == "paraphrase"
    broken = [dict(raw[0]), dict(raw[1], expected="yes")]        # the phrasings disagree
    with pytest.raises(known_lane.KnownSourceError, match="disagree"):
        known_lane.import_jevbench(broken)
    with pytest.raises(known_lane.KnownSourceError, match="members"):
        known_lane.import_jevbench([raw[0]])


def test_fixture_benchmarks_are_marked_so_they_never_mix_with_real_runs():
    cases, prov = known_lane.load("fixture", "smoke", SEED)
    assert {c["benchmark"] for c in cases} == {"deepset-prompt-injections:fixture",
                                               "jevbench-original:fixture"}
    assert prov["source"] == "fixture"
    deep = [c for c in cases if c["policy"] == "deepset-prompt-injections"]
    jev = [c for c in cases if c["policy"] == "jevbench-original"]
    assert sorted(c["truth"] for c in deep) == ["no"] * 3 + ["yes"] * 3   # balanced draw
    assert len(jev) == 6 and all(sum(o["pair"] == c["pair"] for o in jev) == 2 for c in jev)


def _fake_get(deepset_rows: list[dict], jevbench_bytes: bytes):
    def get(url: str, timeout: float) -> bytes:
        if "datasets-server" in url:
            offset = int(url.split("offset=")[1].split("&")[0])
            chunk = deepset_rows[offset: offset + known_lane.PAGE]
            return json.dumps({"rows": [{"row_idx": offset + i, "row": r, "truncated_cells": []}
                                        for i, r in enumerate(chunk)]}).encode()
        if "api/datasets" in url:
            return json.dumps({"sha": "0" * 40}).encode()
        assert known_lane.SOURCES["jevbench-original"]["revision"] in url
        return jevbench_bytes
    return get


def test_fetch_checks_the_pinned_hash_saves_a_copy_and_the_copy_reloads(tmp_path, monkeypatch):
    rows = known_lane.read_jsonl(known_lane.FIXTURE_DIR / "deepset-prompt-injections" / "test.jsonl")
    jev = (known_lane.FIXTURE_DIR / "jevbench-original" / "original.jsonl").read_bytes()
    get = _fake_get(rows, jev)
    # The real pin does not match the fixture: the fetch is refused.
    with pytest.raises(known_lane.KnownSourceError, match="pinned revision"):
        known_lane.load("fetch", "standard", SEED, tmp_path / "a", get=get)
    # Pin the fixture's own hashes and the same path succeeds.
    deep = dict(known_lane.SOURCES["deepset-prompt-injections"])
    deep["splits"] = {"test": {"rows": len(rows), "sha256": known_lane.deepset_hash(rows)}}
    jb = dict(known_lane.SOURCES["jevbench-original"], sha256=hashlib.sha256(jev).hexdigest())
    monkeypatch.setitem(known_lane.SOURCES, "deepset-prompt-injections", deep)
    monkeypatch.setitem(known_lane.SOURCES, "jevbench-original", jb)
    saved = tmp_path / "known"
    cases, prov = known_lane.load("fetch", "standard", SEED, saved, get=get)
    assert {c["benchmark"] for c in cases} == {"deepset-prompt-injections", "jevbench-original"}
    assert prov["benchmarks"]["deepset-prompt-injections"]["hub_revision_now"] == "0" * 40
    assert (saved / "jevbench-original" / "original.jsonl").read_bytes() == jev
    again, _ = known_lane.load(str(saved), "standard", SEED)
    assert [c["id"] for c in again] == [c["id"] for c in cases]
    # A saved copy that was edited no longer matches the pin.
    edited = saved / "deepset-prompt-injections" / "test.jsonl"
    edited.write_text(edited.read_text().replace("Varden", "Vardon", 1))
    with pytest.raises(known_lane.KnownSourceError):
        known_lane.load(str(saved), "standard", SEED)


# ---- the scorecard on a keyless run ----------------------------------------------------------

def test_a_keyless_run_feeds_the_scorecard_in_both_lanes(tmp_path, capsys):
    out = tmp_path / "smoke"
    assert run_bench.main(["--mock", "--depth", "smoke", "--out", str(out)]) == 0
    rows = [json.loads(l) for l in (out / "samples.jsonl").read_text().splitlines()]
    for r in rows:
        assert {"arm", "threat", "lane", "benchmark", "case", "good"} <= set(r)
        assert r["lane"] in ("known", "custom") and r["good"] in (True, False, None)
        assert r["threat"] in IDS or (r["threat"] is None and r["pair_role"] == "anchor")
    nondet = [r for r in rows if r["threat"] == "dm-nondeterminism"]
    assert nondet and all(r["good"] is True for r in nondet)   # the mock is deterministic
    capsys.readouterr()
    assert scorecard.main(["--threats", str(ROOT / "threats.json"), "--samples",
                           str(out / "samples.jsonl"), "--out", str(out)]) == 0
    card = json.loads((out / "scorecard.json").read_text())
    assert set(card["models"]) == {"mock-a", "mock-b", "mock-a-gemini"}
    measured = {(r["threat"], r["lane"]) for r in card["rows"]}
    for t in THREATS["threats"]:
        for lane in ("known", "custom"):
            assert ((t["id"], lane) in measured) == bool(t["lanes"][lane]), (t["id"], lane)
    # Every planned lane ran and every threat has a benchmark, so nothing is reported missing;
    # a threat measured in one lane by design is not a gap.
    assert card["coverage"] == []
    text = (out / "scorecard.md").read_text()
    assert "## Scorecard" in text and "## Ordering" in text
