#!/usr/bin/env python3
"""Grade a run's stored reply transcripts again with a second judge, without running the
model under test again, and check whether the result depends on the judge.

    VOICE_JUDGE_BASE_URL=<endpoint>/v1 VOICE_JUDGE_API_KEY=... \
    python3 regrade.py <EXP> --judge <another judge model> [--alt-rubric] [--limit N]
    python3 regrade.py <EXP> --judge mock --alt-rubric        # keyless, on a run against the mock

Every known-lane row of <EXP>/samples.jsonl that the run's judge graded is graded again from
its stored request and transcript. Rows graded without a judge (a provider content filter, a
reply that was only a function call, a target error) and the custom lane (deterministic, no
judge) are not re-graded. Writes:

  <EXP>/samples_regrade.jsonl   the re-graded rows: same fields, the second judge's verdict,
                                `good` and `judge`
  <EXP>/judge_check.md / .json  lib/judgecheck.py on the two: agreement and Cohen's kappa per
                                case type, each input condition's good rate under each judge
                                and whether their order changes, and sensitivity to reply length

and rewrites summary.md, which then mentions the check. `--alt-rubric` grades with the
reworded rubric (judge.ALT_RUBRIC_VERSION); with the run's own judge model it tests the
wording alone. To compare models across runs under both judges, concatenate their
samples.jsonl and samples_regrade.jsonl files and run
`python3 lib/judgecheck.py --primary <all samples> --secondary <all regrades> --out <dir> --group threat`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import evalkit  # noqa: E402
import judge as judgelib  # noqa: E402
import judgecheck  # noqa: E402
import report  # noqa: E402
import run_benchmark  # noqa: E402

OUT_FILE = "samples_regrade.jsonl"


def regradable(row: dict) -> bool:
    """A known-lane row the run's judge graded from a transcript."""
    return ((row.get("lane") or "known") == "known" and row.get("graded_by") == "judge"
            and bool(row.get("transcript")))


def regrade_rows(rows: list[dict], judge, concurrency: int = 4) -> list[dict]:
    """The rows graded by `judge` from their stored prompt and transcript. The judge sees
    the request and the reply only; the direction is applied here, as in the run."""
    def one(row: dict) -> dict:
        graded = judge.grade({"prompt": row["prompt"]}, row["transcript"])
        return {**row, "verdict": graded["verdict"], "judge": judge.id,
                "judge_reason": graded["reason"], "judge_raw": graded["raw"],
                "judge_error": graded["error"],
                "good": run_benchmark.known_good(row["case_type"], graded["verdict"])}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        return list(pool.map(one, rows))


def check_rows(rows: list[dict]) -> list[dict]:
    """Rows as judgecheck reads them for one run: the input condition is the arm and the case
    type is the row, so the check shows whether the order of conditions changes."""
    return [{"arm": report.cond(r), "threat": f"{r['case_type']} requests", "lane": "known",
             "case": r.get("case") or f"{r['sample']}/{report.cond(r)}",
             "repeat": r.get("repeat") or 0, "good": r.get("good"), "judge": r.get("judge"),
             "response_chars": r.get("response_chars")} for r in rows]


def write_check(exp: Path, primary: list[dict], secondary: list[dict]) -> dict:
    res = judgecheck.check(check_rows(primary), check_rows(secondary), by="threat")
    lines = judgecheck.render(res).split("\n")
    note = ("Arms here are the run's input conditions (text, clean speech, each perturbation); "
            "rows are the case types. Good means the safe outcome for that case type.")
    lines[1:1] = ["", note]
    (exp / "judge_check.json").write_text(json.dumps(res, indent=2) + "\n")
    (exp / "judge_check.md").write_text("\n".join(lines))
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("exp", help="the experiment folder holding samples.jsonl")
    p.add_argument("--judge", required=True,
                   help="second judge model on VOICE_JUDGE_BASE_URL, or 'mock' for a mock run")
    p.add_argument("--alt-rubric", action="store_true",
                   help=f"grade with the reworded rubric (version {judgelib.ALT_RUBRIC_VERSION})")
    p.add_argument("--limit", type=int, help="re-grade only the first N judged rows")
    p.add_argument("--concurrency", type=int, default=4, help="parallel judge calls")
    args = p.parse_args(argv)

    exp = Path(args.exp)
    samples = exp / "samples.jsonl"
    if not samples.is_file():
        p.error(f"no samples.jsonl in {exp}")
    rows = report.load_samples(samples)
    run_path = exp / "results" / "run.json"
    run = json.loads(run_path.read_text()) if run_path.is_file() else {}
    targets = sorted({r["target"] for r in rows})
    rubric = judgelib.ALT_RUBRIC_VERSION if args.alt_rubric else judgelib.RUBRIC_VERSION

    judge_base = os.environ.get("VOICE_JUDGE_BASE_URL")
    judge_key = os.environ.get("VOICE_JUDGE_API_KEY")
    clean = evalkit.scrub_provider_credentials(dict(os.environ))
    os.environ.clear()
    os.environ.update(clean)
    if args.judge == "mock":
        if not (run.get("target") or {}).get("mock"):
            p.error("--judge mock grades only the mock server's fixed phrases; use it on a mock run")
        judge = judgelib.MockJudge(rubric)
    else:
        if any(judgelib.same_model(args.judge, t) for t in targets):
            p.error("the judge must not be the model under test")
        if not judge_base:
            p.error("VOICE_JUDGE_BASE_URL is not set (an OpenAI-compatible endpoint ending in /v1)")
        judge = judgelib.ChatJudge(args.judge, judge_base, judge_key, rubric=rubric)

    primary = [r for r in rows if regradable(r)]
    if not primary:
        p.error("no row of this run was graded by a judge; there is nothing to re-grade")
    if judge.id in report.judges_of(primary):
        p.error(f"{judge.id} graded these rows already; name another judge model or pass "
                "--alt-rubric")
    if args.limit:
        primary = primary[:args.limit]
    print(f"re-grading {len(primary)} transcript(s) with {judge.id} ...", file=sys.stderr)
    regraded = regrade_rows(primary, judge, args.concurrency)
    (exp / OUT_FILE).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in regraded))
    res = write_check(exp, primary, regraded)

    previous = exp / "summary.json"
    limits = dict(json.loads(previous.read_text()).get("validity_limits") or {}) \
        if previous.is_file() else {}
    ceiling = limits.pop("ceiling", report.CEILING)
    report.write_summary(samples, exp, limits, run or None, ceiling=ceiling)
    print(f"agreement {res['agreement']}, kappa {res['kappa']} on {res['paired_cases']} case(s)",
          file=sys.stderr)
    print(exp / "judge_check.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
