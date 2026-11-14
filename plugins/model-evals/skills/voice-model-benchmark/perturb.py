#!/usr/bin/env python3
"""Audio perturbations, implemented here in plain Python so a clip is reproducible from its
parent, its parameters and a seed. No numpy, no ffmpeg, no network.

    python perturb.py --clips <dir>/manifest.json --arms speed,noise --out <dir>

  speed    time-scale modification (WSOLA): faster or slower, pitch kept
  pitch    WSOLA stretch then resample: higher or lower, duration kept
  volume   gain in dB, saturating at the int16 range
  noise    additive white Gaussian noise at a target signal-to-noise ratio (seeded)
  echo     discrete delayed repeats of the signal
  reverb   Schroeder reverberator (four comb filters, two all-pass filters)

These change HOW the same words sound. They are not adversarial optimisation: they are the
kind of transformation a caller, a phone line or a room applies, which published work found
is enough to change model behaviour (see references/public-audio-sets.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from operator import mul
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402

DEFAULTS_FILE = Path(__file__).resolve().parent / "perturbations.json"


# --- helpers -----------------------------------------------------------------------------

def _finish(values: list[float]) -> tuple[list[int], int]:
    """Round to int16 and count the samples that had to be saturated."""
    clipped = 0
    out = []
    for v in values:
        if v > audio.INT16_MAX or v < audio.INT16_MIN:
            clipped += 1
        out.append(audio.clip16(v))
    return out, clipped


def derive_seed(seed: int, *parts: str) -> int:
    """A per-clip seed that does not depend on the order clips are processed in."""
    digest = hashlib.sha256(("|".join([str(seed), *parts])).encode()).hexdigest()
    return int(digest[:16], 16)


# --- time-scale modification (WSOLA) -------------------------------------------------------

def time_stretch(samples: list[int], speed: float, rate: int) -> list[int]:
    """Change duration by 1/speed without changing pitch (waveform-similarity overlap-add).

    Frames of 40 ms with 50% Hann overlap. Each frame is taken from where the speed says it
    should come from, nudged by up to 10 ms to the offset whose waveform best continues the
    previous frame, which is what avoids the phase clicks of plain overlap-add.
    """
    if speed <= 0:
        raise ValueError("speed must be positive")
    n = len(samples)
    if n == 0:
        return []
    frame = max(16, int(rate * 0.040) // 2 * 2)
    hop = frame // 2
    tol = max(4, int(rate * 0.010))
    step, dec = 4, 4                       # search every 4th offset, correlate every 4th sample
    out_len = int(round(n / speed))
    pad = frame + tol
    x = [0] * pad + list(samples) + [0] * (pad + frame + int(hop * max(speed, 1.0)) + 1)
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / frame) for i in range(frame)]
    n_frames = out_len // hop + 3
    y = [0.0] * (n_frames * hop + frame)
    max_start = len(x) - frame - tol - 1
    prev = None
    for k in range(n_frames):
        # Frame k is centred on output sample (k-1)*hop, i.e. it starts one hop early so the
        # very first samples are covered by two windows like every other sample.
        target = pad + int(round((k - 1) * hop * speed))
        if target > max_start:
            break
        if prev is None:
            start = target
        else:
            natural = prev + hop
            if natural + frame > len(x):
                start = target
            else:
                ref = x[natural:natural + frame:dec]
                best, best_score = 0, None
                for delta in range(-tol, tol + 1, step):
                    cand = target + delta
                    if cand < 0 or cand > max_start:
                        continue
                    seg = x[cand:cand + frame:dec]
                    energy = sum(map(mul, seg, seg))
                    # Normalised, so a louder neighbour cannot outscore the true continuation.
                    score = sum(map(mul, ref, seg)) / math.sqrt(energy) if energy else 0.0
                    # Ties go to the smallest shift, so silence and speed 1.0 stay in place.
                    if best_score is None or score > best_score or (
                            score == best_score and abs(delta) < abs(best)):
                        best, best_score = delta, score
                start = target + best
        base = k * hop
        seg = x[start:start + frame]
        y[base:base + frame] = [a + b * w for a, b, w in zip(y[base:base + frame], seg, window)]
        prev = start
    return [audio.clip16(v) for v in y[hop:hop + out_len]]


# --- the perturbations ---------------------------------------------------------------------
# Each returns (samples, applied) where `applied` is the parameters actually used plus any
# side effect a reader needs to interpret the clip (saturated samples, scaling).

def speed(samples: list[int], rate: int, *, factor: float) -> tuple[list[int], dict]:
    return time_stretch(samples, factor, rate), {"factor": factor}


def pitch(samples: list[int], rate: int, *, semitones: float) -> tuple[list[int], dict]:
    ratio = 2.0 ** (semitones / 12.0)
    stretched = time_stretch(samples, 1.0 / ratio, rate)       # ratio times longer
    return audio.resample_to_length(stretched, len(samples)), {
        "semitones": semitones, "frequency_ratio": round(ratio, 6)}


def volume(samples: list[int], rate: int, *, gain_db: float) -> tuple[list[int], dict]:
    gain = 10.0 ** (gain_db / 20.0)
    out, clipped = _finish([s * gain for s in samples])
    return out, {"gain_db": gain_db, "saturated_samples": clipped}


def noise(samples: list[int], rate: int, *, snr_db: float, seed: int) -> tuple[list[int], dict]:
    signal_rms = audio.rms(samples)
    sigma = signal_rms / (10.0 ** (snr_db / 20.0))
    rng = random.Random(seed)
    gauss = rng.gauss
    out, clipped = _finish([s + gauss(0.0, sigma) for s in samples])
    return out, {"snr_db": snr_db, "seed": seed, "noise_rms": round(sigma, 3),
                 "saturated_samples": clipped}


def echo(samples: list[int], rate: int, *, delay_ms: float, decay: float,
         repeats: int = 3) -> tuple[list[int], dict]:
    delay = max(1, int(round(rate * delay_ms / 1000.0)))
    out = [float(s) for s in samples] + [0.0] * (delay * repeats)
    gain = 1.0
    for r in range(1, repeats + 1):
        gain *= decay
        offset = delay * r
        seg = out[offset:offset + len(samples)]
        out[offset:offset + len(samples)] = [a + gain * s for a, s in zip(seg, samples)]
    scaled, scale = _fit(out)
    return scaled, {"delay_ms": delay_ms, "decay": decay, "repeats": repeats,
                    "applied_scale": scale}


def _comb(x: list[float], delay: int, gain: float) -> list[float]:
    """Feedback comb y[n] = x[n] + gain*y[n-delay], computed a block of `delay` at a time."""
    y = list(x)
    for start in range(delay, len(y), delay):
        prev = y[start - delay:start]
        cur = y[start:start + delay]
        y[start:start + delay] = [c + gain * p for c, p in zip(cur, prev)]
    return y


def _allpass(x: list[float], delay: int, gain: float) -> list[float]:
    """Schroeder all-pass y[n] = -gain*x[n] + x[n-delay] + gain*y[n-delay]."""
    y = [-gain * v for v in x[:delay]]
    for start in range(delay, len(x), delay):
        cur = x[start:start + delay]
        xprev = x[start - delay:start]
        yprev = y[start - delay:start]
        y.extend(-gain * c + xp + gain * yp for c, xp, yp in zip(cur, xprev, yprev))
    return y


def _fit(values: list[float]) -> tuple[list[int], float]:
    """Scale down (never up) so the peak fits int16; returns the scale that was applied."""
    peak = max((abs(v) for v in values), default=0.0)
    scale = 1.0 if peak <= audio.INT16_MAX else audio.INT16_MAX / peak
    return [audio.clip16(v * scale) for v in values], round(scale, 6)


def reverb(samples: list[int], rate: int, *, rt60_ms: float, wet: float) -> tuple[list[int], dict]:
    tail = int(rate * rt60_ms / 1000.0)
    dry = [float(s) for s in samples] + [0.0] * tail
    total = [0.0] * len(dry)
    for delay_ms in (29.7, 37.1, 41.1, 43.7):
        delay = max(1, int(rate * delay_ms / 1000.0))
        gain = 10.0 ** (-3.0 * delay_ms / rt60_ms)             # decays 60 dB in rt60_ms
        total = [t + c for t, c in zip(total, _comb(dry, delay, gain))]
    rev = [t / 4.0 for t in total]
    for delay_ms in (5.0, 1.7):
        rev = _allpass(rev, max(1, int(rate * delay_ms / 1000.0)), 0.7)
    scaled, scale = _fit([(1.0 - wet) * d + wet * r for d, r in zip(dry, rev)])
    return scaled, {"rt60_ms": rt60_ms, "wet": wet, "applied_scale": scale}


KINDS = {"speed": speed, "pitch": pitch, "volume": volume, "noise": noise, "echo": echo,
         "reverb": reverb}


def load_arms(path: str | Path | None = None) -> dict[str, dict]:
    """Perturbation arms: {arm name: {"kind": ..., "params": {...}}}."""
    arms = json.loads(Path(path or DEFAULTS_FILE).read_text())["arms"]
    for name, spec in arms.items():
        if spec.get("kind") not in KINDS:
            raise ValueError(f"arm {name!r}: unknown kind {spec.get('kind')!r}; "
                             f"known: {sorted(KINDS)}")
    return arms


def apply(samples: list[int], rate: int, spec: dict, seed: int, clip_key: str,
          arm: str) -> tuple[list[int], dict]:
    """Apply one arm's perturbation. `clip_key` (the case id) and the arm name are mixed into
    the seed, so the noise added to a clip never depends on which other clips were made."""
    params = dict(spec.get("params", {}))
    if spec["kind"] == "noise":
        params["seed"] = derive_seed(seed, arm, clip_key)
    out, applied = KINDS[spec["kind"]](samples, rate, **params)
    return out, {"kind": spec["kind"], **applied}


def _perturb_one(job: tuple) -> dict:
    """Worker: perturb one parent clip for one arm. Module-level so a process pool can run it."""
    base_dir, out_dir, parent, arm, spec, seed = job
    samples, rate = audio.read_wav(Path(base_dir) / parent["path"])
    if audio.sha256_pcm(samples) != parent["sha256"]:
        raise ValueError(f"{parent['path']}: content does not match its manifest hash")
    out, applied = apply(samples, rate, spec, seed, parent["case_id"], arm)
    rel = Path(arm) / f"{parent['case_id']}.wav"
    audio.write_wav(Path(out_dir) / rel, out, rate)
    return {"clip_id": f"{arm}/{parent['case_id']}", "case_id": parent["case_id"],
            "arm": arm, "path": str(rel), "rate": rate, "samples": len(out),
            "seconds": audio.seconds(out, rate), "sha256": audio.sha256_pcm(out),
            "parent": parent["clip_id"], "parent_sha256": parent["sha256"],
            "perturbation": applied}


def perturb_manifest(manifest_path: str | Path, arms: dict[str, dict], out_dir: str | Path,
                     seed: int, workers: int | None = None) -> list[dict]:
    """Perturb every base clip in a synthesis manifest; returns the new manifest rows, in
    arm then clip order whatever the number of worker processes."""
    manifest_path = Path(manifest_path)
    base_rows = [r for r in json.loads(manifest_path.read_text())["clips"]
                 if r["arm"] == "speech"]
    jobs = [(str(manifest_path.parent), str(out_dir), parent, arm, spec, seed)
            for arm, spec in arms.items() for parent in base_rows]
    workers = workers if workers is not None else min(8, os.cpu_count() or 1)
    if workers <= 1 or len(jobs) < 8:
        return [_perturb_one(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_perturb_one, jobs, chunksize=4))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Perturb synthesised clips; append to the manifest.")
    p.add_argument("--clips", required=True, help="manifest.json written by synth.py")
    p.add_argument("--arms", default="all", help="comma list of arm names, or 'all'")
    p.add_argument("--config", help="perturbation definitions (default: perturbations.json)")
    p.add_argument("--seed", type=int, default=20261114)
    args = p.parse_args(argv)
    arms = load_arms(args.config)
    if args.arms != "all":
        wanted = [a.strip() for a in args.arms.split(",") if a.strip()]
        unknown = [a for a in wanted if a not in arms]
        if unknown:
            p.error(f"unknown arm(s) {unknown}; defined: {sorted(arms)}")
        arms = {a: arms[a] for a in wanted}
    manifest_path = Path(args.clips)
    doc = json.loads(manifest_path.read_text())
    rows = perturb_manifest(manifest_path, arms, manifest_path.parent, args.seed)
    doc["clips"] = [r for r in doc["clips"] if r["arm"] not in arms] + rows
    doc["perturbation_seed"] = args.seed
    doc["perturbation_arms"] = {**doc.get("perturbation_arms", {}), **arms}
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"perturbed {len(rows)} clip(s) across {len(arms)} arm(s) -> {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
