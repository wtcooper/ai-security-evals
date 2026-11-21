#!/usr/bin/env python3
"""Build small test images with and without an embedded C2PA marker, stdlib only.

  python scripts/make_fixtures.py OUTDIR

Used by the smoke test and the unit tests. The "marked" files carry a FIXTURE manifest store:
a JUMBF superbox with the C2PA manifest store type UUID and the `c2pa` label, wrapped the way
the C2PA specification says a JPEG (APP11 segments) or a PNG (`caBX` chunk) carries one. It
holds no claim and no signature, so every real C2PA validator rejects it. It exists only to
prove provenance_check.py finds the container, and must never be presented as a credential.
"""
from __future__ import annotations

import base64
import struct
import sys
import zlib
from pathlib import Path

C2PA_STORE_UUID = bytes.fromhex("6332706100110010800000AA00389B71")   # c2pa, manifest store
C2PA_MANIFEST_UUID = bytes.fromhex("63326D6100110010800000AA00389B71")  # c2ma, one manifest
AI_SOURCE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
PNG_SIG = b"\x89PNG\r\n\x1a\n"

# A 32x32 baseline JPEG (a colour gradient) encoded once with Pillow, so the fixture needs no
# image library to build.
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAA0JCgsKCA0LCgsODg0PEyAVExISEyccHhcgLikxMC4pLSwzOko+MzZG"
    "NywtQFdBRkxOUlNSMj5aYVpQYEpRUk//2wBDAQ4ODhMREyYVFSZPNS01T09PT09PT09PT09PT09PT09PT09PT09P"
    "T09PT09PT09PT09PT09PT09PT09PT09PT0//wAARCAAgACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAA"
    "AAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAk"
    "M2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
    "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QA"
    "HwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdh"
    "cRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
    "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDgYrbHatGK2x2q3FbY7VPFbY7UTr+w/rYMLibjYrbHatCK2x2q"
    "5FbY7VPFbY7V7FSv7D+tj38LiblOK2x2rQitsdqtxW2O1WIrbHauOpX9h/Wx+d4XE3MqK2x2rQitsdquRW2O1TxW"
    "2O1fHTr+w/rY+rwuJuf/2Q==")


def _box(tbox: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), tbox) + payload


def _description(uuid: bytes, label: str) -> bytes:
    return _box(b"jumd", uuid + b"\x03" + label.encode() + b"\x00")   # requestable + label present


def fixture_store(padding: int = 0) -> bytes:
    """A structurally correct, deliberately invalid manifest store (see the module docstring)."""
    note = (f"FIXTURE - not a valid C2PA manifest. digitalSourceType {AI_SOURCE}").encode()
    manifest = _box(b"jumb", _description(C2PA_MANIFEST_UUID, "urn:c2pa:fixture")
                    + _box(b"json", note + b" " * padding))
    return _box(b"jumb", _description(C2PA_STORE_UUID, "c2pa") + manifest)


def make_png(width: int = 32, height: int = 32) -> bytes:
    raw = b"".join(b"\x00" + bytes((x * 255 // width, y * 255 // height, (x ^ y) * 8 % 256)[c]
                                   for x in range(width) for c in range(3))
                   for y in range(height))
    return PNG_SIG + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) \
        + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b"")


def png_chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body \
        + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def embed_png(png: bytes, store: bytes) -> bytes:
    """Insert a `caBX` chunk right after IHDR (C2PA 2.2, A.3.2: before the IDAT chunks)."""
    ihdr_end = 8 + 12 + struct.unpack(">I", png[8:12])[0]
    return png[:ihdr_end] + png_chunk(b"caBX", store) + png[ihdr_end:]


def png_xmp(png: bytes, xmp: str) -> bytes:
    ihdr_end = 8 + 12 + struct.unpack(">I", png[8:12])[0]
    body = b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + xmp.encode()
    return png[:ihdr_end] + png_chunk(b"iTXt", body) + png[ihdr_end:]


def embed_jpeg(jpeg: bytes, store: bytes, chunk: int = 60000, instance: int = 0x0211) -> bytes:
    """Insert the store as contiguous APP11 segments after the JFIF header (C2PA 2.2, A.3.1).
    Each segment is: CI "JP", box instance number, packet sequence number from 1, then the
    superbox's LBox and TBox (repeated in every segment) and a slice of its payload."""
    head, payload = store[:8], store[8:]
    pieces = [payload[i:i + chunk] for i in range(0, len(payload), chunk)] or [b""]
    segs = b""
    for z, piece in enumerate(pieces, 1):
        body = b"JP" + struct.pack(">HI", instance, z) + head + piece
        segs += b"\xff\xeb" + struct.pack(">H", len(body) + 2) + body
    at = 2
    if jpeg[2:4] == b"\xff\xe0":
        at = 4 + struct.unpack(">H", jpeg[4:6])[0]
    return jpeg[:at] + segs + jpeg[at:]


def jpeg_xmp(jpeg: bytes, xmp: str) -> bytes:
    body = b"http://ns.adobe.com/xap/1.0/\x00" + xmp.encode()
    return jpeg[:2] + b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body + jpeg[2:]


XMP_AI = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/'
          '22-rdf-syntax-ns#"><rdf:Description xmlns:Iptc4xmpExt="http://iptc.org/std/'
          f'Iptc4xmpExt/2008-02-29/" Iptc4xmpExt:DigitalSourceType="{AI_SOURCE}"/>'
          '</rdf:RDF></x:xmpmeta>')


def build(outdir: str | Path) -> list[Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    png = make_png()
    files = {
        "marked_01.jpg": embed_jpeg(TINY_JPEG, fixture_store()),
        "marked_02.jpg": embed_jpeg(TINY_JPEG, fixture_store(padding=3000), chunk=1000),
        "marked_03.png": embed_png(png, fixture_store()),
        "unmarked_01.jpg": TINY_JPEG,
        "unmarked_02.png": png,
        "xmp_only_01.jpg": jpeg_xmp(TINY_JPEG, XMP_AI),
    }
    paths = []
    for name, data in files.items():
        (out / name).write_bytes(data)
        paths.append(out / name)
    return paths


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    for p in build(sys.argv[1]):
        print(p)
