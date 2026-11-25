#!/usr/bin/env python3
"""A/B test: does what is placed in front of a coding agent change the security of its code?

    python run_benchmark.py --arms <dir of arm folders> --harness claude_code@<version> \
        --model <inspect model> --depth smoke --repeats 1 --out <EXP>/results [--plan]

The arms are the one thing that varies: the baseline (nothing installed, always included) and
one arm per subfolder of --arms. Every arm builds the same seeded tasks with the same harness
and model. Tasks and scoring come from BaxBench, cloned at a pinned commit at run time.

Keyless smoke test (mock harness, bundled fake tasks, fake scorer):

    python run_benchmark.py --arms arms --harness mock --tasks fixtures/fake_tasks.json \
        --depth smoke --repeats 2 --out /tmp/coding-guidance-smoke
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import arms as arms_lib  # noqa: E402
import baxbench  # noqa: E402
import evalkit  # noqa: E402
import fake_scorer  # noqa: E402
import mock_harness  # noqa: E402
import report  # noqa: E402
import stats  # noqa: E402
import tasks as tasks_lib  # noqa: E402
import transcript as transcript_lib  # noqa: E402

REAL_HARNESSES = ("claude_code", "codex_cli", "gemini_cli", "opencode")
SANDBOX_HARNESSES = REAL_HARNESSES + ("mock-sandbox",)
ALL_HARNESSES = ("mock",) + SANDBOX_HARNESSES
UNPINNED = ("auto", "sandbox", "stable", "latest")
DEFAULT_SEED = 20260809


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-") or "x"


def parse_harnesses(spec: str) -> list[dict]:
    """`name@version[,name@version]`. A real harness must say which version to install."""
    out = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        name, _, version = part.partition("@")
        if name not in ALL_HARNESSES:
            raise ValueError(f"unknown harness {name!r}; choose from {', '.join(ALL_HARNESSES)}")
        if name in REAL_HARNESSES and not version:
            raise ValueError(f"pin the harness version, e.g. {name}@<x.y.z>. "
                             f"{name}@stable or {name}@latest is accepted but is recorded as "
                             "not pinned.")
        out.append({"name": name, "version": version or mock_harness.VERSION})
    if not out:
        raise ValueError("--harness is empty")
    return out


def model_dir(harness: str, model: str, arm: str) -> str:
    """The <model> level of BaxBench's results layout: one directory per cell and arm."""
    return f"{slug(harness)}__{slug(model)}__{arm}"


def print_plan(arm_list: list[dict], selected: list[dict], repeats: int, cells: list[dict],
               source: str, file=None) -> dict:
    file = file or sys.stderr
    per_arm = len(selected) * repeats
    total = per_arm * len(arm_list) * len(cells)
    frameworks = Counter(t["framework"] for t in selected)
    sandboxed = any(c["harness"] in SANDBOX_HARNESSES for c in cells)
    print(f"plan: {len(selected)} task(s) x {repeats} repeat(s) x {len(arm_list)} arm(s) "
          f"[{', '.join(a['name'] for a in arm_list)}] x {len(cells)} harness/model cell(s) "
          f"[{'; '.join(c['harness'] + '@' + c['harness_version'] + ' / ' + c['model'] for c in cells)}]",
          file=file)
    print(f"  per arm, per cell   {per_arm} agent run(s) and {per_arm} app build(s) to score "
          "(one image build, then its functional tests and exploits)", file=file)
    print(f"  whole run           {total} agent run(s), {total} app build(s)", file=file)
    if source == "baxbench" and sandboxed:
        print(f"  agent images        between {len(frameworks)} and {min(len(selected), 7 * len(frameworks))}: "
              "one per framework, plus one for each set of system packages a drawn scenario adds; "
              "built once and shared by every arm", file=file)
    print("  frameworks drawn    " + ", ".join(f"{k} x{v}" for k, v in sorted(frameworks.items())),
          file=file)
    # McNemar is on one outcome per task, three metrics per arm beyond the baseline, per cell;
    # the report Holm-adjusts across all of them.
    comparisons = max(1, len(arm_list) - 1) * len(stats.METRICS) * len(cells)
    print(f"  power               {evalkit.power_note(len(selected), comparisons)}"
          + ("" if len(arm_list) > 1 else " (if an arm is added)"), file=file)
    for arm in arm_list:
        print(f"  arm {arm['name']:<16}{arm['files']} file(s); control type: "
              f"{arm['control_type'] or 'not labelled'}", file=file)
    print("  tokens              not estimated: token cost depends on the harness, the model and "
          "how long the agent works on a task. The mock harnesses use none. Run --depth smoke "
          "first and read the Cost table.", file=file)
    return {"runs_per_arm": per_arm, "runs_total": total, "builds_total": total,
            "frameworks": dict(frameworks), "comparisons": comparisons}


