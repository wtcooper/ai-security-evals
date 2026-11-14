#!/usr/bin/env python3
"""Compare models from one or more model-benchmark runs.

    python report.py <EXP>/results/results.json [earlier/results.json ...] \
        [--baseline <model>] [--json <EXP>/summary.json] > <EXP>/summary.md

Pass results from an earlier run to compare a new model against it; the report refuses to
compare runs made at a different depth or seed, because they did not see the same samples.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import inspect_report  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(inspect_report.main([*sys.argv[1:], "--title", "model-benchmark summary"]))
