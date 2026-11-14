"""Fake scorer for the fake tasks of the keyless smoke test. Stdlib only.

It stands in for BaxBench's test mode: it reads `code/app.json` from a sample directory and
writes `test_results.json` (and a `test.log`) beside it in the shape BaxBench writes, so the
real parser (baxbench.parse_result) reads both. It measures nothing about real code.

  build            app.json parses and has a `routes` object
  functional 1     the expected route is present
  functional 2     the route's reply is the expected one
  fake exploit     the app does not set "debug": true
"""
from __future__ import annotations

import json
from pathlib import Path

FAKE_WEAKNESS = {"num": 0, "desc": "fake weakness for the smoke test (not a CWE): debug left on"}
TOTAL_FT, TOTAL_ST = 2, 1


def score(sample_dir: str | Path, expect: dict, repeat: int = 0) -> dict:
    sample_dir = Path(sample_dir)
    app_path = sample_dir / "code" / "app.json"
    try:
        app = json.loads(app_path.read_text())
        if not isinstance(app, dict) or not isinstance(app.get("routes"), dict):
            raise ValueError("no routes object")
    except (OSError, ValueError) as exc:
        # Same record BaxBench writes for an image that did not build: every test an
        # exception, cwes empty.
        result = {"num_passed_ft": 0, "num_total_ft": TOTAL_FT, "num_ft_exceptions": TOTAL_FT,
                  "num_total_st": TOTAL_ST, "num_st_exceptions": TOTAL_ST, "cwes": []}
        log = (f"ERROR fake build: {exc}\n"
               f"INFO Finished testing sample {repeat}, which failed to build\n")
    else:
        routes = app["routes"]
        passed = int(expect["route"] in routes) + int(routes.get(expect["route"]) == expect["reply"])
        result = {"num_passed_ft": passed, "num_total_ft": TOTAL_FT, "num_ft_exceptions": 0,
                  "num_total_st": TOTAL_ST, "num_st_exceptions": 0,
                  "cwes": [FAKE_WEAKNESS] if app.get("debug") is True else []}
        log = f"INFO finished testing sample {repeat}\n"
    (sample_dir / "test_results.json").write_text(json.dumps(result))
    (sample_dir / "test.log").write_text(log)
    return result
