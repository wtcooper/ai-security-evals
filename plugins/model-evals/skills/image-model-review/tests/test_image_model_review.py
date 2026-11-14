"""Unit tests for image-model-review. Stdlib + pytest; the Pillow tests skip without Pillow."""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(SKILL / "lib"))

import _evidence  # noqa: E402
import make_fixtures as fx  # noqa: E402
import provenance_check as pc  # noqa: E402
import record_probes as rp  # noqa: E402
import record_review as rr  # noqa: E402

TEMPLATE = json.loads((SKILL / "templates" / "threats.json").read_text())


# ------------------------------------------------------------ marker detection

def test_jpeg_single_segment_manifest_is_found():
    r = pc.inspect_bytes(fx.embed_jpeg(fx.TINY_JPEG, fx.fixture_store()))
    assert (r["format"], r["c2pa"]) == ("jpeg", "present")
    assert r["c2pa_detail"]["label"] == "c2pa" and r["c2pa_detail"]["segments"] == 1
    assert r["manifest_digital_source_types"] == ["trainedAlgorithmicMedia"]


def test_jpeg_manifest_split_over_segments_is_reassembled_to_its_declared_length():
    store = fx.fixture_store(padding=5000)
    r = pc.inspect_bytes(fx.embed_jpeg(fx.TINY_JPEG, store, chunk=700))
    assert r["c2pa"] == "present"
    assert r["c2pa_detail"]["segments"] > 5
    assert r["c2pa_detail"]["present_bytes"] == r["c2pa_detail"]["declared_bytes"] == len(store)


def test_jpeg_segments_out_of_order_are_sorted_by_sequence_number():
    marked = fx.embed_jpeg(fx.TINY_JPEG, fx.fixture_store(padding=900), chunk=400)
    segs = [(m, s, e) for m, _, s, e in pc.jpeg_segments(marked) if m == 0xEB]
    assert len(segs) >= 3
    (_, s0, e0), (_, s1, e1) = segs[0], segs[1]
    swapped = marked[:s0] + marked[s1:e1] + marked[s0:e0] + marked[e1:]
    assert pc.inspect_bytes(swapped)["c2pa"] == "present"


def test_jpeg_with_a_missing_segment_is_truncated_not_present():
    marked = fx.embed_jpeg(fx.TINY_JPEG, fx.fixture_store(padding=3000), chunk=1000)
    last = [(s, e) for m, _, s, e in pc.jpeg_segments(marked) if m == 0xEB][-1]
    r = pc.inspect_bytes(marked[:last[0]] + marked[last[1]:])
    assert r["c2pa"] == "truncated"
    assert r["c2pa_detail"]["present_bytes"] < r["c2pa_detail"]["declared_bytes"]


def test_unmarked_files_are_absent():
    assert pc.inspect_bytes(fx.TINY_JPEG)["c2pa"] == "absent"
    assert pc.inspect_bytes(fx.make_png())["c2pa"] == "absent"


def test_other_jumbf_box_is_not_mistaken_for_a_manifest_store():
    other = fx._box(b"jumb", fx._description(bytes(range(16)), "something-else")
                    + fx._box(b"json", b"{}"))
    r = pc.inspect_bytes(fx.embed_jpeg(fx.TINY_JPEG, other))
    assert r["c2pa"] == "absent" and r["other_jumbf_boxes"] == 1


def test_app11_that_is_not_jumbf_is_ignored():
    body = b"XX" + b"\x00" * 30
    jpeg = fx.TINY_JPEG[:2] + b"\xff\xeb" + struct.pack(">H", len(body) + 2) + body + fx.TINY_JPEG[2:]
    assert pc.inspect_bytes(jpeg)["c2pa"] == "absent"


def test_png_cabx_manifest_is_found_and_bad_crc_is_noted():
    marked = fx.embed_png(fx.make_png(), fx.fixture_store())
    r = pc.inspect_bytes(marked)
    assert (r["format"], r["c2pa"], r["c2pa_detail"]["container"]) == ("png", "present", "png caBX")
    at = marked.index(b"caBX")
    length = struct.unpack(">I", marked[at - 4:at])[0]
    broken = bytearray(marked)
    broken[at + 4 + length] ^= 0xFF                          # first CRC byte
    assert any("CRC" in n for n in pc.inspect_bytes(bytes(broken))["notes"])


