#!/usr/bin/env python3
"""Rebuild the summary of a coding-guidance-benchmark run from its samples.jsonl.

    python report.py <EXP>/results [--baseline baseline] [--json <EXP>/summary.json] > <EXP>/summary.md

The runner already writes summary.md and summary.json; use this to re-read a run, or to name
a different arm as the baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import arms as arms_lib  # noqa: E402
import stats  # noqa: E402


def load(results: Path) -> tuple[list[dict], dict]:
    samples = results / "samples.jsonl" if results.is_dir() else results
    rows = [json.loads(line) for line in samples.read_text().splitlines() if line.strip()]
    run_path = samples.parent / "run.json"
    run = json.loads(run_path.read_text()) if run_path.is_file() else {}
    return rows, run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("results", help="the run's output directory, or its samples.jsonl")
    p.add_argument("--baseline", default=arms_lib.BASELINE, help="arm to compare the others against")
    p.add_argument("--json", help="also write the summary as JSON here")
    args = p.parse_args(argv)
    rows, run = load(Path(args.results))
    if not rows:
        print("no rows in samples.jsonl", file=sys.stderr)
        return 1
    summary = stats.summarise(rows, run.get("arms"), args.baseline, run.get("seed", 0))
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"run": {k: v for k, v in run.items() if k not in ("tasks", "header")}, **summary},
            indent=2))
    print(stats.render(summary, run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
