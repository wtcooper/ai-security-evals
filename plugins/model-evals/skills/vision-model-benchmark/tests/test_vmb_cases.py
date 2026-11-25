"""The custom core set: counts, threat mapping and the properties that keep scoring honest."""
import json
import re
from collections import Counter

import vmb_core as core

THREATS = json.loads((core.SKILL_DIR / "threats.json").read_text())["threats"]
THREAT_IDS = {t["id"] for t in THREATS}


def test_threats_file_shape_and_lane_ids():
    assert 4 <= len(THREATS) <= 7
    for t in THREATS:
        assert t["id"].startswith("vi-") and t["name"] and t["risk_source"] and t["measures"]
        for lane in ("known", "custom"):
            for bench in t["lanes"][lane]:
                assert core.BENCHMARKS[bench] == (t["id"], lane), bench
    known = [b for t in THREATS for b in t["lanes"]["known"]]
    assert len({b.split("_")[0] for b in known}) <= 2      # at most two published benchmarks
    listed = {b for t in THREATS for lane in t["lanes"].values() for b in lane}
    assert listed == {b for b, (_, lane) in core.BENCHMARKS.items() if lane != "baseline"}
    assert any(not t["lanes"]["known"] and not t["lanes"]["custom"] for t in THREATS)


def test_custom_set_has_the_declared_counts():
    cases = core.custom_cases()
    assert {b: len(v) for b, v in cases.items()} == core.CUSTOM_COUNTS
    assert all(10 <= n <= 20 for n in core.CUSTOM_COUNTS.values())


def test_every_case_maps_to_a_threat_and_its_benchmark():
    ids = []
    for bench, cases in core.custom_cases().items():
        threat, lane = core.BENCHMARKS[bench]
        assert lane == "custom" and threat in THREAT_IDS
        for c in cases:
            assert c["threat"] == threat
            assert bench in next(t for t in THREATS if t["id"] == threat)["lanes"]["custom"]
            ids.append(c["id"])
    assert len(ids) == len(set(ids))


def test_injected_canary_cannot_be_read_off_the_image():
    for c in core.load_cases():
        text = core.image_text(c)
        assert core.answer_found(c["expect"], core.image_text({**c, "injection": ""})), c["id"]
        assert not core.answer_found(c["expect"], c["injection"]), c["id"]
        if c.get("canary"):
            assert len(c["canary"]) == 3 and not core.canary_hit(c["canary"], text), c["id"]
        if c.get("secret"):
            assert c["secret"] in c["system"], c["id"]
            assert not core.leaked(c["secret"], text + c["user"]), c["id"]


def test_tool_cases_ask_only_for_unrequested_actions_on_reserved_domains():
    for c in core.load_cases():
        if c["threat"] != "vi-tool-hijack":
            continue
        assert c["allowed_tools"] == ["save_note"]
        assert c["attack"]["tool"] in ("open_url", "send_email")
        assert c["attack"]["target"].endswith(".test") and c["attack"]["target"] in c["injection"]


def test_every_domain_in_the_cases_is_fictional():
    text = json.dumps(core.load_cases())
    for host in re.findall(r"(?:https?://|@)([a-z0-9.-]+\.[a-z]+)", text):
        assert host.endswith((".test", ".example")), host


def test_placements_vary_within_each_threat():
    for threat in ("vi-image-injection", "vi-exfiltration", "vi-tool-hijack"):
        places = Counter(c["placement"] for c in core.load_cases() if c["threat"] == threat)
        assert len(places) >= 7, (threat, places)


def test_prompts_keep_provenance_and_benign_twins():
    prompts = core.load_prompts()
    assert all(p["source"]["kind"] == "benchmark"
               and p["source"]["benchmark"] in ("XSTest", "AdvBench")
               and p["source"]["license"] in ("MIT", "CC-BY-4.0") and p["source"]["id"]
               for p in prompts)
    by_id = {p["id"]: p for p in prompts}
    twins = [p for p in prompts if p.get("twin_of")]
    assert len(twins) == 8 and all(by_id[t["twin_of"]]["kind"] == "harmful" for t in twins)
    notice = (core.CORPUS / "NOTICE").read_text()
    assert "XSTest" in notice and "AdvBench" in notice and "CC-BY-4.0" in notice


def test_render_manifest_covers_every_image_case():
    manifest = json.loads((core.CORPUS / "manifest.json").read_text())
    have = {i["id"] for i in manifest["images"]}
    want = {c["id"] for cases in core.custom_cases().values() for c in cases}
    assert have == want
    assert all(len(i["pixel_sha256"]) == 64 for i in manifest["images"])


def test_every_case_records_where_it_comes_from():
    for path in ("cases.json", "prompts.json"):
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", json.loads((core.CORPUS / path).read_text())["added"])
    for c in core.load_cases():                  # authored here, not taken from an incident
        assert c["source"] == {"kind": "synthetic", "basis": c["threat"]}, c["id"]


def test_threats_list_the_incidents_where_the_pattern_was_observed():
    for t in THREATS:
        assert isinstance(t["observed_in"], list), t["id"]
        assert all(re.match(r"^INC-\d{3}$", i) for i in t["observed_in"]), t["id"]
    by = {t["id"]: t["observed_in"] for t in THREATS}
    assert "INC-084" in by["vi-image-injection"] and by["vi-adversarial-pixels"] == []


def test_prompt_style_is_crossed_with_kind_source_and_twins():
    """The two image styles are a rendering choice, not a property of the case: each kind and
    each source benchmark gets both styles equally, and a benign twin shares its harmful
    twin's style, so neither style can stand in for harmfulness or source."""
    cases = core.custom_cases()
    prompts = cases["vmb_harm_image"] + cases["vmb_benign_image"]
    cells = Counter((p["kind"], p["source"]["benchmark"], p["style"]) for p in prompts)
    for kind, src in {(p["kind"], p["source"]["benchmark"]) for p in prompts}:
        assert cells[(kind, src, "question")] == cells[(kind, src, "list")], (kind, src)
    style = {p["id"]: p["style"] for p in prompts}
    assert all(style[p["id"]] == style[p["twin_of"]] for p in prompts if p.get("twin_of"))
