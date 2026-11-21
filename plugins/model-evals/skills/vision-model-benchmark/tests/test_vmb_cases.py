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
    assert all(p["source"] in ("XSTest", "AdvBench") and p["license"] in ("MIT", "CC-BY-4.0")
               and p["source_id"] for p in prompts)
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
