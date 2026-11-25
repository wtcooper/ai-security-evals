#!/usr/bin/env python3
"""Run a scenario pack across arms (model x harness x safeguards) and write the results.

    python run_benchmark.py --scenarios <pack dir> --arms arms.json \
        --harness <name> --harness-module <your_harness.py> --scorer <your_scorer.py> \
        --depth standard --out <EXP>/results

This is a scaffold. It ships the scenario format, the sweep, the statistics and the report,
plus a mock harness and scorer for a keyless smoke test:

    python run_benchmark.py --scenarios scenarios.example --arms scenarios.example/arms.mock.json \
        --harness mock --scorer mock --depth smoke --out /tmp/agent-misuse-smoke

The scenarios, the real harness and the outcome scorer are yours to supply:
references/build-guide.md says how.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import evalkit  # noqa: E402
import interfaces  # noqa: E402
import metrics  # noqa: E402
import scenarios  # noqa: E402


def load_arms(path: str) -> list[dict]:
    arms = json.loads(Path(path).read_text())
    names = [a.get("name") for a in arms]
    if not arms or None in names or len(set(names)) != len(names):
        raise ValueError(f"arms need unique `name`s: {names}")
    for arm in arms:
        for key in ("model", "harness", "safeguards"):
            if key not in arm:
                raise ValueError(f"arm {arm['name']!r} needs `{key}` (so the report can say "
                                 "what differed between arms)")
    return arms


def pack_files(pack: dict) -> list[Path]:
    """Every file of the pack folder: what the corpus fingerprint covers."""
    return sorted(p for p in Path(pack["_folder"]).rglob("*") if p.is_file())


def plan_rows(pack: dict, todo: list[dict], repeats: int) -> list[dict]:
    """Cost-plan rows. The paired comparisons are on the default-framing restricted tasks and
    on the permitted twins, so those are the rows whose power matters."""
    groups = (("restricted, default framing",
               [t for t in todo if t["kind"] == "restricted" and t["framing"] == "default"]),
              ("permitted twins", [t for t in todo if t["kind"] == "permitted"]),
              ("restricted, other framings",
               [t for t in todo if t["kind"] == "restricted" and t["framing"] != "default"]))
    return [{"name": f"{pack['name']}: {label}", "samples": len(tasks),
             "calls": len(tasks) * repeats,
             "note": f" agent runs ({repeats} per task)" if repeats > 1 else " agent runs"}
            for label, tasks in groups if tasks]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scenarios", required=True, help="scenario pack folder (holds pack.json)")
    p.add_argument("--arms", required=True, help="JSON list of arms")
    p.add_argument("--harness", default="mock", help="`mock`, or a name your harness module knows")
    p.add_argument("--harness-module", help="Python file defining make_harness(name)")
    p.add_argument("--scorer", default="mock", help="`mock`, or a Python file defining score(task, run)")
    p.add_argument("--depth", default="standard", help="smoke | standard | full | N (pairs per arm)")
    p.add_argument("--seed", type=int, default=20261114)
    p.add_argument("--baseline", help="arm to compare the others against (default: the first)")
    p.add_argument("--repeats", type=int, default=1,
                   help="run every task this many times per arm; a task's outcome is the "
                        "majority of its repeats and the report shows how often they disagree")
    p.add_argument("--max-unscored", type=float, default=0.05,
                   help="validity flag: share of runs with no verdict")
    p.add_argument("--min-permitted-completion", type=float, default=0.3,
                   help="validity flag: completion of the permitted twins below this")
    p.add_argument("--ceiling", type=float, default=metrics.CEILING,
                   help="validity flag: every arm at or above this rate on a measure "
                        "(default %(default)s)")
    p.add_argument("--out", default="results")
    p.add_argument("--plan", action="store_true", help="print what would run and exit")
    p.add_argument("--plan-reason",
                   help="why this run's analysis plan differs from the one already registered "
                        "in --out (kept with the amendment in plan.json)")
    args = p.parse_args(argv)
    if args.repeats < 1:
        p.error("--repeats must be at least 1")

    mock = args.harness == "mock"
    pack = scenarios.load_pack(args.scenarios)
    problems = scenarios.validate_pack(pack, allow_placeholders=mock)
    if problems:
        print("scenario pack is not usable:", *problems, sep="\n  ", file=sys.stderr)
        return 2
    arms = load_arms(args.arms)
    depth = evalkit.resolve_depth(args.depth)
    pair_ids = scenarios.select_pairs(pack, depth, args.seed)
    todo = scenarios.tasks(pack, pair_ids)
    # Two paired tests (restricted, permitted) per arm beyond the baseline.
    evalkit.print_plan(plan_rows(pack, todo, args.repeats), arms=len(arms),
                       comparisons=2 * max(0, len(arms) - 1))
    print("  tokens per agent run depend on the harness", file=sys.stderr)
    if args.plan:
        return 0

    harness = interfaces.get_harness(args.harness, args.harness_module)
    scorer = interfaces.get_scorer(args.scorer)
    if mock != (args.scorer == "mock"):
        p.error("the mock harness and the mock scorer only work together")
    # A real harness must show its sandbox cannot reach the network before any task is given.
    pre = harness.preflight()
    if not pre.get("egress_blocked"):
        print("refusing to run: the harness preflight did not confirm that the sandbox has no "
              f"network access ({pre}). See references/build-guide.md, step 4.", file=sys.stderr)
        return 3

    out = Path(args.out)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    samples = out / "samples.jsonl"
    samples.write_text("")
    # The analysis plan, on record before the first task runs; the report lists departures.
    baseline = args.baseline or arms[0]["name"]
    scorer_path = Path(args.scorer) if args.scorer.endswith(".py") else None
    bundled = Path(pack["_folder"]) == (HERE / "scenarios.example").resolve()
    evalkit.register_plan(out, {
        "arms": [a["name"] for a in arms], "baseline": baseline,
        "measures": list(metrics.MEASURES),
        "slices": {"categories": sorted({t["category"] for t in todo}),
                   "framings": sorted({t["framing"] for t in todo})},
        "depth": args.depth, "seed": args.seed, "repeats": args.repeats,
        "pack": {"name": pack["name"], "version": pack.get("version"), "pairs": pair_ids},
        "harness": args.harness,
        "scorer": {"name": args.scorer,
                   "sha256": evalkit.fingerprint(scorer_path) if scorer_path else None},
        "judge": getattr(getattr(scorer, "module", None), "JUDGE", None),
        "corpus": evalkit.corpus_record(pack_files(pack), bundled=bundled),
        "criteria": evalkit.criteria_record()}, reason=args.plan_reason)
    for arm in arms:
        for task, rep in ((t, k) for t in todo for k in range(args.repeats)):
            started = time.time()
            workdir = out / "runs" / arm["name"] / task["id"]
            if args.repeats > 1:
                workdir = workdir / f"r{rep}"
            workdir.mkdir(parents=True, exist_ok=True)
            task = {**task, "repeat": rep}
            try:
                run = harness.run(task, arm, workdir)
            except Exception as exc:  # noqa: BLE001 - one failed run must not stop the sweep
                run = {"error": f"{type(exc).__name__}: {exc}"}
            criteria = None
            if run.get("error"):
                outcome, evidence = "error", run["error"]
            else:
                try:
                    verdict = scorer.score(task, run)
                except Exception as exc:  # noqa: BLE001
                    verdict = {"outcome": "unscored", "evidence": f"scorer failed: {exc}"}
                outcome = interfaces.check_outcome(task, verdict)
                evidence = (verdict or {}).get("evidence", "")
                criteria = (verdict or {}).get("criteria")
            (workdir / "run.json").write_text(json.dumps(
                {k: v for k, v in run.items() if k != "mock_outcome"}, indent=1, default=str))
            evalkit.append_samples(samples, [{
                "arm": arm["name"], "target": task["pair"], "sample": task["id"],
                "task": task["id"], "repeat": rep, "kind": task["kind"], "framing": task["framing"],
                "category": task["category"], "outcome": outcome, "evidence": evidence,
                "criteria": criteria,
                "model": arm["model"], "harness": arm["harness"],
                "harness_version": run.get("harness_version"), "safeguards": arm["safeguards"],
                "tokens": run.get("tokens"), "wall_s": round(time.time() - started, 2)}])
        print(f"[{arm['name']}] {len(todo) * args.repeats} runs", file=sys.stderr, flush=True)

    rows = metrics.load_samples(samples)
    summary = metrics.summarize(rows, args.baseline, args.max_unscored,
                                args.min_permitted_completion, args.ceiling)
    header = {"pack": pack["name"], "pairs": len(pair_ids), "depth": args.depth, "seed": args.seed,
              "repeats": args.repeats, "harness": args.harness, "scorer": args.scorer}
    plan = evalkit.load_plan(out)
    (out / "summary.json").write_text(json.dumps(
        {**header, "arms": arms, "context": evalkit.load_context(), **summary,
         "plan_deviations": evalkit.plan_deviations(plan, {
             "arms": summary["arms"], "baseline": summary["baseline"], "depth": args.depth,
             "seed": args.seed, "repeats": args.repeats})}, indent=2))
    (out / "summary.md").write_text(metrics.render(summary, header, plan))
    print(out / "summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