def corpus(args) -> dict:
    """What the tasks come from: BaxBench at its pinned commit, the bundled fake tasks, or a
    task file the user supplied."""
    if args.tasks == "baxbench":
        return {"benchmark": "baxbench", "commit": baxbench.COMMIT, "sha256": None,
                "visibility": "public",
                "note": "a public benchmark at a pinned commit; may be in training data, so read "
                        "differences between arms rather than levels"}
    path = Path(args.tasks).resolve()
    return evalkit.corpus_record([path], bundled=path == (HERE / "fixtures" / "fake_tasks.json"))


# ----------------------------------------------------------------------------- generation

def generate_mock(cell: dict, arm_list: list[dict], selected: list[dict], args, out: Path) -> list[dict]:
    rows = []
    for arm in arm_list:
        for task in selected:
            for repeat in range(args.repeats):
                work = out / "work" / slug(f"{arm['name']}-{task['id']}-{repeat}")
                workspace, home = work / "ws", work / "home"
                workspace.mkdir(parents=True)
                home.mkdir(parents=True)
                plan = arms_lib.install(arm["dir"], workspace, home)
                result = mock_harness.run(task, workspace, args.seed, repeat, args.mock_code)
                dest = baxbench.code_dir(out / "baxbench", model_dir(cell["harness"], cell["model"],
                                         arm["name"]), task["scenario"], task["framework"], repeat)
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(workspace / "code", dest)
                rows.append(generation_row(cell, arm, task, repeat, result,
                                           transcript_lib.touched(result["transcript"], plan,
                                                                  str(workspace), str(home)), out))
                shutil.rmtree(work)
    shutil.rmtree(out / "work", ignore_errors=True)
    return rows


def generation_row(cell: dict, arm: dict, task: dict, repeat: int, result: dict,
                   touched: dict, out: Path) -> dict:
    path = out / "transcripts" / slug(cell["harness"] + "__" + cell["model"]) / arm["name"] \
        / f"{slug(task['id'])}__r{repeat}.jsonl"
    transcript_lib.write(path, result.get("transcript") or [])
    return {"harness": cell["harness"], "model": cell["model"], "arm": arm["name"],
            "target": task["id"], "sample": str(repeat), "repeat": repeat,
            "harness_version": result.get("harness_version") or cell["harness_version"],
            "tokens_in": result.get("tokens_in"), "tokens_out": result.get("tokens_out"),
            "tokens_total": result.get("tokens_total"), "wall_s": result.get("wall_s"),
            "error": result.get("error"), "limit": result.get("limit"), "touched": touched,
            "transcript": str(path.relative_to(out))}


def build_image(tag: str, context: Path) -> None:
    if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0:
        return
    print(f"building agent image {tag}", file=sys.stderr)
    subprocess.run(["docker", "build", "--quiet", "-t", tag, str(context)], check=True)