def test_webp_c2pa_chunk_is_found():
    def chunk(fourcc, body):
        return fourcc + struct.pack("<I", len(body)) + body + (b"\x00" if len(body) % 2 else b"")
    payload = b"WEBP" + chunk(b"VP8 ", b"\x00" * 11) + chunk(b"C2PA", fx.fixture_store())
    webp = b"RIFF" + struct.pack("<I", len(payload)) + payload
    r = pc.inspect_bytes(webp)
    assert (r["format"], r["c2pa"], r["c2pa_detail"]["container"]) == ("webp", "present", "webp C2PA")
    plain = b"WEBP" + chunk(b"VP8 ", b"\x00" * 11)
    assert pc.inspect_bytes(b"RIFF" + struct.pack("<I", len(plain)) + plain)["c2pa"] == "absent"


def test_unknown_format_is_reported_not_guessed():
    r = pc.inspect_bytes(b"GIF89a" + b"\x00" * 40)
    assert r["c2pa"] == "unsupported_format"


def test_xmp_source_type_is_reported_but_is_not_a_manifest():
    for data in (fx.jpeg_xmp(fx.TINY_JPEG, fx.XMP_AI), fx.png_xmp(fx.make_png(), fx.XMP_AI)):
        r = pc.inspect_bytes(data)
        assert r["c2pa"] == "absent"
        assert r["xmp_digital_source_types"] == ["trainedAlgorithmicMedia"]
    ref = fx.jpeg_xmp(fx.TINY_JPEG, '<rdf:Description dcterms:provenance="https://m.example/a.c2pa"/>')
    assert pc.inspect_bytes(ref)["xmp_external_manifest"] == "https://m.example/a.c2pa"


# ------------------------------------------------------------ transformations

def test_strip_metadata_removes_the_manifest_and_leaves_the_image_bytes_alone():
    png = fx.make_png()
    assert pc.strip_metadata(fx.embed_jpeg(fx.TINY_JPEG, fx.fixture_store(2000), chunk=500)) \
        == fx.TINY_JPEG
    assert pc.strip_metadata(fx.embed_png(png, fx.fixture_store())) == png
    assert pc.strip_metadata(fx.jpeg_xmp(fx.TINY_JPEG, fx.XMP_AI)) == fx.TINY_JPEG
    assert pc.strip_metadata(b"RIFF\x04\x00\x00\x00WEBP") is None


def _fixture_files(tmp_path):
    return sorted(fx.build(tmp_path / "images"))


def test_survival_is_counted_only_over_files_that_had_a_manifest(tmp_path):
    result = pc.check(_fixture_files(tmp_path), ["strip_metadata"], {})
    s = result["summary"]
    assert s["files"] == 6 and s["original"]["present"] == 3 and s["original"]["n"] == 6
    after = s["after_transform"]["strip_metadata"]
    assert (after["present"], after["n"], after["skipped"]) == (0, 3, 0)
    assert s["xmp_digital_source_type"] == 1
    lo, hi = s["original"]["ci95"]
    assert lo < 0.5 < hi and (lo, hi) == pytest.approx((0.188, 0.812), abs=0.002)


def test_without_pillow_transformations_are_skipped_with_a_reason_and_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "pillow_version", lambda: None)
    result = pc.check(_fixture_files(tmp_path), ["strip_metadata", "resize"], {})
    resize = result["summary"]["after_transform"]["resize"]
    assert (resize["n"], resize["skipped"]) == (0, 3)
    assert resize["skipped_because"] == ["Pillow is not installed"]
    rows = pc.evidence_rows(result, "2026-11-14", "m", "p.json")
    claims = [r["claim"] for r in rows]
    assert any(c.startswith("Not assessed: survival") and "resize" in c for c in claims)
    assert any("invisible watermark" in c and c.startswith("Not assessed") for c in claims)
    assert all(_evidence.check(r) == [] and r["pointer"] == "p.json" for r in rows)
    assert all(r["absent"] for r in rows if r["claim"].startswith("Not assessed"))
    assert not any(r["absent"] for r in rows if not r["claim"].startswith("Not assessed"))
    assert {t for r in rows for t in r["threats"]} == {"img-07", "img-08"}


