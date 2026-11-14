#!/usr/bin/env python3
"""Use recorded or published audio instead of synthesised speech.

    python import_clips.py --index rows.jsonl --out <dir> --source-name "JALMBench AHarm" \
        --source-license CC-BY-4.0

rows.jsonl has one JSON object per clip:
    id       unique case id
    type     "harmful" or "benign"
    prompt   the words spoken in the clip (sent as the text arm, and shown to the judge)
    audio    path to a 16-bit PCM WAV file (any sample rate, mono or stereo)
    source, license, category   optional, copied through

It writes <dir>/cases.jsonl and <dir>/manifest.json plus <dir>/speech/<id>.wav converted to
mono 24 kHz, in the same layout synth.py produces, so the runner can use it:

    python run_benchmark.py --corpus <dir>/cases.jsonl --clips <dir> --arms text,speech ...

Nothing here downloads a dataset; see references/public-audio-sets.md for how to sample one.
Audio that is not 16-bit PCM WAV must be converted first, for example
    ffmpeg -i in.flac -ac 1 -ar 24000 -c:a pcm_s16le out.wav
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402

REQUIRED = ("id", "type", "prompt", "audio")


def import_clips(index_path: str | Path, out_dir: str | Path, source_name: str,
                 source_license: str | None = None) -> dict:
    index_path, out_dir = Path(index_path), Path(out_dir)
    rows = [json.loads(ln) for ln in index_path.read_text().splitlines() if ln.strip()]
    cases, clips = [], []
    for n, row in enumerate(rows, 1):
        missing = [k for k in REQUIRED if not row.get(k)]
        if missing:
            raise ValueError(f"row {n} is missing {missing}")
        if row["type"] not in ("harmful", "benign"):
            raise ValueError(f"row {n}: type must be 'harmful' or 'benign'")
        src = Path(row["audio"])
        src = src if src.is_absolute() else index_path.parent / src
        samples = audio.load_clip(src, audio.TARGET_RATE)
        rel = Path("speech") / f"{row['id']}.wav"
        audio.write_wav(out_dir / rel, samples, audio.TARGET_RATE)
        case = {k: v for k, v in row.items() if k != "audio"}
        case.setdefault("source", source_name)
        if source_license:
            case.setdefault("license", source_license)
        cases.append(case)
        clips.append({"clip_id": f"speech/{row['id']}", "case_id": row["id"], "arm": "speech",
                      "path": str(rel), "rate": audio.TARGET_RATE, "samples": len(samples),
                      "seconds": audio.seconds(samples, audio.TARGET_RATE),
                      "sha256": audio.sha256_pcm(samples),
                      "text_sha256": hashlib.sha256(row["prompt"].encode()).hexdigest(),
                      "parent": None, "perturbation": None})
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("case ids are not unique")
    manifest = {"schema": 1,
                "engine": {"name": "imported", "is_speech": True, "source": source_name,
                           "license": source_license or "not stated",
                           "note": "audio supplied by the user; not synthesised by this skill"},
                "format": {"encoding": "pcm_s16le", "channels": 1, "rate": audio.TARGET_RATE,
                           "resampling": "linear interpolation from each file's own rate"},
                "clips": clips}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out_dir / "cases.jsonl").write_text(
        "".join(json.dumps(c, sort_keys=True) + "\n" for c in cases))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--index", required=True, help="JSON lines: id, type, prompt, audio")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--source-name", required=True, help="where the audio came from")
    p.add_argument("--source-license", help="its licence, recorded in the manifest")
    args = p.parse_args(argv)
    manifest = import_clips(args.index, args.out, args.source_name, args.source_license)
    total = sum(c["seconds"] for c in manifest["clips"])
    print(f"imported {len(manifest['clips'])} clip(s), {total:.1f} s of audio -> "
          f"{Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