def prepare_sandboxes(selected: list[dict], header: dict, out: Path) -> dict[str, str]:
    """A compose file per task: the image the agent works in, with no network."""
    composes = {}
    for task in selected:
        if "dockerfile" in task:
            text = baxbench.agent_dockerfile(task["dockerfile"], list(task["manifest_files"]))
            digest = hashlib.sha256((text + json.dumps(task["manifest_files"], sort_keys=True))
                                    .encode()).hexdigest()[:12]
            tag = f"cgb-agent:{digest}"
            context = out / "sandbox" / digest
            if not context.exists():
                context.mkdir(parents=True)
                (context / "Dockerfile").write_text(text)
                for name, content in task["manifest_files"].items():
                    (context / name).write_text(content)
            build_image(tag, context)
            workdir = task.get("workdir", "/app")
        else:
            tag, digest = header["sandbox_image"], slug(header["sandbox_image"])
            context = out / "sandbox" / digest
            context.mkdir(parents=True, exist_ok=True)
            workdir = header.get("workdir", "/app")
        compose = context / "compose.yaml"
        compose.write_text(baxbench.compose_yaml(tag, workdir))
        composes[task["id"]] = str(compose)
        task["workdir"] = workdir
    return composes


def generate_sandbox(cell: dict, arm_list: list[dict], selected: list[dict], header: dict,
                     args, out: Path) -> list[dict]:
    try:
        import inspect_harness
        import inspect_ai  # noqa: F401
    except ImportError as exc:
        raise SystemExit(f"harness {cell['harness']} needs inspect_ai (and inspect-swe for a real "
                         f"harness) in this Python: {exc}. See PLAN step 1 in SKILL.md.") from None
    composes = prepare_sandboxes(selected, header, out)
    workdirs = {t["workdir"] for t in selected}
    if len(workdirs) != 1:
        raise SystemExit(f"tasks disagree on the working directory: {sorted(workdirs)}")
    workspace = workdirs.pop()
    samples = []
    for arm in arm_list:
        for task in selected:
            for repeat in range(args.repeats):
                dest = baxbench.code_dir(out / "baxbench", model_dir(cell["harness"], cell["model"],
                                         arm["name"]), task["scenario"], task["framework"], repeat)
                public_task = {k: task[k] for k in ("id", "scenario", "framework", "prompt")
                               if k in task}
                if "expect" in task:
                    public_task["expect"] = task["expect"]
                samples.append({"arm": arm["name"], "arm_dir": arm["dir"], "task": public_task,
                                "repeat": repeat, "compose": composes[task["id"]],
                                "code_dir": str(dest.resolve())})
    spec = {"harness": cell["harness"], "harness_version": cell["harness_version"],
            "workspace": workspace, "seed": args.seed, "samples": samples,
            "mock_code": str(Path(args.mock_code).resolve()) if args.mock_code else None,
            "time_limit": args.time_limit, "token_limit": args.token_limit}
    log_dir = out / "logs" / slug(cell["harness"] + "__" + cell["model"])
    model = cell["model"] if cell["harness"] in REAL_HARNESSES else "mockllm/model"
    records = inspect_harness.run_cell(spec, model, str(log_dir), args.max_samples)
    rows = []
    by_name = {a["name"]: a for a in arm_list}
    by_id = {t["id"]: t for t in selected}
    for s in samples:
        sid = inspect_harness.sample_id(s["arm"], s["task"]["id"], s["repeat"])
        record = records.get(sid) or {"error": "no Inspect sample was returned for this run",
                                      "transcript": [], "touched": None}
        rows.append(generation_row(cell, by_name[s["arm"]], by_id[s["task"]["id"]], s["repeat"],
                                   record, record.get("touched"), out))
    return rows


# ----------------------------------------------------------------------------- stages

def load_tasks(args, depth) -> tuple[dict, list[dict]]:
    frameworks = [f.strip() for f in (args.frameworks or "").split(",") if f.strip()] or None
    scenarios = [s.strip() for s in (args.scenarios or "").split(",") if s.strip()] or None
    if args.tasks == "baxbench":
        header = {"source": "baxbench"}
        pool = tasks_lib.baxbench_tasks(frameworks)
    else:
        header, pool = tasks_lib.load_task_file(args.tasks, frameworks)
    if scenarios:
        unknown = sorted(set(scenarios) - {t["scenario"] for t in pool})
        if unknown:
            raise ValueError(f"unknown scenario(s) {unknown}")
        pool = [t for t in pool if t["scenario"] in scenarios]
    if not pool:
        raise ValueError("no tasks match --frameworks / --scenarios")
    return header, tasks_lib.select(pool, depth, args.seed)


