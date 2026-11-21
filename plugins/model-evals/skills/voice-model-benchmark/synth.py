#!/usr/bin/env python3
"""Turn a prompt list into mono PCM16 WAV clips at 24 kHz, locally, with a manifest.

    <venv>/bin/python synth.py --download-voice                 # once; needs network
    <venv>/bin/python synth.py --prompts cases.jsonl --out clips --engine piper
    python synth.py --prompts cases.jsonl --out clips --engine tone     # no dependency

Engines
  piper   Piper neural text-to-speech (PyPI `piper-tts`, GPL-3.0-or-later), run in this
          process with both of its noise scales set to 0. With its default noise scales
          the same text gives different audio on every run; at 0 the output is repeatable
          on one machine and library version. Nothing is sent to a service.
  tone    NOT speech. One short sine tone per character, for wiring tests against the
          mock server only. A real model cannot understand it, and the runner refuses to
          send it to anything but the mock.

--prompts is JSON lines with `id` and `prompt`, or a text file with one prompt per line
(ids become p0001, p0002, ...). The manifest records the engine, its version and licence,
the voice file hash, and for every clip its text hash, length and PCM hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402

DEFAULT_VOICE = "en_US-ljspeech-medium"
# The second, clearly different voice the custom lane uses for background speech (a male US
# voice; its model card gives the training data as CC0). Download it once like the default.
DEFAULT_BACKGROUND_VOICE = "en_US-joe-medium"
PIPER_LICENSE = "GPL-3.0-or-later (piper-tts); voice files have their own licence, see the voice's MODEL_CARD"
# Rough speaking rates, used only to ESTIMATE audio seconds in a cost plan before any clip
# exists. Measured on this skill's corpus with the default voice; the tone engine is exact.
CHARS_PER_SECOND = {"piper": 16.0, "tone": 1 / 0.06}


def voice_dir() -> Path:
    return Path(os.environ.get("VOICE_BENCH_VOICE_DIR")
                or Path.home() / ".cache" / "voice-model-benchmark" / "voices")


def resolve_voice(voice: str | None) -> Path:
    """A path to a Piper .onnx voice: the argument if it is a file, else a name in the voice
    directory."""
    name = voice or os.environ.get("VOICE_BENCH_VOICE") or DEFAULT_VOICE
    candidate = Path(name)
    if candidate.is_file():
        return candidate
    candidate = voice_dir() / f"{name}.onnx"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(
        f"Piper voice {name!r} not found in {voice_dir()}. Download it once with: "
        f"python synth.py --download-voice {name}")


def download_voice(name: str) -> Path:
    """Fetch a Piper voice with Piper's own downloader (Hugging Face, no account needed)."""
    voice_dir().mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "piper.download_voices", name,
                    "--download-dir", str(voice_dir())], check=True)
    return voice_dir() / f"{name}.onnx"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class ToneEngine:
    """Deterministic non-speech audio: a 60 ms tone per character. Wiring tests only.
    `base_hz` shifts every tone, so a second "voice" is distinguishable from the first."""
    name = "tone"

    def __init__(self, base_hz: float = 200.0):
        self.base_hz = base_hz

    def describe(self) -> dict:
        return {"name": "tone", "version": "1", "license": "MIT (this skill)",
                "is_speech": False, "base_hz": self.base_hz,
                "note": "not speech; mock target only"}

    def synthesize(self, text: str) -> tuple[list[int], int]:
        rate = audio.TARGET_RATE
        per_char = int(rate * 0.06)
        out = []
        for ch in text:
            freq = self.base_hz + (ord(ch) % 64) * 25.0
            step = 2 * math.pi * freq / rate
            out.extend(int(8000 * math.sin(step * i) * (1 - i / per_char))
                       for i in range(per_char))
        return out, rate


