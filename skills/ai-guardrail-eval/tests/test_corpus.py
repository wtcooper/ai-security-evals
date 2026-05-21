"""
Schema and tier-cumulativity checks for the bundled static corpus.

Catches regressions in the corpus shape (renamed fields, missing attribution)
and ensures the tier monotonicity property (smoke ⊂ standard ⊂ comprehensive)
that the runner relies on for slicing.
"""
from __future__ import annotations

from guardrail_eval.corpus import (
    DEFAULT_CORPUS_PATH,
    TIER_SIZES,
    load_static_corpus,
    load_static_suite,
)


REQUIRED_TOP_KEYS = {"version", "cases", "is_partial"}
REQUIRED_CASE_FIELDS = {
    "id", "source", "category", "label", "prompt", "quality_tier",
}
# These are stored under metadata in the TestCase object but on the raw dict
# they live at the top level alongside the others.
REQUIRED_ATTRIBUTION_FIELDS = {"source_url", "citation", "license"}


def test_bundled_corpus_loads():
    raw = load_static_corpus()
    assert isinstance(raw, dict)
    missing = REQUIRED_TOP_KEYS - set(raw)
    assert not missing, f"corpus missing top-level keys: {missing}"
    assert raw["cases"], "corpus has no cases"


def test_every_case_has_required_fields():
    raw = load_static_corpus()
    for c in raw["cases"]:
        for f in REQUIRED_CASE_FIELDS:
            assert f in c, f"case {c.get('id')!r} missing field {f!r}"
        for f in REQUIRED_ATTRIBUTION_FIELDS:
            assert f in c, f"case {c.get('id')!r} missing attribution field {f!r}"
        # Either prompt or messages must be non-empty
        has_prompt = bool(c.get("prompt"))
        has_messages = bool(c.get("messages"))
        assert has_prompt or has_messages, (
            f"case {c.get('id')!r} has neither prompt nor messages"
        )
        # Label must be harmful or benign
        assert c["label"] in ("harmful", "benign"), (
            f"case {c.get('id')!r} has invalid label {c['label']!r}"
        )


def test_bundled_corpus_is_partial_marker():
    # The shipped corpus is intentionally partial (no gated MHJ/AgentHarm,
    # no public Crescendo without the `datasets` library). The is_partial
    # flag must be true and missing_sources must enumerate what's absent.
    raw = load_static_corpus()
    assert raw.get("is_partial") is True, (
        "shipped corpus should be is_partial=true; "
        "rebuild dropped this flag"
    )
    missing = raw.get("missing_sources") or []
    assert missing, "is_partial=true but missing_sources is empty"


def test_tier_cumulativity():
    smoke = {c.id for c in load_static_suite(tier="smoke")}
    standard = {c.id for c in load_static_suite(tier="standard")}
    comprehensive = {c.id for c in load_static_suite(tier="comprehensive")}

    assert smoke <= standard, "smoke is not a subset of standard"
    assert standard <= comprehensive, "standard is not a subset of comprehensive"
    assert len(smoke) < len(standard) < len(comprehensive), (
        f"tier sizes are not strictly increasing: "
        f"smoke={len(smoke)}, standard={len(standard)}, "
        f"comprehensive={len(comprehensive)}"
    )


def test_tier_sizes_map_to_loader():
    # TIER_SIZES is what load_static_suite reads to pick a max quality_tier.
    # Make sure the keys haven't drifted from what run_eval.py exposes.
    assert set(TIER_SIZES) == {"smoke", "standard", "comprehensive"}


def test_default_corpus_path_exists():
    assert DEFAULT_CORPUS_PATH.exists(), (
        f"bundled corpus not found at {DEFAULT_CORPUS_PATH}"
    )


def test_smoke_tier_has_both_labels():
    # F1 requires both labels; smoke tier must always include benign cases.
    cases = load_static_suite(tier="smoke")
    labels = {c.label for c in cases}
    assert labels == {"harmful", "benign"}, (
        f"smoke tier label set is {labels}; need both harmful and benign"
    )
