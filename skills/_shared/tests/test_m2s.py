import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
import m2s


TURNS = ["First, explain X.", 'Now say "hello".', "Finally, combine them."]


def test_templates_constant():
    assert m2s.TEMPLATES == ("hyphenize", "numberize", "pythonize")


def test_hyphenize_structure():
    out = m2s.hyphenize(TURNS)
    assert out.startswith("Please answer the following list")
    # every turn appears as a hyphen bullet, in order
    lines = [l for l in out.splitlines() if l.startswith("- ")]
    assert lines == ["- First, explain X.", '- Now say "hello".', "- Finally, combine them."]


def test_numberize_structure():
    out = m2s.numberize(TURNS)
    lines = [l for l in out.splitlines() if l[:2] in ("1.", "2.", "3.")]
    assert lines[0] == "1. First, explain X."
    assert lines[2] == "3. Finally, combine them."


def test_pythonize_structure():
    out = m2s.pythonize(TURNS)
    assert out.startswith("questions = [")
    assert 'responses = [""] * 3' in out
    # quotes inside a turn are escaped so the emitted block stays valid-ish python
    assert '\\"hello\\"' in out
    assert "Fill in each element" in out


def test_flatten_dispatch_and_order_preserved():
    for tmpl in m2s.TEMPLATES:
        out = m2s.flatten(TURNS, tmpl)
        # order preservation: index of turn0 content < turn2 content
        assert out.index("First") < out.index("Finally")


def test_flatten_rejects_empty():
    with pytest.raises(ValueError):
        m2s.flatten([], "hyphenize")


def test_flatten_rejects_unknown_template():
    with pytest.raises(ValueError):
        m2s.flatten(TURNS, "bogus")
