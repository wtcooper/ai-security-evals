#!/usr/bin/env python3
"""Known-lane importer: read the two published benchmarks in their upstream format, at a
pinned revision, and check (or rebuild) the vendored copy in corpus/cases.jsonl.

    python corpus/fetch_known.py --check                    # fetch both files at the pins, compare
    python corpus/fetch_known.py --from-dir <dir> --check   # the same, from files already downloaded
    python corpus/fetch_known.py --out <cases.jsonl>        # write cases built from upstream

The two benchmarks and their pins (verified 2026-11-21 from the repositories themselves):

    advbench  github.com/llm-attacks/llm-attacks  data/advbench/harmful_behaviors.csv
              MIT; 520 rows, columns goal,target; each `goal` is one harmful request
    xstest    github.com/paul-rottger/xstest      xstest_prompts.csv
              CC-BY-4.0 (attribution required); 450 rows, columns id,prompt,type,label,focus,note;
              label "safe" (250) or "unsafe" (200 contrasts)

Both are small text files whose licences allow redistribution, so the skill vendors them
(corpus/cases.jsonl); this script is how that copy is checked against the source. Only the
two CSV files are downloaded (about 120 KB), each verified against its pinned sha256.

Case ids, as the vendored corpus uses them:
    advbench-<row>               row = 0-based data row in harmful_behaviors.csv
    xstest-<label>-<row>         row = 0-based data row in xstest_prompts.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = {
    "advbench": {
        "repo": "llm-attacks/llm-attacks",
        "commit": "098262edf85f807224e70ecd87b9d83716bf6b73",
        "path": "data/advbench/harmful_behaviors.csv",
        "sha256": "6cd1a5c63c07610d7eb67307772ee5606017ee950b5770ab288a2c487489d3e1",
        "license": "MIT", "source": "AdvBench", "rows": 520,
    },
    "xstest": {
        "repo": "paul-rottger/xstest",
        "commit": "d7bb5bd738c1fcbc36edd83d5e7d1b71a3e2d84d",
        "path": "xstest_prompts.csv",
        "sha256": "11783fb294ed017473ee53c207d71f2161c7672c8d0b037501e78387f801cb5a",
        "license": "CC-BY-4.0", "source": "XSTest", "rows": 450,
    },
}
RAW = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def url(name: str) -> str:
    return RAW.format(**PINS[name])


def fetch(name: str, timeout: float = 60.0) -> str:
    """The pinned file's text, after checking its hash."""
    with urllib.request.urlopen(url(name), timeout=timeout) as resp:
        data = resp.read()
    return verify(name, data)


def verify(name: str, data: bytes) -> str:
    got = hashlib.sha256(data).hexdigest()
    if got != PINS[name]["sha256"]:
        raise ValueError(f"{name}: sha256 {got} does not match the pin {PINS[name]['sha256']}")
    return data.decode("utf-8")


def advbench_cases(text: str) -> list[dict]:
    """harmful_behaviors.csv (columns goal,target) -> harmful cases."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None or "goal" not in reader.fieldnames:
        raise ValueError("not AdvBench harmful_behaviors.csv: no 'goal' column")
    return [{"id": f"advbench-{i}", "type": "harmful", "source": "AdvBench", "license": "MIT",
             "prompt": row["goal"]} for i, row in enumerate(reader)]


def xstest_cases(text: str) -> list[dict]:
    """xstest_prompts.csv (columns id,prompt,type,label,...) -> safe prompts as benign cases
    and unsafe contrasts as harmful cases."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    need = {"prompt", "label", "type"}
    if reader.fieldnames is None or not need <= set(reader.fieldnames):
        raise ValueError(f"not XSTest xstest_prompts.csv: needs columns {sorted(need)}")
    out = []
    for i, row in enumerate(reader):
        if row["label"] not in ("safe", "unsafe"):
            raise ValueError(f"xstest row {i}: label {row['label']!r}")
        out.append({"id": f"xstest-{row['label']}-{i}",
                    "type": "benign" if row["label"] == "safe" else "harmful",
                    "source": "XSTest", "license": "CC-BY-4.0", "prompt": row["prompt"],
                    "xstest_type": row["type"]})
    return out


def upstream_cases(texts: dict[str, str]) -> list[dict]:
    return advbench_cases(texts["advbench"]) + xstest_cases(texts["xstest"])


def compare(vendored: list[dict], upstream: list[dict], max_chars: int | None = None) -> dict:
    """What differs between the vendored corpus and upstream, on id, type, source and prompt.
    With `max_chars`, upstream cases longer than that are expected to be absent."""
    up = {c["id"]: c for c in upstream}
    mine = {c["id"]: c for c in vendored}
    changed = [i for i in mine if i in up and any(mine[i][k] != up[i][k]
                                                  for k in ("type", "source", "prompt"))]
    extra = [i for i in mine if i not in up]
    missing = [i for i in up if i not in mine
               and not (max_chars and len(up[i]["prompt"]) > max_chars)]
    return {"vendored": len(mine), "upstream": len(up), "changed": changed,
            "not_upstream": extra, "missing": missing,
            "same": not (changed or extra or missing)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--from-dir", help="a folder holding harmful_behaviors.csv and "
                                      "xstest_prompts.csv already downloaded")
    p.add_argument("--check", action="store_true", help="compare with corpus/cases.jsonl")
    p.add_argument("--out", help="write the upstream cases as JSON lines")
    args = p.parse_args(argv)
    if not (args.check or args.out):
        p.error("pass --check, --out, or both")
    texts = {}
    for name, pin in PINS.items():
        if args.from_dir:
            texts[name] = verify(name, (Path(args.from_dir) / Path(pin["path"]).name).read_bytes())
        else:
            print(f"fetching {url(name)}", file=sys.stderr)
            texts[name] = fetch(name)
    cases = upstream_cases(texts)
    if args.out:
        Path(args.out).write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in cases))
        print(f"wrote {len(cases)} case(s) to {args.out}")
    if args.check:
        vendored = [json.loads(ln) for ln in (HERE / "cases.jsonl").read_text().splitlines()
                    if ln.strip()]
        max_chars = json.loads((HERE / "manifest.json").read_text())["rule"]["max_chars"]
        result = compare(vendored, cases, max_chars)
        print(json.dumps({k: (v[:5] if isinstance(v, list) else v) for k, v in result.items()}, indent=2))
        return 0 if result["same"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
