#!/usr/bin/env python3
"""Held-out malicious-pickle generator (design §6.3): embed a __reduce__ of a HARMLESS payload
(print / tempfile write / socket to localhost) into a benign object, across several carriers.
SCAN-ONLY: never unpickle these; the sandbox Dockerfile has no network.

  python3 mutate_pickle.py <out-dir> --payload print|tempfile|localsock --carrier raw|torch_zip|base64_exec|nested --seed 0
Writes out-dir/<name>.<ext> + out-dir/<name>.label.json {expected: malicious, payload, carrier}.
"""
import argparse
import base64
import io
import json
import os
import pathlib
import pickle
import sys
import zipfile


class _P:
    def __init__(self, kind, sink="127.0.0.1"):
        self.kind, self.sink = kind, sink

    def __reduce__(self):
        if self.kind == "print":
            return (print, ("PICKLE-CANARY (harmless)",))
        if self.kind == "tempfile":
            import tempfile
            return (_write_temp, ())
        if self.kind == "localsock":
            return (_touch, ())          # avoid real sockets; represent intent structurally
        return (print, ("noop",))


def _write_temp():
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "pickle_canary.txt")
    open(p, "w").write("harmless canary")
    return p


def _touch():
    return "would-connect-localhost:9 (harmless canary)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dst", type=pathlib.Path)
    ap.add_argument("--payload", choices=["print", "tempfile", "localsock"], default="print")
    ap.add_argument("--carrier", choices=["raw", "torch_zip", "base64_exec", "nested"], default="raw")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    a.dst.mkdir(parents=True, exist_ok=True)
    name = f"mal_{a.payload}_{a.carrier}_{a.seed}"
    payload = pickle.dumps({"weights": [0.0] * 8, "_": _P(a.payload)})
    if a.carrier == "raw":
        path = a.dst / f"{name}.pkl"; path.write_bytes(payload)
    elif a.carrier == "torch_zip":
        path = a.dst / f"{name}.pt"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("archive/data.pkl", payload); z.writestr("archive/version", "3")
    elif a.carrier == "base64_exec":
        path = a.dst / f"{name}.pkl"
        path.write_bytes(pickle.dumps({"loader": base64.b64encode(payload)}))   # nested opaque blob
    else:  # nested
        path = a.dst / f"{name}.pkl"; path.write_bytes(pickle.dumps({"outer": {"inner": _P(a.payload)}}))
    (a.dst / f"{name}.label.json").write_text(json.dumps({"file": path.name, "expected": "malicious",
                                                          "payload": a.payload, "carrier": a.carrier}) + "\n")
    print(f"wrote {path} (SCAN ONLY — do not pickle.load)")


if __name__ == "__main__":
    sys.exit(main())