def test_reviewer_pipeline_folder_is_matched_by_stem_and_missing_files_are_counted(tmp_path):
    files = _fixture_files(tmp_path)
    after = tmp_path / "after_cms"
    after.mkdir()
    (after / "marked_01.jpg").write_bytes((tmp_path / "images" / "marked_01.jpg").read_bytes())
    (after / "marked_03.png").write_bytes(fx.make_png())            # the path dropped it
    result = pc.check(files, [], {"cms": after})
    cms = result["summary"]["after_pipeline"]["cms"]
    assert (cms["present"], cms["n"], cms["missing_files"]) == (1, 2, 1)


def test_pillow_transformations_drop_the_embedded_manifest_and_keep_a_readable_image():
    pytest.importorskip("PIL")
    from PIL import Image
    import io
    for original in (fx.embed_jpeg(fx.TINY_JPEG, fx.fixture_store()),
                     fx.embed_png(fx.make_png(), fx.fixture_store())):
        for name in pc.PILLOW_TRANSFORMS:
            out, skipped = pc.apply_transform(name, original)
            assert skipped is None
            im = Image.open(io.BytesIO(out))
            im.load()
            assert im.size == {"resize": (16, 16), "crop": (26, 26)}.get(name, (32, 32))
            assert pc.inspect_bytes(out)["c2pa"] == "absent"
            if name == "screenshot":
                assert pc.sniff(out) == "png"


def test_provenance_main_writes_report_and_does_not_duplicate_evidence(tmp_path, capsys):
    images = tmp_path / "images"
    fx.build(images)
    out = tmp_path / "review"
    for _ in range(2):
        assert pc.main([str(images), "--out", str(out), "--transforms", "strip_metadata",
                        "--date", "2026-11-14", "--subject", "fixture"]) == 0
    result = json.loads((out / "provenance.json").read_text())
    assert result["schema"] == pc.SCHEMA and len(result["cannot_detect"]) == 4
    assert "invisible watermarks" in capsys.readouterr().out
    rows = _evidence.read(out / "evidence.jsonl")
    assert [r["id"] for r in rows] == ["E001", "E002", "E003"]


# ------------------------------------------------------------ probe recording

def _rows(spec):
    return [rp.normalise({"probe_id": f"p{i}", "category": c, "kind": k, "outcome": o}, i)
            for i, (c, k, o) in enumerate(spec, 1)]


def test_counts_intervals_and_errors_left_out_of_the_denominator():
    rows = _rows([("identity_document", "abuse", "produced")] * 3
                 + [("identity_document", "abuse", "blocked")] * 8
                 + [("identity_document", "abuse", "partial")]
                 + [("identity_document", "abuse", "error")] * 2)
    g = rp.summarise(rows, TEMPLATE)["groups"][0]
    assert (g["n"], g["errors"]) == (12, 2)
    assert g["produced"]["count"] == 3 and g["produced"]["rate"] == 0.25
    assert g["produced"]["ci95"] == pytest.approx([0.089, 0.532], abs=0.002)
    assert g["blocked"]["count"] == 8 and g["partial"]["count"] == 1
    assert g["threat_ids"] == ["img-02"] and g["validity_flags"] == []


def test_small_n_is_a_configurable_validity_flag_that_keeps_the_number():
    rows = _rows([("qr_payload", "abuse", "produced")] * 2 + [("qr_payload", "abuse", "blocked")] * 2)
    g = rp.summarise(rows, TEMPLATE, min_n=10)["groups"][0]
    assert [f["flag"] for f in g["validity_flags"]] == ["small_n"]
    assert g["produced"]["rate"] == 0.5 and g["produced"]["ci95"] is not None
    assert rp.summarise(rows, TEMPLATE, min_n=3)["groups"][0]["validity_flags"] == []


