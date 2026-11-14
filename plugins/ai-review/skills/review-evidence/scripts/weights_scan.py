#!/usr/bin/env python3
"""Open-weights supply-chain check: read the scan results Hugging Face already publishes.

    python weights_scan.py <org/repo> [--revision main] [--out weights.json]

The Hub runs several scanners over every public model file and serves the verdicts
unauthenticated, so there is no reason to download tens of gigabytes to re-run them:

    GET /api/models/{repo}/tree/{rev}?expand=true&recursive=true  -> per-file securityFileStatus
    GET /api/models/{repo}/scan                                   -> {scansDone, filesWithIssues}

The one rule that matters: "not scanned" is not "safe". The verdict is `unsafe`, `clean`
or `unscanned`, and only `clean` means a scanner looked and found nothing.
Exit code: 0 clean, 1 unsafe, 2 unscanned or error. Set HF_TOKEN for gated repos.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HF_API = "https://huggingface.co/api"
SCANNERS = ("protectAiScan", "avScan", "pickleImportScan", "virusTotalScan", "jFrogScan")
WEIGHT_SUFFIXES = (".bin", ".safetensors", ".pt", ".pth", ".ckpt", ".h5", ".pb", ".onnx",
                   ".msgpack", ".gguf", ".tflite", ".pkl", ".joblib", ".npy", ".npz")
# Formats that can execute code on load. A repo that ships only these is a finding in
# itself, even when every scanner says safe.
PICKLE_SUFFIXES = (".bin", ".pt", ".pth", ".ckpt", ".pkl", ".joblib")
NOT_SCANNED = ("unscanned", "queued", "")


def parse_file(entry: dict) -> dict:
    status = entry.get("securityFileStatus") or {}
    verdicts = {k: str(status[k].get("status", "unscanned"))
                for k in SCANNERS if isinstance(status.get(k), dict)}
    return {
        "path": entry.get("path", "?"),
        "size": entry.get("size"),
        "status": str(status.get("status", "unscanned")),
        "verdicts": verdicts,
        "messages": {k: status[k].get("message") for k in verdicts if status[k].get("message")},
    }


def assess(tree: list, scan: dict) -> dict:
    files = [parse_file(e) for e in tree
             if e.get("type") == "file" and isinstance(e.get("securityFileStatus"), dict)]
    unsafe = sorted({f["path"] for f in files
                     if f["status"] == "unsafe" or "unsafe" in f["verdicts"].values()}
                    | {i.get("path", str(i)) if isinstance(i, dict) else str(i)
                       for i in (scan.get("filesWithIssues") or [])})
    weights = [f for f in files if f["path"].lower().endswith(WEIGHT_SUFFIXES)]
    coverage = {k: sum(1 for f in weights if f["verdicts"].get(k, "unscanned") not in NOT_SCANNED)
                for k in SCANNERS}
    unscanned = [f["path"] for f in weights
                 if all(v in NOT_SCANNED for v in f["verdicts"].values())]
    pickles = [f["path"] for f in weights if f["path"].lower().endswith(PICKLE_SUFFIXES)]
    safetensors = any(f["path"].lower().endswith((".safetensors", ".gguf")) for f in weights)
    scans_done = bool(scan.get("scansDone", False))
    if unsafe:
        verdict = "unsafe"
    elif not scans_done or not weights or unscanned:
        verdict = "unscanned"
    else:
        verdict = "clean"
    return {
        "verdict": verdict, "scans_done": scans_done, "unsafe_files": unsafe,
        "weight_files": len(weights), "unscanned_weight_files": unscanned,
        "scanner_coverage": coverage, "pickle_format_files": pickles,
        "pickle_only": bool(pickles) and not safetensors, "files": files,
    }


def _get(url: str, token: str | None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https host
        return json.load(resp)


def harvest(repo: str, revision: str = "main", token: str | None = None) -> dict:
    base = f"{HF_API}/models/{urllib.parse.quote(repo, safe='/')}"
    try:
        tree = _get(f"{base}/tree/{urllib.parse.quote(revision, safe='')}"
                    "?expand=true&recursive=true", token)
    except urllib.error.HTTPError as exc:
        return {"repo": repo, "revision": revision, "verdict": "error",
                "error": f"HTTP {exc.code} listing {repo} (missing, gated or private)"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"repo": repo, "revision": revision, "verdict": "error",
                "error": f"{type(exc).__name__}: {exc}"}
    try:
        scan = _get(f"{base}/scan", token)
    except (urllib.error.URLError, TimeoutError, ValueError):
        scan = {}   # no summary is not a positive signal: scans_done stays False
    return {"repo": repo, "revision": revision, **assess(tree, scan)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("repo")
    p.add_argument("--revision", default="main")
    p.add_argument("--out")
    args = p.parse_args(argv)
    result = harvest(args.repo, args.revision, os.environ.get("HF_TOKEN"))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2)
    brief = {k: v for k, v in result.items() if k != "files"}
    print(json.dumps(brief, indent=2))
    return {"clean": 0, "unsafe": 1}.get(result["verdict"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
