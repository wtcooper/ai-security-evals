#!/usr/bin/env python3
"""Re-grade a finished run's judged images with a second judge, without generating again.

  python scripts/regrade.py --exp EXP --judge-url https://judge2/v1 --judge-model MODEL_J2
  python scripts/regrade.py --exp EXP --judge-url https://judge/v1 --judge-model MODEL_J --alt-rubric
  python scripts/regrade.py --mock --exp EXP          # the second mock judge, mock-judge-2

Needs the images: run the benchmark with --keep-images (each judged row then names its file;
the file's sha256 is checked against the row). Writes EXP/samples_regrade.jsonl, the judged
rows of samples.jsonl graded again (same rows, another `judge`, `good` recomputed), then
EXP/judge_check.md and .json (lib/judgecheck.py, grouped by threat: agreement, Cohen's kappa,
each arm's rate and order under each judge) and rewrites summary.md to point at the check.

--alt-rubric grades with the reworded wording in core.json (`alt_judge_system`,
`alt_rubrics`, rubric version cases.ALT_RUBRIC_VERSION), so the same judge model can be asked
the question differently. The second judge is never one of the arms. Decoded payloads and
refusals have no judge and are not re-graded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SKILL / "lib"))
import cases as caselib  # noqa: E402
import clients  # noqa: E402
import judgecheck  # noqa: E402
import run_benchmark as rb  # noqa: E402
import scoring  # noqa: E402

MOCK_SECOND_JUDGE = "mock-judge-2"


def _flat(row: dict) -> dict:
    """judgecheck compares judges by a string: use the judge id."""
    j = row.get("judge")
    return dict(row, judge=j.get("id") or j.get("model")) if isinstance(j, dict) else row


def alt_rubrics(exp: Path, meta: dict) -> dict[str, str]:
    """Reworded rubric per case id, expanded with the slots and extra cases the run used."""
    corpus = caselib.load_corpus()
    if meta.get("extra_cases"):
        corpus = caselib.merge_extra(corpus, meta["extra_cases"])
    slots = Path(meta["slots"])
    slots = slots if slots.is_absolute() else SKILL / slots
    run, _ = caselib.expand(corpus, caselib.load_slots(slots), all_values=meta["depth"] == "full")
    return {c["case"]: c["rubric_alt"] for c in run if c.get("rubric_alt")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--exp", required=True, type=Path, help="experiment folder of a finished run")
    ap.add_argument("--judge-url", help="OpenAI-compatible chat base URL for the second judge")
    ap.add_argument("--judge-model", help="second vision judge; never one of the arms")
    ap.add_argument("--judge-key-env", default="JUDGE_API_KEY")
    ap.add_argument("--judge-extra", default="{}", help="JSON merged into each judge request body")
    ap.add_argument("--alt-rubric", action="store_true", help="grade with the reworded wording")
    ap.add_argument("--limit", type=int, help="re-grade at most N judged images per arm")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--mock", action="store_true", help="use the bundled mock's second judge")
    a = ap.parse_args(argv)

    exp = a.exp
    if not (exp / "samples.jsonl").is_file() or not (exp / "summary.json").is_file():
        ap.error(f"{exp} holds no finished run (samples.jsonl and summary.json)")
    rows = [json.loads(x) for x in (exp / "samples.jsonl").read_text().splitlines() if x.strip()]
    meta = json.loads((exp / "summary.json").read_text())["meta"]
    arms = list(dict.fromkeys(r["arm"] for r in rows))
    server = None
    if a.mock:
        import mock_server
        server = mock_server.serve(0)
        a.judge_url = a.judge_url or f"http://127.0.0.1:{server.server_port}/v1"
        a.judge_model = a.judge_model or MOCK_SECOND_JUDGE
    if not (a.judge_url and a.judge_model):
        ap.error("route the second judge with --judge-url and --judge-model (or --mock)")
    if a.judge_model in arms:
        ap.error(f"{a.judge_model!r} is an arm of this run; a judge is never the model under test")
    if a.judge_model == meta.get("judge_model") and not a.alt_rubric:
        ap.error("that is the run's own judge: name another judge model, or pass --alt-rubric")

    judged = [r for r in rows if rb.was_judged(r)]
    if a.limit is not None:
        seen: Counter = Counter()
        kept = []
        for r in judged:
            seen[r["arm"]] += 1
            if seen[r["arm"]] <= a.limit:
                kept.append(r)
        judged = kept
    corpus = caselib.load_corpus()
    system = corpus["alt_judge_system"] if a.alt_rubric else corpus["judge_system"]
    alt = alt_rubrics(exp, meta) if a.alt_rubric else {}
    key = os.environ.get(a.judge_key_env)
    extra = json.loads(a.judge_extra)

    def grade(row: dict) -> dict | None:
        path = exp / row["image_file"] if row.get("image_file") else None
        if path is None or not path.is_file():
            return None
        image = path.read_bytes()
        if hashlib.sha256(image).hexdigest() != row.get("image_sha256"):
            return None
        rubric = alt.get(row["case"]) if a.alt_rubric else row["judge"]["rubric"]
        if not rubric:
            return None
        answer = clients.judge(a.judge_url, a.judge_model, rubric, image, system, key, extra,
                               a.timeout)
        new = dict(row, judge=rb.judge_record(a.judge_model, rubric, answer, a.alt_rubric))
        new["good"] = scoring.request_good({"kind": row["kind"], "scorer": "judge"},
                                           row["outcome"], answer["verdict"])
        return new

    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
        graded = list(pool.map(grade, judged))
    if server:
        server.shutdown()
    regraded = [g for g in graded if g is not None]
    missing = len(judged) - len(regraded)
    with open(exp / "samples_regrade.jsonl", "w") as fh:
        for r in regraded:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    print(f"re-graded {len(regraded)} of {len(judged)} judged image(s) with {a.judge_model}"
          + (f"; {missing} had no kept image (run with --keep-images)" if missing else ""))
    if not regraded:
        return 1

    res = judgecheck.check([_flat(r) for r in judged], [_flat(r) for r in regraded], "threat")
    (exp / "judge_check.json").write_text(json.dumps(res, indent=2))
    (exp / "judge_check.md").write_text(judgecheck.render(res))
    rb.rewrite_summary(exp)
    print(exp / "judge_check.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