def test_benign_probes_report_blocked_and_are_kept_apart_from_abuse_probes():
    rows = _rows([("benign_control", "", "blocked")] * 2 + [("benign_control", "", "produced")] * 10
                 + [("brand_impersonation", "benign", "produced")]
                 + [("brand_impersonation", "abuse", "blocked")])
    s = rp.summarise(rows, TEMPLATE)
    kinds = {(g["category"], g["kind"]): g for g in s["groups"]}
    assert set(kinds) == {("benign_control", "benign"), ("brand_impersonation", "benign"),
                          ("brand_impersonation", "abuse")}
    ev = rp.evidence_rows(s, "2026-11-14", "model", "x.json")
    benign = next(r for r in ev if "category benign_control" in r["claim"])
    assert "2 of 12 (17%" in benign["claim"] and "were blocked" in benign["claim"]
    assert benign["threats"] == [] and benign["pointer"] == "x.json"


def test_unprobed_template_categories_and_unmapped_reviewer_categories_are_listed():
    rows = _rows([("brand_impersonation", "abuse", "blocked")])
    rows.append(rp.normalise({"probe_id": "x", "category": "invoice_fraud", "outcome": "produced",
                              "threat_ids": "IMG-02; img-06"}, 9))
    rows.append(rp.normalise({"probe_id": "y", "category": "my_own", "outcome": "produced"}, 10))
    s = rp.summarise(rows, TEMPLATE)
    assert "identity_document" in s["categories_without_probes"]
    assert "brand_impersonation" not in s["categories_without_probes"]
    assert s["unmapped_categories"] == ["my_own"]
    custom = next(g for g in s["groups"] if g["category"] == "invoice_fraud")
    assert custom["threat_ids"] == ["img-02", "img-06"] and custom["in_template"] is False


@pytest.mark.parametrize("bad", [{"category": "qr_payload", "outcome": "allowed"},
                                 {"category": "", "outcome": "blocked"},
                                 {"category": "qr_payload", "outcome": "blocked", "kind": "x"}])
def test_bad_rows_are_rejected_with_the_row_named(bad):
    with pytest.raises(ValueError, match="row 4"):
        rp.normalise(bad, 4)


def test_probe_main_reads_csv_and_json_alike(tmp_path):
    example = SKILL / "examples" / "probe_outcomes.example.csv"
    out_csv, out_json = tmp_path / "a", tmp_path / "b"
    assert rp.main([str(example), "--out", str(out_csv), "--date", "2026-11-14", "--by", "variant"]) == 0
    as_json = tmp_path / "probes.json"
    as_json.write_text(json.dumps({"probes": [vars_ for vars_ in rp.load_rows(example)]}))
    assert rp.main([str(as_json), "--out", str(out_json), "--date", "2026-11-14"]) == 0
    a = json.loads((out_csv / "probe_summary.json").read_text())
    b = json.loads((out_json / "probe_summary.json").read_text())
    assert a["probes"] == b["probes"] == 42
    assert [(g["category"], g["n"], g["produced"]) for g in a["groups"]] \
        == [(g["category"], g["n"], g["produced"]) for g in b["groups"]]
    brand = next(g for g in a["groups"] if g["category"] == "brand_impersonation")
    assert set(brand["by_variant"]) == {"plain", "reworded", "other_language"}
    for row in _evidence.read(out_csv / "evidence.jsonl"):
        assert _evidence.check(row) == [] and row["provenance"] == "self_run"
        assert row["pointer"].endswith("probe_summary.json") and row["kind"] == "result"


# ------------------------------------------------------------ the review record

def _answers(**over):
    base = {"subject": {"vendor": "V", "model": "m"}, "harvest": [], "reviewed": [],
            "not_applicable": {}}
    base.update(over)
    return base


def test_every_threat_with_nothing_recorded_is_listed_and_gets_an_evidence_row():
    record, rows = rr.build(_answers(), TEMPLATE, None, None, "2026-11-14")
    assert record["not_assessed"] == [t["id"] for t in TEMPLATE["threats"]]
    not_assessed = [r for r in rows if r["claim"].startswith("Not assessed:")]
    assert len(not_assessed) == len(TEMPLATE["threats"])
    assert all(r["provenance"] == "reviewed" and r["absent"] for r in not_assessed)
    assert [r["threats"] for r in not_assessed] == [[t["id"]] for t in TEMPLATE["threats"]]
    assert record["harvest_not_checked"] == [h["id"] for h in TEMPLATE["harvest_items"]]


