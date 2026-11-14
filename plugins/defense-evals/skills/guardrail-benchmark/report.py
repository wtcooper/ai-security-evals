#!/usr/bin/env python3
"""In-line mode report: each guardrail arm against the baseline arm, on the same samples.

    python report.py <EXP>/results/results.json [--baseline baseline] \
        [--json <EXP>/summary.json] > <EXP>/summary.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import inspect_report  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(inspect_report.main(
        [*sys.argv[1:], "--title", "guardrail-benchmark (in-line) summary"]))
