#!/usr/bin/env python3
"""Keyless mock of an OpenAI-compatible images API and of a vision judge, for the smoke test
and the unit tests. Everything it returns is decided by a hash of (model, prompt), so two runs
give the same outcomes.

  python scripts/mock_server.py [--port 8791]

  POST /v1/images/generations   models mock-strict and mock-lax
  POST /v1/chat/completions     model mock-judge

mock-strict refuses most requests that look risky (HTTP 400 content_policy_violation, or
HTTP 200 with no image), puts a placeholder URL in any QR code it draws, and signs its PNGs
with a C2PA manifest from a throwaway certificate chain made at start-up (so the reference
verifier reports `Valid`, not `Trusted`). mock-lax refuses little, encodes the URL it was
asked for, and attaches the repo's deliberately invalid C2PA marker fixture. Without
c2pa-python and cryptography, mock-strict attaches the fixture too; without zxing-cpp no
QR code is drawn. Each image carries a tEXt chunk `mock-judge` (yes / no / unclear) that the
mock judge reads back, so the judge path, including answers it cannot grade, is exercised.

This is wiring for tests. Its numbers say nothing about any real model.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import struct
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixtures as fx  # noqa: E402

PROFILES = {
    "mock-strict": {"risky": 0.85, "framed": 0.5, "plain": 0.02, "yes": 0.2, "unclear": 0.1,
                    "qr": "placeholder", "provenance": "signed"},
    "mock-lax": {"risky": 0.15, "framed": 0.05, "plain": 0.0, "yes": 0.8, "unclear": 0.1,
                 "qr": "exact", "provenance": "fixture"},
}
JUDGE_MODEL = "mock-judge"
PLACEHOLDER_URL = "https://example.com/"
RISKY = re.compile(
    r"sign-in|sign in|password|passcode|payment|account|security code|letterhead|delivery"
    r"|verified badge|prize|bank details|session|passport|licence|identity card|statement"
    r"|\bbill\b|invoice|sick note|payslip|degree|permit|QR code linking|QR code encoding"
    r"|barcode encoding|photorealistic (?:news|photo|party|video|billboard|courtroom)", re.I)
FRAMED = re.compile(r"security-awareness training|prop for a film|test data|satirical", re.I)
URL_IN_PROMPT = re.compile(r"https?://[^\s'\"]+?(?=[.,;:]?(?:\s|$))")


def _u(*parts: str) -> float:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 2 ** 32


# ------------------------------------------------------------------ images

def gray_png(pixels: bytes, width: int, height: int) -> bytes:
    raw = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    return fx.PNG_SIG + fx.png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) \
        + fx.png_chunk(b"IDAT", zlib.compress(raw)) + fx.png_chunk(b"IEND", b"")


def barcode_png(text: str, code128: bool = False) -> bytes | None:
    try:
        import zxingcpp
    except ImportError:
        return None
    fmt = zxingcpp.BarcodeFormat.Code128 if code128 else zxingcpp.BarcodeFormat.QRCode
    view = memoryview(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(text, fmt), scale=4))
    height, width = view.shape
    return gray_png(bytes(view), width, height)


def add_text(png: bytes, key: str, value: str) -> bytes:
    ihdr_end = 8 + 12 + struct.unpack(">I", png[8:12])[0]
    return png[:ihdr_end] + fx.png_chunk(b"tEXt", key.encode() + b"\x00" + value.encode()) \
        + png[ihdr_end:]


def read_text(png: bytes, key: str) -> str | None:
    i = 8
    while i + 12 <= len(png):
        length, ctype = struct.unpack(">I4s", png[i:i + 8])
        if ctype == b"tEXt":
            k, _, v = png[i + 8:i + 8 + length].partition(b"\x00")
            if k.decode("latin-1") == key:
                return v.decode("latin-1")
        i += 12 + length
    return None


_SIGNING: dict = {}
_SIGNING_LOCK = threading.Lock()


def _signing_material():
    """A throwaway CA and signer certificate, made once per process."""
    with _SIGNING_LOCK:
        if "chain" not in _SIGNING:
            import datetime as dt
            from cryptography import x509
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

            now = dt.datetime.now(dt.timezone.utc)

            def name(cn):
                return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                                  x509.NameAttribute(NameOID.ORGANIZATION_NAME, "mock")])

            def usage(**on):
                keys = ("digital_signature", "content_commitment", "key_encipherment",
                        "data_encipherment", "key_agreement", "key_cert_sign", "crl_sign",
                        "encipher_only", "decipher_only")
                return x509.KeyUsage(**{k: on.get(k, False) for k in keys})

            ca_key, key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
            base = (lambda subject, issuer, pub: x509.CertificateBuilder().subject_name(subject)
                    .issuer_name(issuer).public_key(pub).serial_number(x509.random_serial_number())
                    .not_valid_before(now - dt.timedelta(days=1))
                    .not_valid_after(now + dt.timedelta(days=7)))
            ca = (base(name("mock test ca"), name("mock test ca"), ca_key.public_key())
                  .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                  .add_extension(usage(key_cert_sign=True, crl_sign=True), True)
                  .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), False)
                  .sign(ca_key, hashes.SHA256()))
            leaf = (base(name("mock test signer"), ca.subject, key.public_key())
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
                    .add_extension(usage(digital_signature=True), True)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), False)
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
                    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
                    .sign(ca_key, hashes.SHA256()))
            pem = serialization.Encoding.PEM
            _SIGNING["chain"] = leaf.public_bytes(pem) + ca.public_bytes(pem)
            _SIGNING["ca"] = ca.public_bytes(pem).decode()
            _SIGNING["key"] = key.private_bytes(pem, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption())
        return _SIGNING


def sign_png(png: bytes) -> bytes | None:
    """A PNG carrying a C2PA manifest signed with the throwaway chain, or None without
    c2pa-python and cryptography."""
    try:
        import c2pa
        material = _signing_material()
    except ImportError:
        return None
    manifest = {"claim_generator_info": [{"name": "mock-image-server", "version": "1"}],
                "assertions": [{"label": "c2pa.actions", "data": {"actions": [{
                    "action": "c2pa.created", "digitalSourceType":
                    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"}]}}]}
    signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(b"es256", material["chain"],
                                                       material["key"], None))
    ctx = c2pa.Context(c2pa.Settings.from_dict({"builder": {"thumbnail": {"enabled": False}}}))
    out = io.BytesIO()
    c2pa.Builder(manifest, context=ctx).sign(signer, "image/png", io.BytesIO(png), out)
    return out.getvalue()


def make_image(model: str, prompt: str) -> bytes:
    p = PROFILES[model]
    urls = URL_IN_PROMPT.findall(prompt)
    png = None
    if urls and re.search(r"QR code|barcode", prompt, re.I):
        target = urls[0] if p["qr"] == "exact" else PLACEHOLDER_URL
        png = barcode_png(target, code128="Code 128" in prompt)
    if png is None:
        png = fx.make_png(48, 48)
    u = _u(model, prompt, "label")
    label = "yes" if u < p["yes"] else "unclear" if u < p["yes"] + p["unclear"] else "no"
    png = add_text(png, "mock-judge", label)
    if p["provenance"] == "signed":
        signed = sign_png(png)
        if signed is not None:
            return signed
    return fx.embed_png(png, fx.fixture_store())


def images_response(model: str, prompt: str) -> tuple[int, dict]:
    if model not in PROFILES:
        return 404, {"error": {"message": f"The model {model!r} does not exist",
                               "code": "model_not_found", "type": "invalid_request_error"}}
    p = PROFILES[model]
    risky, framed = bool(RISKY.search(prompt)), bool(FRAMED.search(prompt))
    p_refuse = p["framed"] if risky and framed else p["risky"] if risky else p["plain"]
    if _u(model, prompt, "refuse") < p_refuse:
        if _u(model, prompt, "style") < 0.25:
            return 200, {"created": int(time.time()), "data": []}
        return 400, {"error": {"code": "content_policy_violation", "type": "invalid_request_error",
                               "message": "Your request was rejected by the safety system."}}
    image = make_image(model, prompt)
    return 200, {"created": int(time.time()),
                 "data": [{"b64_json": base64.b64encode(image).decode(), "revised_prompt": prompt}]}


# ------------------------------------------------------------------ judge

def judge_response(body: dict) -> tuple[int, dict]:
    if body.get("model") != JUDGE_MODEL:
        return 404, {"error": {"message": f"The model {body.get('model')!r} does not exist",
                               "code": "model_not_found"}}
    image = None
    for msg in body.get("messages", []):
        content = msg.get("content")
        for part in content if isinstance(content, list) else []:
            url = (part.get("image_url") or {}).get("url", "") if isinstance(part, dict) else ""
            if url.startswith("data:"):
                image = base64.b64decode(url.split(",", 1)[1])
    if image is None:
        return 400, {"error": {"message": "no image in the request"}}
    label = read_text(image, "mock-judge") if image[:8] == fx.PNG_SIG else None
    answer = {"yes": "YES", "unclear": "I cannot tell from this image."}.get(label, "NO")
    return 200, {"id": "mock-judge-1", "object": "chat.completion", "model": JUDGE_MODEL,
                 "choices": [{"index": 0, "finish_reason": "stop",
                              "message": {"role": "assistant", "content": answer}}]}


# ------------------------------------------------------------------ server

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):                             # keep test output quiet
        pass

    def do_POST(self):                                        # noqa: N802
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": {"message": "body is not JSON"}})
        path = self.path.rstrip("/")
        if path.endswith("/images/generations"):
            status, payload = images_response(str(body.get("model")), str(body.get("prompt", "")))
            self.server.calls.append({"route": "images", "model": body.get("model")})
        elif path.endswith("/chat/completions"):
            status, payload = judge_response(body)
            self.server.calls.append({"route": "judge", "model": body.get("model")})
        else:
            status, payload = 404, {"error": {"message": f"no route {self.path}"}}
        self._send(status, payload)

    def _send(self, status: int, payload: dict):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(port: int = 0) -> ThreadingHTTPServer:
    """Start the mock on 127.0.0.1 in a background thread; `server.server_port` is the port."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.calls = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.calls = []
    print(f"mock images API and judge on http://127.0.0.1:{args.port}/v1 "
          f"(models {', '.join(PROFILES)}; judge {JUDGE_MODEL})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
