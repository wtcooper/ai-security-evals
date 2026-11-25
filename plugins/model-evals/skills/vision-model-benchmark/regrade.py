#!/usr/bin/env python3
"""Re-grade a finished run's judged checks with a second judge, without re-running any model.

    .venv-inspect/bin/python regrade.py <EXP> --judge <second judge> [--limit N]
    .venv-inspect/bin/python regrade.py <EXP> --judge <same or other judge> --alt-rubric

Reads the Inspect logs the run saved, scores the stored replies again and writes
<EXP>/samples_regrade.jsonl (the same rows, graded by the second judge), then
<EXP>/judge_check.md and .json (lib/judgecheck.py: agreement, kappa, rates and order under
each judge, length sensitivity), and rewrites summary.md so it points at the check.

--alt-rubric grades the judged custom and FigStep checks with the reworded template
(vmb_core.JUDGE_TEMPLATE_ALT, its own rubric version) instead of the main one; the
CyberSecEval 3 checks keep the upstream template and are not re-graded then. The second judge
must not be a model under test (the shared runner refuses). Deterministic checks (canary,
secret, tool call) have nothing to re-grade. Run from this skill's folder, like the run itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
sys.path.insert(0, str(HERE))
import inspect_suite as suite  # noqa: E402
import run_benchmark as rb  # noqa: E402


def regradable(benches: list[str], alt: bool) -> list[str]:
    """Judged checks; with the reworded rubric, only those graded by this skill's template."""
    return [b for b in benches if rb.CHECKS[b][6] and not (alt and rb.CHECKS[b][2] != "helped")]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("exp", type=Path, help="the experiment folder of a finished run")
    p.add_argument("--judge", required=True, help="second judge: a gateway alias or an "
                   "Inspect model string; never a model under test")
    p.add_argument("--alt-rubric", action="store_true",
                   help="grade with the reworded template instead of the main one")
    p.add_argument("--limit", type=int, help="re-grade only the first N samples of each log")
    p.add_argument("--keep-provider-env", action="store_true")
    a = p.parse_args(argv)

    results = a.exp / "results.json"
    if not results.is_file():
        p.error(f"{results} not found: run run_benchmark.py into this folder first")
    res = json.loads(results.read_text())
    benches = regradable(list(res.get("checks") or {}), a.alt_rubric)
    if not benches:
        p.error("this run has no judged check to re-grade")
    judge = rb.model_string(a.judge)
    if judge == res.get("judge") and not a.alt_rubric:
        p.error("that is the run's own judge: name another judge, or pass --alt-rubric")
    if judge in {r.get("model") for r in res.get("rows", [])}:
        p.error(f"{a.judge} is a model under test in this run; a judge never is")

    checks = rb.build_checks(benches, a.exp / "inputs", {}, None,
                             "alt" if a.alt_rubric else "main")
    # The shared runner finds a check by id in the suite; this skill's checks are built here.
    suite.BY_ID.update({c.id: c for c in checks})
    rb.route([a.judge], p.error)
    if judge.startswith("vmbmock/"):
        import mock_vision  # noqa: F401  (registers the vmbmock provider)

    import inspect_runner
    import judgecheck
    import report
    out = a.exp / "samples_regrade.jsonl"
    inspect_runner.regrade(str(results), judge, out=str(out), limit=a.limit,
                           keep_provider_env=a.keep_provider_env)
    records = res.get("corpus") or rb.corpora(res.get("known_source", "fetch"))
    rb.stamp_corpus(out, records)
    code = judgecheck.main(["--primary", str(a.exp / "samples.jsonl"), "--secondary", str(out),
                            "--out", str(a.exp), "--group", "target"])
    report.write(a.exp)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
