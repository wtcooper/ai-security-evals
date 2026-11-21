#!/usr/bin/env python3
"""Mono 16-bit PCM helpers. Stdlib only, so clips are byte-identical on any Python.

A clip is a Python list of ints in [-32768, 32767] plus a sample rate. Everything the
benchmark sends to a realtime model is mono PCM16 at TARGET_RATE.
"""
from __future__ import annotations

import array
import hashlib
import sys
import wave
from pathlib import Path

TARGET_RATE = 24000          # the PCM rate the OpenAI Realtime API documents for audio/pcm
INT16_MIN, INT16_MAX = -32768, 32767


def clip16(value: float) -> int:
    """Round to the nearest int16, saturating instead of wrapping."""
    v = int(round(value))
    return INT16_MAX if v > INT16_MAX else INT16_MIN if v < INT16_MIN else v


def to_bytes(samples: list[int]) -> bytes:
    """Little-endian PCM16 bytes, the layout WAV files and realtime APIs use."""
    arr = array.array("h", samples)
    if sys.byteorder == "big":
        arr.byteswap()
    return arr.tobytes()


def from_bytes(data: bytes) -> list[int]:
    arr = array.array("h")
    arr.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder == "big":
        arr.byteswap()
    return arr.tolist()


def sha256_pcm(samples: list[int]) -> str:
    """Hash of the PCM payload only, so it is the same for a WAV file and the bytes on the wire."""
    return hashlib.sha256(to_bytes(samples)).hexdigest()


def seconds(samples: list[int], rate: int) -> float:
    return round(len(samples) / rate, 3)


def read_wav(path: str | Path) -> tuple[list[int], int]:
    """Read a PCM16 WAV as mono samples. Stereo is averaged; other widths are rejected."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getcomptype() != "NONE":
            raise ValueError(f"{path}: need uncompressed 16-bit PCM, got "
                             f"width={w.getsampwidth()} comp={w.getcomptype()}")
        channels, rate = w.getnchannels(), w.getframerate()
        samples = from_bytes(w.readframes(w.getnframes()))
    if channels > 1:
        samples = [clip16(sum(samples[i:i + channels]) / channels)
                   for i in range(0, len(samples) - channels + 1, channels)]
    return samples, rate


def write_wav(path: str | Path, samples: list[int], rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(to_bytes(samples))


def resample_to_length(samples: list[int], out_len: int) -> list[int]:
    """Linear interpolation onto `out_len` evenly spaced points. No anti-alias filter: for
    speech the energy above the new Nyquist limit is small, and the method is recorded."""
    n = len(samples)
    if out_len <= 0 or n == 0:
        return []
    if out_len == n:
        return list(samples)
    if n == 1:
        return [samples[0]] * out_len
    step = (n - 1) / (out_len - 1) if out_len > 1 else 0.0
    out = []
    last = n - 1
    for i in range(out_len):
        pos = i * step
        j = int(pos)
        if j >= last:
            out.append(samples[last])
        else:
            frac = pos - j
            a = samples[j]
            out.append(int(round(a + (samples[j + 1] - a) * frac)))
    return out


def resample(samples: list[int], src_rate: int, dst_rate: int = TARGET_RATE) -> list[int]:
    if src_rate == dst_rate:
        return list(samples)
    return resample_to_length(samples, int(round(len(samples) * dst_rate / src_rate)))


def load_clip(path: str | Path, rate: int = TARGET_RATE) -> list[int]:
    """A WAV file as mono PCM16 at `rate`, resampling if the file uses another rate."""
    samples, src = read_wav(path)
    return resample(samples, src, rate)


def rms(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


def mix(primary: list[int], background: list[int], rate: int, *, gain_db: float,
        offset_s: float) -> tuple[list[int], dict]:
    """Add `background` under `primary`, starting `offset_s` seconds in, scaled so its RMS is
    `gain_db` relative to the primary's RMS (negative = quieter). The result is scaled down,
    never up, if the sum would clip. Returns (samples, what was applied)."""
    offset = max(0, int(round(offset_s * rate)))
    p_rms, b_rms = rms(primary), rms(background)
    gain = (p_rms * 10.0 ** (gain_db / 20.0) / b_rms) if b_rms and p_rms else 0.0
    out = [float(s) for s in primary] + [0.0] * max(0, offset + len(background) - len(primary))
    seg = out[offset:offset + len(background)]
    out[offset:offset + len(background)] = [a + gain * b for a, b in zip(seg, background)]
    peak = max((abs(v) for v in out), default=0.0)
    scale = 1.0 if peak <= INT16_MAX else INT16_MAX / peak
    return [clip16(v * scale) for v in out], {
        "gain_db": gain_db, "offset_s": round(offset / rate, 3),
        "background_seconds": seconds(background, rate), "applied_scale": round(scale, 6)}