def test_absent_vendor_material_is_a_finding_and_does_not_count_as_assessment():
    answers = _answers(harvest=[{"item": "H-12", "status": "absent",
                                 "source": "https://v.example/docs", "note": "no quota page"}])
    record, rows = rr.build(answers, TEMPLATE, None, None, "2026-11-14")
    cost = next(t for t in record["threats"] if t["id"] == "img-12")
    assert cost["status"] == "not_assessed" and "H-12 looked for and absent" in cost["reason"]
    assert record["vendor_evidence_absent"] == ["H-12"]
    absent = next(r for r in rows if r["claim"].startswith("Not found"))
    assert absent["source"] == "https://v.example/docs" and absent["threats"] == ["img-12"]
    assert absent["absent"] is True and "no quota page" in absent["note"]


def test_found_evidence_probes_and_provenance_each_mark_a_threat_as_recorded(tmp_path):
    files = sorted(fx.build(tmp_path / "images"))
    provenance = pc.check(files, ["strip_metadata"], {})
    probes = rp.summarise(_rows([("qr_payload", "abuse", "produced")]), TEMPLATE)
    answers = _answers(
        harvest=[{"item": "H-10", "status": "found", "claim": "Retention is 30 days.",
                  "source": "https://v.example/data"}],
        reviewed=[{"threat_ids": ["img-11"], "claim": "Our tool logs each generation."}],
        not_applicable={"img-13": "no video"})
    record, rows = rr.build(answers, TEMPLATE, probes, provenance, "2026-11-14")
    by = {t["id"]: t for t in record["threats"]}
    assert by["img-10"]["assessed_by"] == ["vendor_evidence"]
    assert by["img-03"]["assessed_by"] == ["probes"]
    assert by["img-07"]["assessed_by"] == ["provenance_check"]
    assert by["img-08"]["assessed_by"] == ["provenance_check"]
    assert by["img-11"]["assessed_by"] == ["reviewer_note"]
    assert by["img-13"]["status"] == "not_applicable"
    assert "img-13" not in record["not_assessed"] and "img-01" in record["not_assessed"]
    assert {r["provenance"] for r in rows} == {"published", "reviewed"}
    found = next(r for r in rows if r["claim"] == "Retention is 30 days.")
    assert found["absent"] is False and found["threats"] == ["img-10"]


def test_the_decision_is_never_filled_even_if_the_answers_try():
    record, _ = rr.build(_answers(decision={"decision": "approve"}), TEMPLATE, None, None,
                         "2026-11-14")
    d = record["decision"]
    assert d["decision"] is None and d["decided_by"] is None and d["conditions"] is None
    md = rr.render(record, TEMPLATE)
    assert "- Decision:\n" in md and "approve" not in md.lower()


@pytest.mark.parametrize("answers, message", [
    (_answers(harvest=[{"item": "H-99", "status": "found"}]), "not in the template"),
    (_answers(harvest=[{"item": "H-05", "status": "found", "claim": "x"}]), "claim and a source"),
    (_answers(not_applicable={"img-13": " "}), "give the reason"),
    (_answers(reviewed=[{"threat_ids": ["img-77"], "claim": "x"}]), "unknown threat id"),
    (_answers(harvest=[{"item": "H-10", "status": "found", "claim": "x",
                        "source": "contract.pdf"}]), "http"),
])
def test_bad_answers_are_refused(answers, message):
    with pytest.raises(ValueError, match=message):
        rr.build(answers, TEMPLATE, None, None, "2026-11-14")


