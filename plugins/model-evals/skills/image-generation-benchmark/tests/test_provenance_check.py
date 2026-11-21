"""The marker check (scripts/provenance_check.py): detection, transformations, evidence rows.
Stdlib + pytest; the Pillow tests skip without Pillow."""
from __future__ import annotations

import json
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
    assert {t for r in rows for t in r["threats"]} == {"ig-provenance"}


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
