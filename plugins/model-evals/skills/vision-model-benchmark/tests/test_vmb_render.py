"""Rendering is deterministic and matches the checked-in manifest. Needs Pillow; skipped in an
environment without it (the main repo environment), run it with the skill's engine Python."""
import json

import pytest

pytest.importorskip("PIL")
import render  # noqa: E402
import vmb_core as core  # noqa: E402

IDS = {"inj-receipt-footer", "inj-form-rotated", "exf-screen-dialog", "tool-web-popup-url",
       "tool-calendar-watermark-email", "harm-xs-01", "benign-xs-02"}


def test_render_is_deterministic(tmp_path):
    a = render.render_all(tmp_path / "a", IDS)
    b = render.render_all(tmp_path / "b", IDS)
    assert [i["pixel_sha256"] for i in a["images"]] == [i["pixel_sha256"] for i in b["images"]]
    assert len(a["images"]) == len(IDS)


def test_render_matches_reference_manifest(tmp_path):
    ref = json.loads((core.CORPUS / "manifest.json").read_text())
    got = render.render_all(tmp_path, IDS)
    if got["environment"] != ref["environment"]:
        pytest.skip(f"different renderer {got['environment']} vs {ref['environment']}")
    assert render.compare(got, ref) == []


def test_every_placement_renders(tmp_path):
    seen = set()
    for c in core.load_cases():
        if c["placement"] not in seen:
            seen.add(c["placement"])
            img = render.render_case(c)
            assert img.width >= 560 and img.height >= 360
    assert len(seen) >= 12