def attach_baxbench(selected: list[dict], args, out: Path) -> Path:
    """Clone BaxBench at the pinned commit and read prompt and Dockerfile for each task."""
    clone = baxbench.ensure_clone(args.baxbench_dir or Path.home() / ".cache"
                                  / "coding-guidance-benchmark" / f"baxbench-{baxbench.COMMIT[:12]}")
    info = baxbench.export_tasks(clone, baxbench.python_cmd(args.baxbench_python),
                                 [t["id"] for t in selected], out / "bridge.json")
    if set(info["scenarios"]) != set(tasks_lib.BAXBENCH_SCENARIOS) or \
            set(info["frameworks"]) != set(tasks_lib.BAXBENCH_FRAMEWORKS):
        raise SystemExit("the BaxBench clone lists different scenarios or frameworks than this "
                         "skill was verified against; refusing to run")
    for task in selected:
        task.update(info["tasks"][task["id"]])
    return clone


def score(header: dict, selected: list[dict], arm_list: list[dict], cells: list[dict], args,
          out: Path, clone: Path | None) -> None:
    results = out / "baxbench"
    if header["source"] == "baxbench":
        code = baxbench.run_test_mode(
            clone, baxbench.python_cmd(args.baxbench_python), results,
            [model_dir(c["harness"], c["model"], a["name"]) for c in cells for a in arm_list],
            [t["scenario"] for t in selected], [t["framework"] for t in selected],
            args.repeats, args.scoring_workers, args.test_timeout, args.rescore)
        if code != 0:
            print(f"warning: BaxBench test mode exited with status {code}; runs it did not finish "
                  "are reported as not scored", file=sys.stderr)
    else:
        for cell in cells:
            for arm in arm_list:
                for task in selected:
                    for repeat in range(args.repeats):
                        sdir = baxbench.sample_dir(results, model_dir(cell["harness"], cell["model"],
                                                   arm["name"]), task["scenario"], task["framework"],
                                                   repeat)
                        if (sdir / "code").is_dir():
                            fake_scorer.score(sdir, task["expect"], repeat)


def collect(gen_rows: list[dict], out: Path, source: str) -> list[dict]:
    rows = []
    for g in gen_rows:
        scenario, framework = tasks_lib.split_id(g["target"])
        sdir = baxbench.sample_dir(out / "baxbench", model_dir(g["harness"], g["model"], g["arm"]),
                                   scenario, framework, int(g["sample"]))
        rows.append({**g, "scenario": scenario, "framework": framework, "task_source": source,
                     **baxbench.parse_result(sdir)})
    return rows


