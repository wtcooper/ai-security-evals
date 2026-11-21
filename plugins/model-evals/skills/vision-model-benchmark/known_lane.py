"""Fetch the known-lane benchmarks at pinned revisions, one file at a time. Standard library.

  * CyberSecEval 3 visual prompt injection: test_cases.json (588 KB) from Hugging Face, then
    only the images of the selected cases (about 1.3 MB each; all 1000 are about 1.2 GB).
  * FigStep SafeBench: safebench.csv (79 KB) from GitHub, then only the selected typographic
    images (30-50 KB each).

Both index files are checked against a recorded sha256, so a moved revision fails loudly.
`source="fixture"` reads the tiny fixtures in tests/fixtures instead, in the same upstream
layout, for the keyless smoke test. Set HF_TOKEN for higher Hugging Face rate limits.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from pathlib import Path

import vmb_core as core

HF_URL = "https://huggingface.co/datasets/{repo}/resolve/{rev}/{path}"
GH_URL = "https://raw.githubusercontent.com/{repo}/{rev}/{path}"


def default_cache() -> Path:
    return Path(os.environ.get("VMB_CACHE_DIR") or Path.home() / ".cache" /
                "vision-model-benchmark")


def _download(url: str, dest: Path, sha256: str | None = None) -> Path:
    if dest.is_file() and (sha256 is None or _sha(dest) == sha256):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "vision-model-benchmark"})
    if "huggingface.co" in url and os.environ.get("HF_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['HF_TOKEN']}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=120) as resp:
        tmp.write_bytes(resp.read())
    if sha256 is not None and _sha(tmp) != sha256:
        tmp.unlink()
        raise ValueError(f"{url}: sha256 differs from the pinned value; the upstream file "
                         "changed at this revision or the download was altered")
    tmp.replace(dest)
    return dest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- CyberSecEval 3 ----------------------------------------------------------------------
def cyse3_dir(source: str, cache: Path | None, override: Path | None = None) -> Path:
    if source == "fixture":
        return core.FIXTURES / "cyse3"
    if override:
        return override
    return (cache or default_cache()) / f"cyse3-{core.CYSE3['revision'][:12]}"


def cyse3_records(source: str, data_dir: Path) -> list[dict]:
    path = data_dir / "test_cases.json"
    if source != "fixture":
        _download(HF_URL.format(repo=core.CYSE3["repo"], rev=core.CYSE3["revision"],
                                path="test_cases.json"), path, core.CYSE3["test_cases_sha256"])
    return json.loads(path.read_text())


def cyse3_image(source: str, data_dir: Path, record_id) -> Path:
    path = data_dir / "images" / f"{record_id}.png"
    if source != "fixture":
        _download(HF_URL.format(repo=core.CYSE3["repo"], rev=core.CYSE3["revision"],
                                path=f"images/{record_id}.png"), path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


# --- FigStep SafeBench -------------------------------------------------------------------
def figstep_dir(source: str, cache: Path | None) -> Path:
    if source == "fixture":
        return core.FIXTURES / "figstep"
    return (cache or default_cache()) / f"figstep-{core.FIGSTEP['revision'][:12]}"


def figstep_csv(source: str, data_dir: Path) -> str:
    path = data_dir / core.FIGSTEP["csv"]
    if source != "fixture":
        _download(GH_URL.format(repo=core.FIGSTEP["repo"], rev=core.FIGSTEP["revision"],
                                path=core.FIGSTEP["csv"]), path, core.FIGSTEP["csv_sha256"])
    return path.read_text(encoding="utf-8")


def figstep_image(source: str, data_dir: Path, row: dict) -> Path:
    rel = core.figstep_image_name(row)
    path = data_dir / rel
    if source != "fixture":
        _download(GH_URL.format(repo=core.FIGSTEP["repo"], rev=core.FIGSTEP["revision"],
                                path=rel), path)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def provenance(source: str) -> dict:
    if source == "fixture":
        return {"source": "fixture", "note": "tiny fixtures in the upstream layout; the numbers "
                "describe the mock models, not a benchmark result"}
    return {"source": "fetched",
            "cyse3": {k: core.CYSE3[k] for k in ("repo", "revision", "test_cases_sha256",
                                                 "license")},
            "figstep": {k: core.FIGSTEP[k] for k in ("repo", "revision", "csv_sha256",
                                                     "license")}}
