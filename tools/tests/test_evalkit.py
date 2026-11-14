import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import evalkit  # noqa: E402


def test_depth_names_and_numbers():
    assert evalkit.resolve_depth("smoke") == 25
    assert evalkit.resolve_depth("standard") == 100
    assert evalkit.resolve_depth("full") is None
    assert evalkit.resolve_depth("40") == 40
    for bad in ("quick", "0", "-3"):
        with pytest.raises(ValueError):
            evalkit.resolve_depth(bad)


def test_plan_totals(capsys):
    total = evalkit.print_plan([{"name": "a", "samples": 10, "calls": 30},
                                {"name": "b", "samples": 5, "calls": 5}], arms=2)
    assert total == {"samples": 15, "calls": 35}
    assert "2 arm(s)" in capsys.readouterr().err


def test_wilson_and_mcnemar_known_values():
    lo, hi = evalkit.wilson_ci(0.9, 100)
    assert lo == pytest.approx(0.8256, abs=1e-3) and hi == pytest.approx(0.9448, abs=1e-3)
    assert evalkit.mcnemar_exact(1, 6) == pytest.approx(0.125)
    assert evalkit.mcnemar_exact(0, 0) == 1.0
    assert evalkit.mcnemar_exact(5, 5) == 1.0


def test_context_is_read_from_a_review_profile(tmp_path, monkeypatch):
    profile = tmp_path / "review.json"
    profile.write_text(json.dumps({"subject": "x", "context": {
        "surface": "coding agent", "harness": "opencode", "safeguards": "on", "junk": 1,
        "tools": None}}))
    assert evalkit.load_context(str(profile)) == {
        "surface": "coding agent", "harness": "opencode", "safeguards": "on"}
    monkeypatch.chdir(tmp_path / "..")
    monkeypatch.delenv("REVIEW_FILE", raising=False)
    assert evalkit.load_context(None) == {} or isinstance(evalkit.load_context(None), dict)


def test_samples_rows_need_their_keys(tmp_path):
    out = tmp_path / "samples.jsonl"
    evalkit.append_samples(out, [{"arm": "a", "target": "t", "sample": 1, "good": True}])
    evalkit.append_samples(out, [{"arm": "b", "target": "t", "sample": 1, "good": False}])
    assert len(out.read_text().splitlines()) == 2
    with pytest.raises(ValueError):
        evalkit.append_samples(out, [{"arm": "a"}])


def test_validity_flag_never_fires_without_data_and_keeps_the_number():
    assert evalkit.validity_flag("judge", None, 0.05, "above", "m") is None
    assert evalkit.validity_flag("judge", 0.01, 0.05, "above", "m") is None
    flag = evalkit.validity_flag("judge", 0.2, 0.05, "above", "judge unusable")
    assert flag["observed"] == 0.2 and flag["limit"] == 0.05
    assert evalkit.validity_flag("utility", 0.1, 0.3, "below", "m")["flag"] == "utility"


def test_provider_credentials_are_scrubbed():
    env = {"OPENAI_API_KEY": "x", "AWS_SECRET_ACCESS_KEY": "x", "GROQ_API_KEY": "x",
           "HF_TOKEN": "h", "OPENAI_BASE_URL": "u", "PATH": "/bin"}
    assert evalkit.scrub_provider_credentials(env) == {
        "HF_TOKEN": "h", "OPENAI_BASE_URL": "u", "PATH": "/bin"}
