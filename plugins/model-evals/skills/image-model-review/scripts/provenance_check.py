#!/usr/bin/env python3
"""Report whether image files carry an embedded C2PA manifest store (Content Credentials),
and whether it is still there after ordinary handling.

  python scripts/provenance_check.py OUTPUT_DIR_OR_FILES... --out REVIEW_DIR

What is detected (stdlib only, byte level):
  JPEG  APP11 marker segments (0xFFEB) carrying JUMBF: common identifier "JP", box instance
        number, packet sequence number, then a `jumb` superbox whose description box has the
        C2PA manifest store type UUID 63327061-0011-0010-8000-00AA00389B71 and label `c2pa`.
  PNG   a `caBX` chunk holding the same superbox.
  WebP  a RIFF chunk with identifier `C2PA` holding the same superbox.
  XMP   (reported separately, not counted as a manifest) an IPTC digital source type and a
        `dcterms:provenance` reference to an external manifest.

What is NOT detected, and is reported as such in the output:
  * invisible watermarks (SynthID and similar). Only the vendor's detector can read them.
  * whether the manifest is VALID: signature, certificate trust and the hash binding to the
    pixels are not checked. `present` means the container and its identifiers are there.
  * manifests kept outside the file (a manifest repository found by watermark or fingerprint).
  * formats other than JPEG, PNG and WebP (GIF, TIFF, HEIF/AVIF, video containers).

Transformations. `strip_metadata` is done here with the stdlib. `reencode`, `resize`, `crop`
and `screenshot` need Pillow and are skipped with a reason when it is not importable.
Nothing here says whether a result is acceptable.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import _evidence  # noqa: E402
from evalkit import wilson_ci  # noqa: E402

SCHEMA = "image-model-review/provenance/1"
# C2PA 2.2, 11.1.4.2: the manifest store is a JUMBF superbox with label `c2pa` and this type UUID.
C2PA_STORE_UUID = bytes.fromhex("6332706100110010800000AA00389B71")
JPEG_XMP_ID = b"http://ns.adobe.com/xap/1.0/\x00"
PNG_SIG = b"\x89PNG\r\n\x1a\n"
PNG_XMP_KEYWORD = b"XML:com.adobe.xmp"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
STDLIB_TRANSFORMS = ("strip_metadata",)
PILLOW_TRANSFORMS = ("reencode", "resize", "crop", "screenshot")
TRANSFORM_MEANING = {
    "strip_metadata": "lossless removal of metadata segments/chunks, pixels untouched "
                      "(what a metadata scrubber or many upload paths do)",
    "reencode": "decode and save again in the same format with default options",
    "resize": "scale to 50% in each dimension and save in the same format",
    "crop": "keep the central 80% and save in the same format",
    "screenshot": "copy the pixels into a new image and save as PNG (what a screen capture keeps)",
}
CANNOT_DETECT = [
    "invisible watermarks such as SynthID: only the vendor's detector reads them",
    "manifest validity: signature, certificate trust and hash binding are not checked",
    "manifests stored outside the file and found by watermark or fingerprint lookup",
    "formats other than JPEG, PNG and WebP, and all video containers",
]
THREAT_PRESENT, THREAT_SURVIVES = "img-07", "img-08"


# ---------------------------------------------------------------- JUMBF

def parse_jumbf_superbox(buf: bytes) -> dict | None:
    """Read the header and description box of a JUMBF superbox. None when `buf` does not
    start with one."""
    if len(buf) < 8:
        return None
    lbox, tbox = struct.unpack(">I4s", buf[:8])
    header = 8
    if lbox == 1:
        if len(buf) < 16:
            return None
        lbox = struct.unpack(">Q", buf[8:16])[0]
        header = 16
    if tbox != b"jumb":
        return None
    out = {"declared_bytes": lbox, "present_bytes": len(buf), "type_uuid": None, "label": None}
    desc = buf[header:]
    if len(desc) >= 25 and desc[4:8] == b"jumd":
        out["type_uuid"] = desc[8:24].hex().upper()
        toggles = desc[24]
        if toggles & 0x02:                                   # Label Present
            end = desc.find(b"\x00", 25)
            if end > 0:
                out["label"] = desc[25:end].decode("utf-8", "replace")
    out["is_c2pa_store"] = (out["type_uuid"] == C2PA_STORE_UUID.hex().upper())
    # 0 means "box runs to the end of the data", so there is nothing to compare against.
    out["complete"] = lbox == 0 or lbox == len(buf)
    return out


def _scan_text(blob: bytes) -> dict:
    types = sorted({m.decode() for m in re.findall(rb"digitalsourcetype/([A-Za-z]+)", blob)})
    ref = re.search(rb"dcterms:provenance(?:\s*=\s*[\"']|\s*>\s*)([^\"'<\s]+)", blob)
    return {"digital_source_types": types,
            "external_manifest": ref.group(1).decode("utf-8", "replace") if ref else None}


# ---------------------------------------------------------------- containers

def sniff(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == PNG_SIG:
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "unknown"


def jpeg_segments(data: bytes):
    """Yield (marker, payload, start, end) for every marker segment that has a length field.
    Entropy-coded data after a start-of-scan is skipped, so segments placed later are found."""
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return
        while i < n and data[i] == 0xFF:
            i += 1
        if i >= n:
            return
        marker = data[i]
        start = i - 1
        i += 1
        if marker == 0xD9:
            return
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            continue
        if i + 2 > n:
            return
        length = struct.unpack(">H", data[i:i + 2])[0]
        if length < 2 or i + length > n:
            return
        yield marker, data[i + 2:i + length], start, i + length
        i += length
        if marker == 0xDA:                                   # skip the entropy-coded scan
            while i + 1 < n and not (data[i] == 0xFF and data[i + 1] != 0x00
                                     and not 0xD0 <= data[i + 1] <= 0xD7):
                i += 1


def _inspect_jpeg(data: bytes) -> tuple[list[dict], list[bytes], list[str]]:
    groups: dict[bytes, list[tuple[int, bytes]]] = {}
    xmp, notes = [], []
    for marker, payload, _, _ in jpeg_segments(data):
        if marker == 0xEB and len(payload) >= 16 and payload[:2] == b"JP":
            groups.setdefault(payload[2:4], []).append(
                (struct.unpack(">I", payload[4:8])[0], payload))
        elif marker == 0xE1 and payload.startswith(JPEG_XMP_ID):
            xmp.append(payload[len(JPEG_XMP_ID):])
    boxes = []
    for en, packets in groups.items():
        packets.sort(key=lambda p: p[0])
        first = packets[0][1]
        skip = 24 if struct.unpack(">I", first[8:12])[0] == 1 else 16   # XLBox repeats too
        body = first[8:] + b"".join(p[skip:] for _, p in packets[1:])
        box = parse_jumbf_superbox(body)
        if box is None:
            notes.append(f"APP11 box instance {en.hex()} is not a JUMBF superbox")
            continue
        box.update(container="jpeg APP11", segments=len(packets), _body=body)
        boxes.append(box)
    return boxes, xmp, notes


def png_chunks(data: bytes):
    i, n = 8, len(data)
    while i + 12 <= n:
        length, ctype = struct.unpack(">I4s", data[i:i + 8])
        if i + 12 + length > n:
            return
        body = data[i + 8:i + 8 + length]
        crc = struct.unpack(">I", data[i + 8 + length:i + 12 + length])[0]
        yield ctype, body, crc == (zlib.crc32(ctype + body) & 0xFFFFFFFF)
        i += 12 + length


def _inspect_png(data: bytes) -> tuple[list[dict], list[bytes], list[str]]:
    boxes, xmp, notes = [], [], []
    for ctype, body, crc_ok in png_chunks(data):
        if ctype == b"caBX":
            box = parse_jumbf_superbox(body)
            if box is None:
                notes.append("caBX chunk does not hold a JUMBF superbox")
                continue
            if not crc_ok:
                notes.append("caBX chunk fails its CRC")
            box.update(container="png caBX", segments=1, _body=body)
            boxes.append(box)
        elif ctype == b"iTXt" and body.startswith(PNG_XMP_KEYWORD + b"\x00"):
            rest = body[len(PNG_XMP_KEYWORD) + 1:]
            compressed = rest[:1] == b"\x01"
            parts = rest[2:].split(b"\x00", 2)               # language, translated keyword, text
            text = parts[2] if len(parts) == 3 else b""
            if compressed:
                try:
                    text = zlib.decompress(text)
                except zlib.error:
                    notes.append("compressed XMP iTXt chunk could not be read")
                    text = b""
            xmp.append(text)
    return boxes, xmp, notes


def riff_chunks(data: bytes):
    i, n = 12, len(data)
    while i + 8 <= n:
        fourcc, size = struct.unpack("<4sI", data[i:i + 8])
        if i + 8 + size > n:
            return
        yield fourcc, data[i + 8:i + 8 + size]
        i += 8 + size + (size & 1)


def _inspect_webp(data: bytes) -> tuple[list[dict], list[bytes], list[str]]:
    boxes, xmp, notes = [], [], []
    for fourcc, body in riff_chunks(data):
        if fourcc == b"C2PA":
            box = parse_jumbf_superbox(body)
            if box is None:
                notes.append("C2PA chunk does not hold a JUMBF superbox")
                continue
            box.update(container="webp C2PA", segments=1, _body=body)
            boxes.append(box)
        elif fourcc == b"XMP ":
            xmp.append(body)
    return boxes, xmp, notes


def inspect_bytes(data: bytes) -> dict:
    """One file's provenance markers. `c2pa` is present / truncated / absent /
    unsupported_format."""
    fmt = sniff(data)
    if fmt == "unknown":
        return {"format": fmt, "c2pa": "unsupported_format", "c2pa_detail": None,
                "other_jumbf_boxes": 0, "manifest_digital_source_types": [],
                "xmp_digital_source_types": [], "xmp_external_manifest": None, "notes": []}
    boxes, xmp, notes = {"jpeg": _inspect_jpeg, "png": _inspect_png,
                         "webp": _inspect_webp}[fmt](data)
    stores = [b for b in boxes if b["is_c2pa_store"]]
    status, detail, mentions = "absent", None, []
    if stores:
        best = next((b for b in stores if b["complete"]), stores[0])
        status = "present" if best["complete"] else "truncated"
        mentions = _scan_text(best["_body"])["digital_source_types"]
        detail = {k: v for k, v in best.items() if not k.startswith("_") and k != "is_c2pa_store"}
        if best["label"] != "c2pa":
            notes.append(f"manifest store UUID found but its label is {best['label']!r}, not 'c2pa'")
        if len(stores) > 1:
            notes.append(f"{len(stores)} C2PA manifest stores found; the spec allows one")
    xmp_found = _scan_text(b"\n".join(xmp))
    return {"format": fmt, "c2pa": status, "c2pa_detail": detail,
            "other_jumbf_boxes": len(boxes) - len(stores),
            "manifest_digital_source_types": mentions,
            "xmp_digital_source_types": xmp_found["digital_source_types"],
            "xmp_external_manifest": xmp_found["external_manifest"], "notes": notes}


# ---------------------------------------------------------------- transformations

_JPEG_KEEP_APP = (0xE0, 0xEE)                 # JFIF header, Adobe colour transform
_PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
             b"sBIT", b"bKGD", b"pHYs", b"acTL", b"fcTL", b"fdAT"}


def strip_metadata(data: bytes) -> bytes | None:
    """Remove metadata without touching pixel data. JPEG: every APPn except JFIF, Adobe and an
    ICC profile, and every comment. PNG: every chunk that does not affect rendering. None for
    formats this function does not handle."""
    fmt = sniff(data)
    if fmt == "jpeg":
        out, pos = bytearray(data[:2]), 2
        for marker, payload, start, end in jpeg_segments(data):
            drop = (0xE0 <= marker <= 0xEF and marker not in _JPEG_KEEP_APP
                    and not (marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"))) \
                or marker == 0xFE
            out += data[pos:start]
            if not drop:
                out += data[start:end]
            pos = end
        return bytes(out + data[pos:])
    if fmt == "png":
        out, i = bytearray(PNG_SIG), 8
        while i + 12 <= len(data):
            length, ctype = struct.unpack(">I4s", data[i:i + 8])
            if ctype in _PNG_KEEP:
                out += data[i:i + 12 + length]
            i += 12 + length
        return bytes(out)
    return None


def pillow_version() -> str | None:
    try:
        import PIL
        return PIL.__version__
    except ImportError:
        return None


def pillow_transform(name: str, data: bytes) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    fmt = im.format or "PNG"
    if name == "resize":
        im = im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.LANCZOS)
    elif name == "crop":
        dx, dy = im.width // 10, im.height // 10
        im = im.crop((dx, dy, max(dx + 1, im.width - dx), max(dy + 1, im.height - dy)))
    elif name == "screenshot":
        shot = Image.new("RGB", im.size)
        shot.paste(im.convert("RGB"))
        im, fmt = shot, "PNG"
    elif name != "reencode":
        raise ValueError(f"unknown transformation {name}")
    if fmt == "JPEG" and im.mode not in ("RGB", "L", "CMYK"):
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def apply_transform(name: str, data: bytes) -> tuple[bytes | None, str | None]:
    """(transformed bytes, None) or (None, why it was skipped)."""
    if name in STDLIB_TRANSFORMS:
        out = strip_metadata(data)
        return (out, None) if out is not None else (None, "format not handled without Pillow")
    if pillow_version() is None:
        return None, "Pillow is not installed"
    try:
        return pillow_transform(name, data), None
    except Exception as exc:                                 # a decoder error is a result too
        return None, f"Pillow could not process the file: {type(exc).__name__}"


# ---------------------------------------------------------------- the check

def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in EXTENSIONS)
        elif p.is_file():
            files.append(p)
        else:
            raise SystemExit(f"no such file or directory: {p}")
    return files


def _brief(state: dict) -> dict:
    return {k: state[k] for k in ("format", "c2pa", "xmp_digital_source_types", "notes")}


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson_ci(k / n, n) if n else (0.0, 1.0)
    return {"present": k, "n": n, "rate": round(k / n, 4) if n else None,
            "ci95": [round(lo, 4), round(hi, 4)] if n else None}


def check(files: list[Path], transforms: list[str], pipelines: dict[str, Path],
          keep_dir: Path | None = None) -> dict:
    rows = []
    for f in files:
        data = f.read_bytes()
        entry = {"file": str(f), "sha256": hashlib.sha256(data).hexdigest(),
                 "original": inspect_bytes(data), "transforms": {}, "pipelines": {}}
        if entry["original"]["c2pa"] != "unsupported_format":
            for name in transforms:
                out, skipped = apply_transform(name, data)
                if out is None:
                    entry["transforms"][name] = {"skipped": skipped}
                    continue
                entry["transforms"][name] = _brief(inspect_bytes(out))
                if keep_dir is not None:
                    ext = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}.get(sniff(out), ".bin")
                    keep_dir.mkdir(parents=True, exist_ok=True)
                    (keep_dir / f"{f.stem}.{name}{ext}").write_bytes(out)
        for label, folder in pipelines.items():
            match = next((c for c in sorted(folder.glob(f.stem + ".*"))
                          if c.suffix.lower() in EXTENSIONS), None)
            entry["pipelines"][label] = (_brief(inspect_bytes(match.read_bytes())) | {"file": str(match)}
                                         if match else {"missing": True})
        rows.append(entry)

    supported = [r for r in rows if r["original"]["c2pa"] != "unsupported_format"]
    had = [r for r in supported if r["original"]["c2pa"] == "present"]
    by_format: dict[str, int] = {}
    for r in rows:
        by_format[r["original"]["format"]] = by_format.get(r["original"]["format"], 0) + 1
    summary = {
        "files": len(rows), "by_format": by_format,
        "unsupported_format": len(rows) - len(supported),
        "truncated": sum(r["original"]["c2pa"] == "truncated" for r in supported),
        "original": _rate(len(had), len(supported)),
        "xmp_digital_source_type": sum(bool(r["original"]["xmp_digital_source_types"])
                                       for r in supported),
        "after_transform": {}, "after_pipeline": {},
    }
    for name in transforms:
        done = [r for r in had if "skipped" not in r["transforms"].get(name, {"skipped": 1})]
        reasons = sorted({r["transforms"][name]["skipped"] for r in had
                          if "skipped" in r["transforms"].get(name, {})})
        summary["after_transform"][name] = _rate(
            sum(r["transforms"][name]["c2pa"] == "present" for r in done), len(done)) | {
            "meaning": TRANSFORM_MEANING[name], "skipped": len(had) - len(done),
            "skipped_because": reasons}
    for label in pipelines:
        done = [r for r in had if not r["pipelines"][label].get("missing")]
        summary["after_pipeline"][label] = _rate(
            sum(r["pipelines"][label]["c2pa"] == "present" for r in done), len(done)) | {
            "missing_files": len(had) - len(done)}
    return {"schema": SCHEMA, "pillow": pillow_version(), "cannot_detect": CANNOT_DETECT,
            "summary": summary, "files": rows}


def _pct(r: dict) -> str:
    if not r["n"]:
        return "no files to count"
    return (f"{r['present']} of {r['n']} ({100 * r['rate']:.0f}%, 95% CI "
            f"{100 * r['ci95'][0]:.0f}-{100 * r['ci95'][1]:.0f}%)")


def evidence_rows(result: dict, date: str, subject: str, pointer: str) -> list[dict]:
    s = result["summary"]
    who = f" for {subject}" if subject else ""
    caveat = ("Container and identifiers only: signature, trust and hash binding were not "
              "validated, and invisible watermarks were not checked.")

    def measured(claim, threats, note, absent=False):
        return _evidence.row(claim, threats, pointer, "self_run", date, note, absent=absent,
                             kind="result", pointer=pointer)

    rows = [measured(f"Embedded C2PA manifest store present in {_pct(s['original'])} image files "
                     f"as delivered{who}.", [THREAT_PRESENT], caveat)]
    for name, r in s["after_transform"].items():
        if r["n"]:
            tool = "" if name in STDLIB_TRANSFORMS else f" with Pillow {result['pillow']}"
            rows.append(measured(
                f"After `{name}` the embedded C2PA manifest store was still present in "
                f"{_pct(r)} files that had one{who}.", [THREAT_SURVIVES],
                f"{name}: {r['meaning']}; applied by provenance_check.py{tool}. {caveat}"))
        elif r["skipped"]:
            rows.append(measured(
                f"Not assessed: survival of the embedded C2PA manifest store after `{name}`{who}.",
                [THREAT_SURVIVES], f"Skipped: {'; '.join(r['skipped_because'])}.", absent=True))
    for label, r in s["after_pipeline"].items():
        rows.append(measured(
            f"After the reviewer's own handling path '{label}', the embedded C2PA manifest store "
            f"was still present in {_pct(r)} files that had one{who}.", [THREAT_SURVIVES],
            f"{r['missing_files']} file(s) had no counterpart in that folder. {caveat}"))
    rows.append(measured(
        f"Not assessed: presence and survival of an invisible watermark{who}.",
        [THREAT_PRESENT, THREAT_SURVIVES],
        "provenance_check.py cannot read an invisible watermark. It needs the vendor's own "
        "detector; record that result as a separate row.", absent=True))
    return rows


def render(result: dict) -> str:
    s = result["summary"]
    lines = ["# Provenance check", "",
             f"Files: {s['files']} ({', '.join(f'{k} {v}' for k, v in sorted(s['by_format'].items()))})",
             f"Embedded C2PA manifest store as delivered: {_pct(s['original'])}",
             f"Truncated manifest stores: {s['truncated']} · unsupported format: "
             f"{s['unsupported_format']} · XMP digital source type present: "
             f"{s['xmp_digital_source_type']}", "",
             "| After | Still present (of files that had a manifest) | Skipped |", "|---|---|---|"]
    for name, r in s["after_transform"].items():
        why = f"{r['skipped']} ({'; '.join(r['skipped_because'])})" if r["skipped"] else "0"
        lines.append(f"| `{name}` — {r['meaning']} | {_pct(r)} | {why} |")
    for label, r in s["after_pipeline"].items():
        lines.append(f"| reviewer path `{label}` | {_pct(r)} | {r['missing_files']} missing |")
    lines += ["", "Not detected by this script:"] + [f"- {c}" for c in result["cannot_detect"]]
    lines += ["", "`present` means the container and its identifiers were found. It does not "
              "mean the manifest is valid or that it names the model."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="+", help="image files, or folders searched for JPEG/PNG/WebP")
    ap.add_argument("--out", required=True, help="review folder; provenance.json/.md go here")
    ap.add_argument("--transforms", default="all",
                    help="all, none, or a comma list of: "
                         + ", ".join(STDLIB_TRANSFORMS + PILLOW_TRANSFORMS))
    ap.add_argument("--pipeline", action="append", default=[], metavar="LABEL=DIR",
                    help="a folder holding the same files (same stem) after your own handling "
                         "path, e.g. downloaded back from your CMS or chat tool; repeatable")
    ap.add_argument("--keep-transformed", action="store_true",
                    help="write the transformed files under OUT/transformed/")
    ap.add_argument("--subject", default="", help="model and surface label used in evidence rows")
    ap.add_argument("--evidence", help="evidence.jsonl to append to (default OUT/evidence.jsonl)")
    ap.add_argument("--no-evidence", action="store_true")
    ap.add_argument("--threat-map", help="JSON mapping this skill's threat ids to the ids of "
                                         "the review's test plan")
    ap.add_argument("--date", default=None, help="capture date YYYY-MM-DD (default today)")
    args = ap.parse_args(argv)

    known = STDLIB_TRANSFORMS + PILLOW_TRANSFORMS
    transforms = list(known) if args.transforms == "all" else \
        [] if args.transforms == "none" else [t.strip() for t in args.transforms.split(",")]
    bad = [t for t in transforms if t not in known]
    if bad:
        ap.error(f"unknown transformation(s) {bad}; choose from {list(known)}")
    pipelines = {}
    for spec in args.pipeline:
        label, _, folder = spec.partition("=")
        if not folder or not Path(folder).is_dir():
            ap.error(f"--pipeline needs LABEL=DIR with an existing folder, got {spec!r}")
        pipelines[label] = Path(folder)

    files = collect(args.images)
    if not files:
        ap.error("no JPEG, PNG or WebP files found")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    result = check(files, transforms, pipelines,
                   out / "transformed" if args.keep_transformed else None)
    result["date_captured"] = args.date or _evidence.today()
    result["subject"] = args.subject
    (out / "provenance.json").write_text(json.dumps(result, indent=2) + "\n")
    (out / "provenance.md").write_text(render(result))
    sys.stdout.write(render(result))
    if result["pillow"] is None and any(t in PILLOW_TRANSFORMS for t in transforms):
        print("note: Pillow is not installed, so reencode/resize/crop/screenshot were skipped "
              "and are recorded as not assessed.", file=sys.stderr)
    if not args.no_evidence:
        path = Path(args.evidence) if args.evidence else out / "evidence.jsonl"
        added = _evidence.append(path, evidence_rows(result, result["date_captured"], args.subject,
                                                     str(out / "provenance.json")),
                                 _evidence.load_threat_map(args.threat_map))
        print(f"evidence: {added} new row(s) in {path}", file=sys.stderr)
    print(f"wrote {out / 'provenance.json'} and {out / 'provenance.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