class PiperEngine:
    """Piper, loaded once and called in-process with deterministic settings."""
    name = "piper"

    def __init__(self, voice: str | None = None):
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:
            raise RuntimeError(
                "piper-tts is not installed in this Python. Install it in the skill's own "
                "environment (see SKILL.md, Preflight) or use --engine tone for wiring "
                "tests.") from exc
        self.voice_path = resolve_voice(voice)
        self._voice = PiperVoice.load(str(self.voice_path))
        self._config = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0)

    def describe(self) -> dict:
        from importlib import metadata
        return {"name": "piper", "version": metadata.version("piper-tts"),
                "license": PIPER_LICENSE, "is_speech": True,
                "voice": self.voice_path.stem, "voice_sha256": sha256_file(self.voice_path),
                "settings": {"noise_scale": 0.0, "noise_w_scale": 0.0}}

    def synthesize(self, text: str) -> tuple[list[int], int]:
        pcm, rate = b"", None
        for chunk in self._voice.synthesize(text, syn_config=self._config):
            pcm += chunk.audio_int16_bytes
            rate = chunk.sample_rate
        if rate is None:
            raise RuntimeError(f"piper produced no audio for text of {len(text)} characters")
        return audio.from_bytes(pcm), rate


def make_engine(name: str, voice: str | None = None, background: bool = False):
    """The engine for the caller's voice, or with `background` the second voice."""
    if name == "tone":
        return ToneEngine(900.0 if background else 200.0)
    if name == "piper":
        return PiperEngine(voice)
    raise ValueError(f"unknown engine {name!r}; known: piper, tone")


def estimate_seconds(text: str, engine: str) -> float:
    return len(text) / CHARS_PER_SECOND[engine]


def load_prompts(path: str | Path) -> list[dict]:
    text = Path(path).read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lstrip().startswith("{"):
        rows = [json.loads(ln) for ln in lines]
        bad = [r for r in rows if not r.get("id") or not r.get("prompt")]
        if bad:
            raise ValueError("every JSON line needs `id` and `prompt`")
        return rows
    return [{"id": f"p{n:04d}", "prompt": ln} for n, ln in enumerate(lines, 1)]


def synthesize_all(prompts: list[dict], out_dir: str | Path, engine) -> dict:
    """Write speech/<id>.wav for every prompt and return (and save) the manifest."""
    out_dir = Path(out_dir)
    clips = []
    for row in prompts:
        samples, rate = engine.synthesize(row["prompt"])
        samples = audio.resample(samples, rate, audio.TARGET_RATE)
        rel = Path("speech") / f"{row['id']}.wav"
        audio.write_wav(out_dir / rel, samples, audio.TARGET_RATE)
        clips.append({"clip_id": f"speech/{row['id']}", "case_id": row["id"], "arm": "speech",
                      "path": str(rel), "rate": audio.TARGET_RATE, "samples": len(samples),
                      "seconds": audio.seconds(samples, audio.TARGET_RATE),
                      "sha256": audio.sha256_pcm(samples),
                      "text_sha256": hashlib.sha256(row["prompt"].encode()).hexdigest(),
                      "parent": None, "perturbation": None})
    manifest = {"schema": 1, "engine": engine.describe(),
                "format": {"encoding": "pcm_s16le", "channels": 1, "rate": audio.TARGET_RATE,
                           "resampling": "linear interpolation from the engine's native rate"},
                "clips": clips}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--prompts", help="JSON lines (id, prompt) or one prompt per line")
    p.add_argument("--out", default="clips", help="output directory")
    p.add_argument("--engine", default="piper", choices=("piper", "tone"))
    p.add_argument("--voice", help=f"Piper voice name or .onnx path (default {DEFAULT_VOICE})")
    p.add_argument("--download-voice", nargs="?", const=DEFAULT_VOICE, metavar="NAME",
                   help="download a Piper voice into the voice directory and exit")
    args = p.parse_args(argv)
    if args.download_voice:
        print(download_voice(args.download_voice))
        return 0
    if not args.prompts:
        p.error("--prompts is required")
    manifest = synthesize_all(load_prompts(args.prompts), args.out,
                              make_engine(args.engine, args.voice))
    total = sum(c["seconds"] for c in manifest["clips"])
    print(f"synthesised {len(manifest['clips'])} clip(s), {total:.1f} s of audio, engine "
          f"{manifest['engine']['name']} -> {Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
