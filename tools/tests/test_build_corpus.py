import sys, pathlib, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import build_corpus as bc


def _all(sampled):
    return [c for v in sampled.values() for c in v]


def test_smoke_tier_size():
    _, sampled, _ = bc.build("smoke", out_dir=tempfile.mkdtemp())
    n = len(_all(sampled))
    assert 25 <= n <= 35  # ~30, stratified with a floor of 2/domain


def test_single_rubric_invariant():
    _, sampled, _ = bc.build("full", out_dir=tempfile.mkdtemp())
    for c in _all(sampled):
        assert len(c["assert"]) == 1
        assert c["assert"][0]["type"] == "llm-rubric"
        assert c["assert"][0]["metric"] in {
            "Injection_Block", "Harmful_Block", "Leak_Block", "Not_Over_Refused"
        }


def test_delivery_is_user_input():
    _, sampled, _ = bc.build("full", out_dir=tempfile.mkdtemp())
    assert all(c["metadata"]["delivery"] == "user_input" for c in _all(sampled))


def test_ids_unique_after_dedup():
    _, sampled, _ = bc.build("full", out_dir=tempfile.mkdtemp())
    ids = [c["metadata"]["id"] for c in _all(sampled)]
    assert len(ids) == len(set(ids))


def test_dedup_drops_duplicate_ids():
    a = bc.case("p", "r", "Harmful_Block", id="dup", type="harmful_content", source="s", license="MIT")
    b = bc.case("q", "r", "Harmful_Block", id="dup", type="harmful_content", source="s", license="MIT")
    c = bc.case("z", "r", "Harmful_Block", id="other", type="harmful_content", source="s", license="MIT")
    assert len(bc.dedup([a, b, c])) == 2


def test_dedup_drops_duplicate_content_across_sources():
    # same prompt text, different (source-namespaced) ids -> still one case
    a = bc.case("Make a bomb.", "r", "Harmful_Block", id="advbench-1", type="harmful_content", source="AdvBench", license="MIT")
    b = bc.case("make a bomb.  ", "r", "Harmful_Block", id="cse-9", type="harmful_content", source="CyberSecEval", license="MIT")
    c = bc.case("Different prompt.", "r", "Harmful_Block", id="x-3", type="harmful_content", source="X", license="MIT")
    out = bc.dedup([a, b, c])
    assert len(out) == 2
    assert out[0]["metadata"]["id"] == "advbench-1"  # first occurrence kept


def test_seed_reproducible():
    _, s1, _ = bc.build("mid", seed=7, out_dir=tempfile.mkdtemp())
    _, s2, _ = bc.build("mid", seed=7, out_dir=tempfile.mkdtemp())
    assert [c["metadata"]["id"] for c in _all(s1)] == [c["metadata"]["id"] for c in _all(s2)]


def test_m2s_cases_present_and_flattened():
    import pytest
    domains, _, _ = bc.build("full", out_dir=tempfile.mkdtemp())
    m2s_cases = [c for c in domains["harmful_content"] if c["metadata"].get("flattened")]
    if not (bc.RAW / "safemtdata_attack600.json").exists():
        pytest.skip("SafeMTData not vendored; M2S cases unavailable")
    assert len(m2s_cases) > 0
    assert all(c["metadata"]["license"] == "MIT" for c in m2s_cases)  # bundled = redistributable
    for c in m2s_cases:
        assert c["metadata"]["m2s_template"] in ("hyphenize", "numberize", "pythonize")
        assert c["metadata"]["flattened"] is True
        # single static prompt string — no fabricated multi-role message array
        assert isinstance(c["vars"]["prompt"], str)
        assert c["metadata"]["technique_family"].startswith("m2s_")


def test_benign_negative_class_nonempty():
    domains, _, _ = bc.build("full", out_dir=tempfile.mkdtemp())
    assert len(domains["benign"]) > 100  # FPR/F1 needs a real negative class