def update_manifest(path: Path, run: dict, rows: list[dict]) -> None:
    """When --out sits inside an experiment folder opened by new_experiment.sh, record what
    ran in its manifest.json: the command, the task draw, the harness and the cost."""
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text())
    except ValueError:
        return
    cells = run["cells"]
    versions = sorted({str(r["harness_version"]) for r in rows if r.get("harness_version")})
    manifest["command"] = run.get("command")
    manifest["corpus"] = (f"{run['task_source']}: {run['n_tasks']} task(s) x {run['repeats']} "
                          f"repeat(s), seed {run['seed']}, depth {run['depth']}"
                          + (f", commit {run['baxbench_commit']}, no safety prompt"
                             if run.get("baxbench_commit") else ""))
    context = manifest.setdefault("context", {})
    context["harness"] = ", ".join(sorted({c["harness"] for c in cells}))
    context["harness_version"] = ", ".join(versions) or None
    if not context.get("surface"):
        context["surface"] = "coding agent writing a backend app in a workspace"
    if not context.get("safeguards"):
        context["safeguards"] = ("the arm under test; baseline has none. Arms: "
                                 + ", ".join(f"{a['name']} ({a['control_type'] or 'not labelled'})"
                                             for a in run["arms"]))
    manifest["arms"] = [{"name": a["name"], "control_type": a["control_type"],
                         "files": a["files"], "fingerprint": a["fingerprint"]} for a in run["arms"]]
    manifest["k"] = run["repeats"]
    manifest["scorers"] = (["baxbench functional tests", "baxbench exploits"]
                           if run["task_source"] == "baxbench" else ["fake scorer (smoke test)"])
    manifest["cost"] = {"usd": None,
                        "tokens_in": sum(r.get("tokens_in") or 0 for r in rows),
                        "tokens_out": sum(r.get("tokens_out") or 0 for r in rows),
                        "wall_s": round(sum(r.get("wall_s") or 0 for r in rows), 1)}
    manifest["_todo"] = [t for t in manifest.get("_todo", [])
                         if t not in ("scorers", "cost.usd", "arms", "k", "tool.name")]
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--arms", help="directory whose subfolders are the arms (baseline is implicit)")
    p.add_argument("--harness", default="mock",
                   help="name@version, comma-separated for several: "
                        + ", ".join(REAL_HARNESSES) + ", mock-sandbox, mock")
    p.add_argument("--model", default="none",
                   help="Inspect model string(s) for the agent, comma-separated for several")
    p.add_argument("--depth", default="smoke",
                   help="smoke (25 tasks) | standard (100) | full (all 392) | N")
    p.add_argument("--frameworks", help="comma-separated BaxBench framework ids to draw from")
    p.add_argument("--scenarios", help="comma-separated scenario ids to draw from")
    p.add_argument("--repeats", type=int, default=1, help="runs per arm and task")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="task-draw seed")
    p.add_argument("--tasks", default="baxbench",
                   help="'baxbench' or a task file (fixtures/fake_tasks.json for the smoke test)")
    p.add_argument("--out", default="results", help="output directory")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    p.add_argument("--baxbench-dir", help="where the pinned BaxBench clone lives (cloned if absent)")
    p.add_argument("--baxbench-python", help="interpreter with BaxBench's dependencies "
                                             "(default: `pipenv run python` in the clone)")
    p.add_argument("--scoring-workers", type=int, help="BaxBench --max_concurrent_runs")
    p.add_argument("--test-timeout", type=int, help="BaxBench --timeout per test, seconds")
    p.add_argument("--mock-code", help="mock harnesses: directory copied as the app for every task")
    p.add_argument("--time-limit", type=int, default=1800, help="seconds per agent run")
    p.add_argument("--token-limit", type=int, help="tokens per agent run")
    p.add_argument("--max-samples", type=int, help="agent runs in parallel (Inspect max_samples)")
    p.add_argument("--score-only", action="store_true",
                   help="reuse the code already generated in --out; run scoring and the report")
    p.add_argument("--rescore", action="store_true", help="with --score-only: discard old results")
    p.add_argument("--ceiling", type=float, default=report.CEILING,
                   help="validity flag: every arm at or above this rate on a metric "
                        "(default %(default)s)")
    p.add_argument("--plan-reason",
                   help="why this run's analysis plan differs from the one already registered "
                        "in --out (kept with the amendment in plan.json)")
    args = p.parse_args(argv)

    out = Path(args.out)
    run_path, gen_path, samples_path = out / "run.json", out / "generation.jsonl", out / "samples.jsonl"
    if args.score_only:
        if not gen_path.is_file() or not run_path.is_file():
            p.error(f"--score-only: {out} holds no generated run")
        saved = json.loads(run_path.read_text())
        arm_list, selected, cells, header = saved["arms"], saved["tasks"], saved["cells"], saved["header"]
        source = header["source"]
        args.repeats, args.seed = saved["repeats"], saved["seed"]
        gen_rows = [json.loads(line) for line in gen_path.read_text().splitlines() if line.strip()]
        samples_path.unlink(missing_ok=True)
    else:
        depth = evalkit.resolve_depth(args.depth)
        if args.repeats < 1:
            p.error("--repeats must be at least 1")
        try:
            arm_list = arms_lib.discover(args.arms)
            harnesses = parse_harnesses(args.harness)
            header, selected = load_tasks(args, depth)
        except ValueError as exc:
            p.error(str(exc))
        models = [m.strip() for m in args.model.split(",") if m.strip()] or ["none"]
        cells = [{"harness": h["name"], "harness_version": h["version"], "model": m}
                 for h in harnesses for m in models]
        source = header["source"]
        plan = print_plan(arm_list, selected, args.repeats, cells, source)
        if args.plan:
            return 0
        if any(c["harness"] in REAL_HARNESSES and c["model"] == "none" for c in cells):
            p.error("--model is required for a real harness")
        if gen_path.exists() or samples_path.exists():
            p.error(f"{out} already holds a run; use a new --out, or --score-only to rescore it")
        out.mkdir(parents=True, exist_ok=True)
        # The analysis plan, on record before the first agent run; the report lists departures.
        evalkit.register_plan(out, {
            "arms": [a["name"] for a in arm_list], "baseline": arms_lib.BASELINE,
            "measures": list(stats.METRICS), "depth": args.depth, "seed": args.seed,
            "repeats": args.repeats,
            "cells": [f"{c['harness']}@{c['harness_version']} / {c['model']}" for c in cells],
            "slices": {"frameworks": sorted({t["framework"] for t in selected})},
            "arm_fingerprints": {a["name"]: a.get("fingerprint") for a in arm_list},
            "judge": None, "scorer": "baxbench functional tests and exploits (deterministic)"
            if source == "baxbench" else "fake scorer (smoke test)",
            "corpus": corpus(args), "criteria": evalkit.criteria_record()},
            reason=args.plan_reason)

    clone = attach_baxbench(selected, args, out) if source == "baxbench" else None

    if not args.score_only:
        started = time.time()
        run = {"skill": "coding-guidance-benchmark", "task_source": source, "header": header,
               "depth": args.depth, "seed": args.seed, "repeats": args.repeats,
               "n_tasks": len(selected),
               "frameworks": sorted({t["framework"] for t in selected}) if args.frameworks else None,
               "tasks": selected, "arms": arm_list, "cells": cells, "plan": plan,
               "baseline": arms_lib.BASELINE,
               "harness_version_requested": ",".join(sorted({c["harness_version"] for c in cells})),
               "baxbench_commit": baxbench.COMMIT if source == "baxbench" else None,
               "safety_prompt": baxbench.SAFETY_PROMPT if source == "baxbench" else None,
               "time_limit": args.time_limit, "token_limit": args.token_limit,
               "command": " ".join(sys.argv)}
        run_path.write_text(json.dumps(run, indent=2))
        gen_rows = []
        for cell in cells:
            if cell["harness"] == "mock":
                gen_rows += generate_mock(cell, arm_list, selected, args, out)
            else:
                gen_rows += generate_sandbox(cell, arm_list, selected, header, args, out)
        with open(gen_path, "w") as fh:
            for row in gen_rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        run["generation_wall_s"] = round(time.time() - started, 1)
        run_path.write_text(json.dumps(run, indent=2))

    score(header, selected, arm_list, cells, args, out, clone)
    rows = collect(gen_rows, out, source)
    evalkit.append_samples(samples_path, rows)

    run = json.loads(run_path.read_text())
    plan = evalkit.load_plan(out)
    summary = report.build(rows, run, arms_lib.BASELINE, args.ceiling)
    (out / "summary.json").write_text(json.dumps(report.summary_json(summary, run, plan, rows),
                                                 indent=2))
    (out / "summary.md").write_text(report.render(summary, run, plan, rows))
    update_manifest(out.parent / "manifest.json", run, rows)
    print(out / "summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
