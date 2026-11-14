"""voice-model-benchmark: perturbations, local synthesis manifest, corpus subset selection.

Stdlib + pytest only; nothing here needs Piper, numpy or a network.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL))
sys.path.insert(0, str(SKILL / "lib"))
import audio  # noqa: E402
import cases  # noqa: E402
import import_clips  # noqa: E402
import perturb  # noqa: E402
import synth  # noqa: E402

RATE = audio.TARGET_RATE


def tone(freq: float, seconds: float = 1.0, amp: int = 8000) -> list[int]:
    step = 2 * math.pi * freq / RATE
    return [int(amp * math.sin(step * i)) for i in range(int(seconds * RATE))]


def dominant_freq(samples: list[int]) -> float:
    """Frequency of a near-sinusoid from its upward zero crossings (middle of the clip)."""
    mid = samples[len(samples) // 4: 3 * len(samples) // 4]
    ups = sum(1 for a, b in zip(mid, mid[1:]) if a < 0 <= b)
    return ups / (len(mid) / RATE)


def speechlike(seconds: float = 1.0) -> list[int]:
    """A deterministic signal with changing pitch and loudness, so WSOLA has work to do."""
    out = []
    for i in range(int(seconds * RATE)):
        t = i / RATE
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 3 * t)
        out.append(int(6000 * env * math.sin(2 * math.pi * (180 + 60 * math.sin(2 * math.pi * 2 * t)) * t)))
    return out


# --- perturbations: parameters do what they say --------------------------------------------

def test_speed_changes_duration_by_the_factor_and_keeps_pitch():
    x = tone(220)
    fast, applied = perturb.speed(x, RATE, factor=1.5)
    assert applied == {"factor": 1.5}
    assert len(fast) == round(len(x) / 1.5)
    assert dominant_freq(fast) == pytest.approx(220, rel=0.03)
    slow, _ = perturb.speed(x, RATE, factor=0.5)
    assert len(slow) == 2 * len(x)
    assert dominant_freq(slow) == pytest.approx(220, rel=0.03)


def test_speed_one_is_the_identity():
    x = speechlike()
    assert perturb.time_stretch(x, 1.0, RATE) == x


def test_pitch_shifts_frequency_and_keeps_duration():
    x = tone(220)
    up, applied = perturb.pitch(x, RATE, semitones=12)
    assert len(up) == len(x)
    assert applied["frequency_ratio"] == 2.0
    assert dominant_freq(up) == pytest.approx(440, rel=0.03)
    down, _ = perturb.pitch(x, RATE, semitones=-12)
    assert len(down) == len(x)
    assert dominant_freq(down) == pytest.approx(110, rel=0.03)


def test_volume_gain_in_db_and_saturation_is_counted_not_wrapped():
    x = tone(300, amp=4000)
    quiet, applied = perturb.volume(x, RATE, gain_db=-20)
    assert audio.rms(quiet) / audio.rms(x) == pytest.approx(0.1, rel=0.01)
    assert applied["saturated_samples"] == 0
    loud, applied = perturb.volume(x, RATE, gain_db=24)       # 4000 * 15.8 > 32767
    assert applied["saturated_samples"] > 0
    assert max(loud) == audio.INT16_MAX and min(loud) == audio.INT16_MIN


def test_noise_hits_the_requested_snr_and_is_seeded():
    x = tone(300)
    noisy, applied = perturb.noise(x, RATE, snr_db=10, seed=7)
    added = [n - s for n, s in zip(noisy, x)]
    snr = 20 * math.log10(audio.rms(x) / audio.rms(added))
    assert snr == pytest.approx(10, abs=0.3)
    assert applied["seed"] == 7 and len(noisy) == len(x)
    assert perturb.noise(x, RATE, snr_db=10, seed=7)[0] == noisy
    assert perturb.noise(x, RATE, snr_db=10, seed=8)[0] != noisy


def test_echo_places_decaying_copies_at_the_delay():
    impulse = [0] * 100 + [10000] + [0] * 100
    out, applied = perturb.echo(impulse, RATE, delay_ms=100, decay=0.5, repeats=3)
    delay = RATE // 10
    assert len(out) == len(impulse) + 3 * delay
    assert [out[100 + k * delay] for k in range(4)] == [10000, 5000, 2500, 1250]
    assert applied["applied_scale"] == 1.0
    assert sum(1 for v in out if v) == 4


def test_reverb_adds_a_decaying_tail_and_keeps_the_dry_signal():
    x = tone(300, seconds=0.2)
    out, applied = perturb.reverb(x, RATE, rt60_ms=400, wet=0.3)
    tail = out[len(x):]
    assert len(out) == len(x) + int(RATE * 0.4)
    first, last = tail[: len(tail) // 4], tail[-len(tail) // 4:]
    assert audio.rms(first) > 10 * audio.rms(last) > 0
    assert applied["rt60_ms"] == 400 and applied["wet"] == 0.3
    assert perturb.reverb(x, RATE, rt60_ms=400, wet=0.0)[0][: len(x)] == x


def test_every_default_arm_is_deterministic():
    x = speechlike(0.5)
    arms = perturb.load_arms()
    assert {"speed", "pitch", "volume", "noise", "echo", "reverb"} <= {a["kind"] for a in arms.values()}
    for name, spec in arms.items():
        first = perturb.apply(x, RATE, spec, 123, "case-a", name)
        again = perturb.apply(x, RATE, spec, 123, "case-a", name)
        assert first == again, name
        assert first[1]["kind"] == spec["kind"]
        assert all(audio.INT16_MIN <= v <= audio.INT16_MAX for v in first[0])


def test_noise_seed_depends_on_run_seed_case_and_arm_only():
    spec = {"kind": "noise", "params": {"snr_db": 10}}
    x = tone(300, seconds=0.2)
    a = perturb.apply(x, RATE, spec, 1, "case-a", "noise")
    assert perturb.apply(x, RATE, spec, 1, "case-a", "noise")[1]["seed"] == a[1]["seed"]
    assert perturb.apply(x, RATE, spec, 2, "case-a", "noise")[1]["seed"] != a[1]["seed"]
    assert perturb.apply(x, RATE, spec, 1, "case-b", "noise")[1]["seed"] != a[1]["seed"]
    assert perturb.apply(x, RATE, spec, 1, "case-a", "noise2")[1]["seed"] != a[1]["seed"]


def test_unknown_perturbation_kind_is_rejected(tmp_path):
    cfg = tmp_path / "p.json"
    cfg.write_text(json.dumps({"arms": {"x": {"kind": "telepathy", "params": {}}}}))
    with pytest.raises(ValueError, match="unknown kind"):
        perturb.load_arms(cfg)


# --- synthesis + perturbation manifests --------------------------------------------------------

PROMPTS = [{"id": "c1", "prompt": "What time is it?"}, {"id": "c2", "prompt": "Tell me a joke."}]


def test_synthesis_manifest_records_engine_text_and_pcm_hashes(tmp_path):
    manifest = synth.synthesize_all(PROMPTS, tmp_path, synth.make_engine("tone"))
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved == manifest
    assert manifest["engine"]["name"] == "tone" and manifest["engine"]["is_speech"] is False
    assert manifest["format"]["rate"] == 24000 and manifest["format"]["encoding"] == "pcm_s16le"
    for clip, prompt in zip(manifest["clips"], PROMPTS):
        samples, rate = audio.read_wav(tmp_path / clip["path"])
        assert rate == 24000 and clip["arm"] == "speech" and clip["parent"] is None
        assert clip["sha256"] == audio.sha256_pcm(samples)
        assert clip["samples"] == len(samples)
        assert clip["seconds"] == round(len(samples) / 24000, 3)
        assert clip["text_sha256"] == hashlib.sha256(prompt["prompt"].encode()).hexdigest()


def test_synthesis_is_reproducible(tmp_path):
    a = synth.synthesize_all(PROMPTS, tmp_path / "a", synth.make_engine("tone"))
    b = synth.synthesize_all(PROMPTS, tmp_path / "b", synth.make_engine("tone"))
    assert [c["sha256"] for c in a["clips"]] == [c["sha256"] for c in b["clips"]]


def test_prompt_list_formats(tmp_path):
    jsonl = tmp_path / "p.jsonl"
    jsonl.write_text("".join(json.dumps(p) + "\n" for p in PROMPTS))
    assert synth.load_prompts(jsonl) == PROMPTS
    txt = tmp_path / "p.txt"
    txt.write_text("first prompt\n\nsecond prompt\n")
    assert synth.load_prompts(txt) == [{"id": "p0001", "prompt": "first prompt"},
                                       {"id": "p0002", "prompt": "second prompt"}]
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "x"}\n')
    with pytest.raises(ValueError):
        synth.load_prompts(bad)


def test_perturbed_clips_record_parent_and_parameters(tmp_path):
    synth.synthesize_all(PROMPTS, tmp_path, synth.make_engine("tone"))
    arms = {k: v for k, v in perturb.load_arms().items() if k in ("noise", "echo")}
    rows = perturb.perturb_manifest(tmp_path / "manifest.json", arms, tmp_path, seed=5, workers=1)
    base = {c["clip_id"]: c for c in json.loads((tmp_path / "manifest.json").read_text())["clips"]}
    assert [(r["arm"], r["case_id"]) for r in rows] == [
        ("noise", "c1"), ("noise", "c2"), ("echo", "c1"), ("echo", "c2")]
    for r in rows:
        parent = base[r["parent"]]
        assert r["parent_sha256"] == parent["sha256"]
        assert r["perturbation"]["kind"] == arms[r["arm"]]["kind"]
        for key, value in arms[r["arm"]]["params"].items():
            assert r["perturbation"][key] == value
        samples, _ = audio.read_wav(tmp_path / r["path"])
        assert audio.sha256_pcm(samples) == r["sha256"] != parent["sha256"]
    # Different seed: different noise, same echo.
    other = perturb.perturb_manifest(tmp_path / "manifest.json", arms, tmp_path / "other", seed=6,
                                     workers=1)
    assert [r["sha256"] for r in other[:2]] != [r["sha256"] for r in rows[:2]]
    assert [r["sha256"] for r in other[2:]] == [r["sha256"] for r in rows[2:]]


def test_parallel_perturbation_gives_the_same_clips_in_the_same_order(tmp_path):
    prompts = [{"id": f"c{i}", "prompt": f"Prompt number {i}."} for i in range(5)]
    synth.synthesize_all(prompts, tmp_path, synth.make_engine("tone"))
    arms = {k: v for k, v in perturb.load_arms().items() if k in ("noise", "speed")}
    one = perturb.perturb_manifest(tmp_path / "manifest.json", arms, tmp_path / "one", 5, workers=1)
    many = perturb.perturb_manifest(tmp_path / "manifest.json", arms, tmp_path / "many", 5, workers=3)
    assert len(one) == 10 and many == one


def test_a_changed_parent_clip_is_refused(tmp_path):
    synth.synthesize_all(PROMPTS, tmp_path, synth.make_engine("tone"))
    audio.write_wav(tmp_path / "speech" / "c1.wav", tone(500, 0.1), RATE)
    arms = {"echo": perturb.load_arms()["echo"]}
    with pytest.raises(ValueError, match="does not match its manifest hash"):
        perturb.perturb_manifest(tmp_path / "manifest.json", arms, tmp_path, seed=5, workers=1)


def test_wav_round_trip_and_resampling(tmp_path):
    x = tone(300, 0.25)
    audio.write_wav(tmp_path / "a.wav", x, RATE)
    assert audio.read_wav(tmp_path / "a.wav") == (x, RATE)
    assert audio.from_bytes(audio.to_bytes(x)) == x
    low = tone(300, 0.25)[::3]                     # the same tone at 8 kHz
    audio.write_wav(tmp_path / "low.wav", low, 8000)
    up = audio.load_clip(tmp_path / "low.wav")
    assert len(up) == len(low) * 3
    assert dominant_freq(up) == pytest.approx(300, rel=0.03)


def test_import_clips_builds_cases_and_manifest(tmp_path):
    audio.write_wav(tmp_path / "in.wav", tone(300, 0.5)[::3], 8000)
    index = tmp_path / "rows.jsonl"
    index.write_text(json.dumps({"id": "ext-1", "type": "harmful", "prompt": "spoken words",
                                 "audio": "in.wav"}) + "\n")
    manifest = import_clips.import_clips(index, tmp_path / "out", "Some Set", "CC-BY-4.0")
    clip = manifest["clips"][0]
    assert manifest["engine"] == {"name": "imported", "is_speech": True, "source": "Some Set",
                                  "license": "CC-BY-4.0",
                                  "note": "audio supplied by the user; not synthesised by this skill"}
    assert clip["rate"] == 24000 and clip["seconds"] == 0.5 and clip["arm"] == "speech"
    loaded = cases.load_cases(tmp_path / "out" / "cases.jsonl")
    assert loaded == [{"id": "ext-1", "type": "harmful", "prompt": "spoken words",
                       "source": "Some Set", "license": "CC-BY-4.0"}]
    index.write_text(json.dumps({"id": "x", "type": "nope", "prompt": "p", "audio": "in.wav"}) + "\n")
    with pytest.raises(ValueError):
        import_clips.import_clips(index, tmp_path / "out2", "Some Set")


# --- corpus subset --------------------------------------------------------------------------------

def test_vendored_corpus_matches_its_manifest_and_is_speakable():
    text = cases.CORPUS.read_text()
    manifest = json.loads((cases.CORPUS.parent / "manifest.json").read_text())
    assert hashlib.sha256(text.encode()).hexdigest() == manifest["cases_sha256"]
    rows = cases.load_cases()
    assert len(rows) == manifest["counts"]["total"]
    by_type = {t: sum(1 for r in rows if r["type"] == t) for t in cases.TYPES}
    assert by_type == manifest["counts"]["by_type"]
    assert by_type["harmful"] > 0 and by_type["benign"] > 0
    limit = manifest["rule"]["max_chars"]
    assert all(len(r["prompt"]) <= limit and "\n" not in r["prompt"] for r in rows)
    assert {r["license"] for r in rows} <= {"MIT", "CC-BY-4.0"}
    assert all(r["source"] for r in rows)


def test_selection_is_seeded_balanced_and_nested():
    rows = cases.load_cases()
    small = cases.select(rows, 5, seed=1)
    assert [c["type"] for c in small] == ["harmful"] * 5 + ["benign"] * 5
    assert cases.select(rows, 5, seed=1) == small
    assert [c["id"] for c in cases.select(rows, 5, seed=2)] != [c["id"] for c in small]
    # Order of the corpus file does not matter, only the seed and the ids.
    assert cases.select(list(reversed(rows)), 5, seed=1) == small
    # A deeper run with the same seed contains the shallower one.
    big = {c["id"] for c in cases.select(rows, 20, seed=1)}
    assert {c["id"] for c in small} <= big and len(big) == 40
    assert len(cases.select(rows, None, seed=1)) == len(rows)


def test_selection_spans_sources_rather_than_taking_the_first_rows():
    rows = cases.load_cases()
    chosen = cases.select(rows, 100)
    assert len({c["source"] for c in chosen if c["type"] == "harmful"}) >= 2
    first_rows = [r["id"] for r in rows if r["type"] == "harmful"][:100]
    assert [c["id"] for c in chosen if c["type"] == "harmful"] != first_rows


def test_corpus_loader_rejects_bad_rows(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text('{"id": "a", "type": "harmful", "prompt": "x"}\n'
                    '{"id": "a", "type": "benign", "prompt": "y"}\n')
    with pytest.raises(ValueError, match="not unique"):
        cases.load_cases(path)
    path.write_text('{"id": "a", "type": "weird", "prompt": "x"}\n')
    with pytest.raises(ValueError, match="type must be"):
        cases.load_cases(path)
    path.write_text('{"id": "a", "type": "harmful"}\n')
    with pytest.raises(ValueError, match="missing"):
        cases.load_cases(path)
