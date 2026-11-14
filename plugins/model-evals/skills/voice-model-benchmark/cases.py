#!/usr/bin/env python3
"""Seeded case selection from the vendored corpus (corpus/cases.jsonl).

    python cases.py --depth smoke --seed 20261114            # print the selected case ids
    python cases.py --depth 10 --out cases.jsonl             # write the selected cases

Selection is per case type (harmful, benign): `depth` cases of each, or every case at `full`.
The order is a hash of (seed, case id), so it is the same on every machine and Python
version, and a deeper run with the same seed contains every case of a shallower one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import evalkit  # noqa: E402

CORPUS = Path(__file__).resolve().parent / "corpus" / "cases.jsonl"
TYPES = ("harmful", "benign")
DEFAULT_SEED = 20261114


def load_cases(path: str | Path | None = None) -> list[dict]:
    """Cases as dicts with at least id, type and prompt. Extra fields are kept."""
    cases = []
    for n, line in enumerate(Path(path or CORPUS).read_text().splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = [k for k in ("id", "type", "prompt") if not row.get(k)]
        if missing:
            raise ValueError(f"case on line {n} is missing {missing}")
        if row["type"] not in TYPES:
            raise ValueError(f"case {row['id']}: type must be one of {TYPES}")
        cases.append(row)
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("case ids are not unique")
    return cases


def _rank(seed: int, case_id: str) -> str:
    return hashlib.sha256(f"{seed}:{case_id}".encode()).hexdigest()


def select(cases: list[dict], depth: int | None, seed: int = DEFAULT_SEED) -> list[dict]:
    """`depth` cases of each type (all of them when depth is None), in seeded order."""
    chosen = []
    for case_type in TYPES:
        pool = sorted((c for c in cases if c["type"] == case_type),
                      key=lambda c: _rank(seed, c["id"]))
        chosen += pool if depth is None else pool[:depth]
    return chosen


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--corpus", help="cases.jsonl to select from (default: the vendored corpus)")
    p.add_argument("--depth", default="smoke", help="smoke | standard | full | N (per case type)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--out", help="write the selected cases as JSON lines instead of listing ids")
    args = p.parse_args(argv)
    chosen = select(load_cases(args.corpus), evalkit.resolve_depth(args.depth), args.seed)
    if args.out:
        Path(args.out).write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in chosen))
        print(f"wrote {len(chosen)} case(s) to {args.out}")
    else:
        for c in chosen:
            print(c["type"], c["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