def test_review_main_on_the_bundled_example(tmp_path, capsys):
    out = tmp_path / "review"
    images = tmp_path / "images"
    fx.build(images)
    pc.main([str(images), "--out", str(out), "--transforms", "strip_metadata", "--date", "2026-11-14"])
    rp.main([str(SKILL / "examples" / "probe_outcomes.example.csv"), "--out", str(out),
             "--date", "2026-11-14"])
    capsys.readouterr()
    assert rr.main([str(SKILL / "examples" / "review_answers.example.json"), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "NOT ASSESSED img-04" in printed and "NOT ASSESSED img-12" in printed
    record = json.loads((out / "image_review.json").read_text())
    assert record["not_assessed"] == ["img-04", "img-12"]
    assert record["not_applicable"] == {"img-13": "The product under review does not generate video."}
    md = (out / "image_review.md").read_text()
    assert "## Not assessed" in md and "No standardized benchmark was found" in md
    rows = _evidence.read(out / "evidence.jsonl")
    assert [r["id"] for r in rows] == [f"E{i:03d}" for i in range(1, len(rows) + 1)]
    assert all(_evidence.check(r) == [] for r in rows)
    assert {r["provenance"] for r in rows} == {"self_run", "published", "reviewed"}


# ------------------------------------------------------------ evidence rows and docs

def test_evidence_rows_follow_the_review_evidence_format(tmp_path):
    good = _evidence.row("c", ["img-01"], "https://v.example/card", "published", "2026-11-14")
    assert set(good) == {"claim", "threats", "source", "captured", "provenance", "note", "absent"}
    for kwargs, message in [
        (dict(provenance="measured"), "provenance"),
        (dict(threats=["IMG-01"]), "lower-case"),
        (dict(source="contract.pdf"), "http"),
        (dict(captured="14/11/2026"), "YYYY-MM-DD"),
        (dict(captured="2999-01-01"), "future"),
        (dict(provenance="self_run", source="x.json"), "pointer"),
        (dict(absent=True), "where you looked"),
        (dict(kind="verdict"), "kind"),
    ]:
        args = dict(claim="c", threats=["img-01"], source="https://v.example/card",
                    provenance="published", captured="2026-11-14")
        args.update(kwargs)
        with pytest.raises(ValueError, match=message):
            _evidence.row(**args)
    assert _evidence.check({**good, "severity": "high"}) == ["unknown field 'severity'"]


def test_append_assigns_ids_continues_them_and_skips_rows_already_there(tmp_path):
    path = tmp_path / "evidence.jsonl"
    a = _evidence.row("a", ["img-01"], "https://v.example/a", "published", "2026-11-14")
    b = _evidence.row("b", ["img-02"], "notes.md", "reviewed", "2026-11-14")
    assert _evidence.append(path, [a, a]) == 1
    assert _evidence.append(path, [a, b]) == 1
    rows = _evidence.read(path)
    assert [(r["id"], r["claim"]) for r in rows] == [("E001", "a"), ("E002", "b")]


def test_threat_map_translates_ids_and_keeps_unmapped_ones(tmp_path):
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"_comment": "x", "img-05": "image-real-person-likeness",
                                   "img-07": ["image-provenance"], "img-08": ["image-provenance"]}))
    rows = [_evidence.row("c", ["img-07", "img-08", "img-01"], "p.json", "self_run", "2026-11-14",
                          pointer="p.json")]
    out = _evidence.apply_threat_map(rows, _evidence.load_threat_map(str(mapping)))
    assert out[0]["threats"] == ["image-provenance", "img-01"]
    assert _evidence.apply_threat_map(rows, None) == rows


def test_template_and_reference_documents_name_the_same_ids():
    threats_md = (SKILL / "references" / "threats.md").read_text()
    headings = re.findall(r"^## (img-\d\d) (.+)$", threats_md, re.M)
    assert headings == [(t["id"], t["title"]) for t in TEMPLATE["threats"]]
    harvest_md = (SKILL / "references" / "evidence-harvest.md").read_text()
    assert re.findall(r"^\| (H-\d\d) \|", harvest_md, re.M) == [h["id"] for h in TEMPLATE["harvest_items"]]
    probe_md = (SKILL / "references" / "probe-set-template.md").read_text()
    table = re.findall(r"^\| `([a-z_]+)` \| .* \| (?:img-\d\d|none) \|$", probe_md, re.M)
    assert table == list(TEMPLATE["probe_categories"])
    for t in TEMPLATE["threats"]:
        for a in t["atlas"]:
            assert a in threats_md, f"{a} is in the template but not explained in threats.md"
        assert set(t["probe_categories"]) <= set(TEMPLATE["probe_categories"])
        assert set(t["harvest_items"]) <= {h["id"] for h in TEMPLATE["harvest_items"]}


def test_no_prompts_are_shipped():
    """The skill ships categories and outcomes, never prompt text."""
    header = (SKILL / "examples" / "probe_outcomes.example.csv").read_text().splitlines()[0]
    assert "prompt" not in header.lower()
    assert not list(SKILL.rglob("*prompts*"))
