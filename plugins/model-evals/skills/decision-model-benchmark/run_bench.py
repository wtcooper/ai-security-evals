#!/usr/bin/env python3
"""Run the decision-model benchmark: every arm gets the same seeded cases and variants.

    python run_bench.py --depth standard --plan                       # cost only, no requests
    DMB_API_KEY=... python run_bench.py \
        --arm name=jev,provider=typesafe,model=jev-1.14.0 \
        --arm name=luna,provider=openai,model=gpt-6-luna,key-env=OPENAI_KEY \
        --depth standard --out <EXP>

An arm is one model behind one endpoint:
    --arm name=<label>,provider=<preset>,model=<id>[,url=<endpoint>][,format=<wire format>]
          [,expect=<model id the server should report>]
          [,price-per-m=<US dollars per million input tokens>]
          [,auth=bearer|api-key|x-goog-api-key|header:<Name>|none][,key-env=<ENV VAR NAME>]
          [,placement=user|tool_output][,header.<Name>=<value>]
Keys are read from the environment variable named by key-env (default DMB_API_KEY), never
from the command line, and are not written to any output file.

Outputs in --out:
    samples.jsonl          one row per arm x case x variant x repeat
    results/run.json       seed, depth, arms (without keys), plan, corpus hash, context
    results/variants.jsonl the exact state and question of every request, for audit
Then: python report.py <out>   writes summary.md and summary.json.

Execution tier T0: HTTPS requests to the endpoints you name. Nothing is executed locally.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import adapter  # noqa: E402
import evalkit  # noqa: E402
import metrics  # noqa: E402
import variants  # noqa: E402

SKILL = "decision-model-benchmark"
QUESTION_NAME = "decision"
# Cases drawn and techniques per axis for each depth. `smoke` proves the wiring only.
DEPTH_PLAN = {
    "smoke": {"cases": 10, "mode": "one"},
    "standard": {"cases": None, "mode": "one"},
    "full": {"cases": None, "mode": "all"},
}


def resolve_depth(spec: str) -> dict:
    """smoke | standard | full, or a number of cases (one technique per axis)."""
    if spec in DEPTH_PLAN:
        return dict(DEPTH_PLAN[spec])
    return {"cases": evalkit.resolve_depth(spec), "mode": "one"}


def parse_arm(text: str) -> dict:
    spec = {}
    for part in text.split(","):
        if "=" not in part:
            raise adapter.CaseError(f"--arm expects key=value pairs, got {part!r}")
        key, value = part.split("=", 1)
        spec[key.strip()] = value.strip()
    return spec


def build_requests(cases: list[dict], policies: dict, seed: int, mode: str,
                   axes: tuple[str, ...], repeats: int, repeat_scope: str) -> list[dict]:
    """The request list every arm receives, in a fixed order."""
    out = []
    for case in cases:
        policy = policies[case["policy"]]
        for var in variants.generate(case, policy, seed, mode, axes):
            times = repeats if (var["id"] == "clean" or repeat_scope == "all") else 1
            wire_case = variants.to_case(var, policy, QUESTION_NAME)
            for rep in range(times):
                out.append({"case": case, "policy": policy, "variant": var, "repeat": rep,
                            "wire_case": wire_case,
                            "tokens_est": adapter.estimate_tokens(wire_case)})
    return out


def plan(requests: list[dict], n_arms: int, file=None) -> dict:
    """Print what the run will send, per arm, before anything is sent."""
    file = file or sys.stderr
    axes: dict[str, dict] = {}
    for req in requests:
        row = axes.setdefault(req["variant"]["axis"], {"variants": 0, "requests": 0, "tokens": 0})
        row["requests"] += 1
        row["tokens"] += req["tokens_est"]
        row["variants"] += req["repeat"] == 0
    total = {"cases": len({r["case"]["id"] for r in requests}), "requests": len(requests),
             "input_tokens_est": sum(r["tokens_est"] for r in requests), "arms": n_arms,
             "axes": axes}
    print(f"plan: {total['cases']} cases x {n_arms} arm(s); per arm {total['requests']} "
          f"requests / ~{total['input_tokens_est']} input tokens (estimate: characters / 4; "
          "the server's count is what gets recorded)", file=file)
    for axis, row in axes.items():
        print(f"  {axis:<14} variants={row['variants']:<5} requests={row['requests']:<5} "
              f"tokens~{row['tokens']}", file=file)
    print(f"  all arms: {total['requests'] * n_arms} requests / "
          f"~{total['input_tokens_est'] * n_arms} input tokens; these models bill input tokens "
          "only, so cost is that figure times the arm's price per token", file=file)
    return total


def score_row(arm: dict, req: dict, result: dict) -> dict:
    """One samples.jsonl row from one canonical result."""
    case, policy, var = req["case"], req["policy"], req["variant"]
    res = result["answers"][QUESTION_NAME]
    raw = res["label"]
    decision = var["label_map"].get(raw) if raw is not None else None
    probs = {var["label_map"][k]: v for k, v in res["probs"].items()} if res["probs"] else None
    inverse = {canon: sent for sent, canon in var["label_map"].items()}
    correct = (decision == case["truth"]) if res["outcome"] == "answered" else None
    return {
        "arm": arm["name"], "target": case["policy"],
        "sample": f"{case['id']}/{var['id']}#r{req['repeat']}",
        "case": case["id"], "variant": var["id"], "axis": var["axis"],
        "technique": var["technique"], "changed": var["changed"], "repeat": req["repeat"],
        "qtype": var["question"]["type"],
        "truth": case["truth"], "truth_raw": inverse[case["truth"]],
        "error_class": case["error_class"],
        "attacker_target": var["attacker_target"],
        "outcome": res["outcome"], "refusal": res["refusal"],
        "decision": decision, "decision_raw": raw, "probs": probs,
        "top_p": res["top_p"], "margin": res["margin"], "prob_sum": res["prob_sum"],
        "tie": res["tie"], "correct": correct,
        "error_kind": metrics.error_kind(case["truth"], decision, policy["restrictive_labels"])
        if res["outcome"] == "answered" else None,
        "options_sent": adapter.labels_of(var["question"]),
        "vendor_confidence": res["vendor_confidence"], "vendor_choice": res["vendor_choice"],
        "latency_ms": res["latency_ms"], "input_tokens": res["input_tokens"],
        "model_requested": arm["model"], "model_echo": res["model_echo"],
        "wire_format": arm["format"], "http_status": res["http_status"],
        "attempts": res["attempts"], "error": res["error"],
    }


def run_arm(arm: dict, requests: list[dict], samples_path: Path, args) -> list[dict]:
    def one(req: dict) -> dict:
        result = adapter.decide(arm, req["wire_case"], timeout=args.timeout,
                                retries=args.retries, backoff=args.backoff)
        return score_row(arm, req, result)

    rows: list[dict] = []
    if not requests:
        return rows
    first = one(requests[0])                      # preflight: the first request, sent alone
    evalkit.append_samples(samples_path, [first])
    rows.append(first)
    if first["outcome"] == "error" and not args.no_preflight:
        print(f"[{arm['name']}] first request failed ({first['error']}); arm skipped. Fix the "
              "endpoint, credential or model id, or pass --no-preflight to send the rest anyway.",
              file=sys.stderr)
        return rows
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        for i, row in enumerate(pool.map(one, requests[1:]), 2):
            # Written as each request finishes so an interrupted run keeps what it has.
            evalkit.append_samples(samples_path, [row])
            rows.append(row)
            if i % 100 == 0:
                print(f"[{arm['name']}] {i}/{len(requests)}", file=sys.stderr, flush=True)
    return rows


def recorded_command(argv: list[str], arms: list[dict]) -> str:
    """The command line as it is written to disk, with each arm URL cut back to its path so
    a key passed in a query string is not recorded."""
    text = "run_bench.py " + " ".join(argv)
    for arm in arms:
        text = text.replace(arm["url"], adapter.safe_url(arm["url"]))
    return text


def corpus_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def update_manifest(out: Path, run: dict, rows: list[dict]) -> bool:
    """Fill the experiment manifest that new_experiment.sh opened, when there is one."""
    path = out / "manifest.json"
    if not path.is_file():
        return False
    doc = json.loads(path.read_text())
    arms = run["arms"]
    doc.update({
        "command": run["command"],
        "corpus": f"{run['corpus']['cases_file']} ({run['corpus']['cases_run']} of "
                  f"{run['corpus']['cases_total']} cases, sha256 {run['corpus']['sha256'][:12]}), "
                  f"depth {run['depth']}, seed {run['seed']}",
        "arms": [{"name": a["name"], "condition": f"{a['format']} {a['model']} @ {a['url']}"}
                 for a in arms],
        "k": run["corpus"]["cases_run"],
        "scorers": [{"name": "argmax-vs-label", "judge": None}],
        "pair_on": ["case", "variant"],
    })
    doc["model"] = {**doc.get("model", {}), "id": ", ".join(a["model"] for a in arms)}
    doc["benchmark"] = {**doc.get("benchmark", {}), "name": SKILL + " seed corpus"
                        if run["corpus"]["bundled"] else run["corpus"]["cases_file"],
                        "version": run["corpus"]["sha256"][:12]}
    doc["tool"] = {**doc.get("tool", {}), "name": SKILL}
    if run.get("context"):
        doc["context"] = {**(doc.get("context") or {}), **run["context"]}
    tokens = sum(r["input_tokens"] or 0 for r in rows)
    doc["cost"] = {**doc.get("cost", {}), "tokens_in": tokens, "tokens_out": 0}
    done = {"tool.name", "model.id", "k", "arms", "scorers", "benchmark.name"}
    if all(a.get("price_per_m") is not None for a in arms):
        price = {a["name"]: a["price_per_m"] for a in arms}
        doc["cost"]["usd"] = round(sum((r["input_tokens"] or 0) * price[r["arm"]]
                                       for r in rows) / 1e6, 6)
        done.add("cost.usd")
    doc["_todo"] = [t for t in doc.get("_todo", []) if t not in done]
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--arm", action="append", default=[], metavar="K=V,...",
                   help="one model behind one endpoint; repeat for more arms (see module help)")
    p.add_argument("--arms-file", help="JSON list of arm objects, instead of or as well as --arm")
    p.add_argument("--depth", default="standard",
                   help="smoke (10 cases, wiring only) | standard (all cases, one technique "
                        "per axis) | full (all cases, every technique) | N cases")
    p.add_argument("--repeats", type=int, default=3,
                   help="times each clean request is sent; the re-runs give the noise floor")
    p.add_argument("--repeat-scope", choices=("clean", "all"), default="clean",
                   help="`all` also re-sends every variant --repeats times")
    p.add_argument("--seed", type=int, default=20261114, help="case draw and variant seed")
    p.add_argument("--axes", default=",".join(variants.AXES),
                   help="comma list of attack axes to generate")
    p.add_argument("--cases", help="your own cases JSONL (default: the bundled seed corpus)")
    p.add_argument("--policies", help="your own policies JSON (default: the bundled one)")
    p.add_argument("--out", default="dmb-out", help="output directory (the experiment folder)")
    p.add_argument("--review", help="review profile whose `context` is recorded with the run")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--retries", type=int, default=2, help="retries on 429, 5xx and network errors")
    p.add_argument("--backoff", type=float, default=1.0, help="seconds; doubles per retry")
    p.add_argument("--no-preflight", action="store_true",
                   help="keep sending an arm's requests even if its first one errors")
    p.add_argument("--force", action="store_true", help="overwrite an existing samples.jsonl")
    p.add_argument("--plan", action="store_true", help="print the cost plan and exit")
    p.add_argument("--mock", action="store_true",
                   help="keyless smoke test: start the bundled mock server in this process and "
                        "add three mock arms, one per wire format")
    args = p.parse_args(argv)
    try:
        return _run(p, args, argv)
    finally:
        if getattr(args, "_mock_server", None) is not None:
            args._mock_server.stop()


def mock_arms(args) -> list[dict]:
    """Start the mock server and return one arm per wire format. The toy model behind it is
    not a decision model; its numbers only show that the pipeline produces numbers."""
    import mock_server
    srv = mock_server.MockServer(port=0).start()
    args._mock_server = srv
    return [
        {"name": "mock-a", "format": "systemone", "url": srv.url("systemone"),
         "model": "mock-decision-a", "auth": "none", "provider": "mock"},
        {"name": "mock-b", "format": "openai", "url": srv.url("openai"),
         "model": "mock-decision-b", "auth": "none"},
        {"name": "mock-a-gemini", "format": "gemini", "url": srv.url("gemini"),
         "model": "mock-decision-a", "auth": "none"},
    ]


def _run(p, args, argv) -> int:

    depth = resolve_depth(args.depth)
    if args.repeats < 1:
        p.error("--repeats must be at least 1")
    axes = tuple(a.strip() for a in args.axes.split(",") if a.strip())
    policies, cases = variants.load_corpus(args.cases, args.policies)
    chosen = variants.select_cases(cases, depth["cases"], args.seed)
    requests = build_requests(chosen, policies, args.seed, depth["mode"], axes, args.repeats,
                              args.repeat_scope)

    specs = [parse_arm(a) for a in args.arm]
    if args.arms_file:
        specs += json.loads(Path(args.arms_file).read_text())
    totals = plan(requests, max(len(specs) + (3 if args.mock else 0), 1))
    if args.repeats < 2:
        print("  note: --repeats 1 sends nothing twice, so there will be no noise floor to "
              "read the flip rates against", file=sys.stderr)
    if args.plan:
        return 0
    if args.mock:
        specs += mock_arms(args)
    if not specs:
        p.error("at least one --arm is required (--mock for the keyless smoke test, or --plan "
                "to see the cost only)")
    try:
        arms = [adapter.resolve_arm(s) for s in specs]
    except adapter.CaseError as exc:
        p.error(str(exc))
    if len({a["name"] for a in arms}) != len(arms):
        p.error("arm names must be unique")

    out = Path(args.out)
    (out / "results").mkdir(parents=True, exist_ok=True)
    samples_path = out / "samples.jsonl"
    if samples_path.exists():
        if not args.force:
            p.error(f"{samples_path} exists; use a new --out or pass --force")
        samples_path.unlink()
    with open(out / "results" / "variants.jsonl", "w") as fh:
        for req in requests:
            if req["repeat"] == 0:
                var = req["variant"]
                fh.write(json.dumps({
                    "case": req["case"]["id"], "policy": req["case"]["policy"],
                    "variant": var["id"], "axis": var["axis"], "technique": var["technique"],
                    "changed": var["changed"], "parent": var["parent"], "truth": var["truth"],
                    "attacker_target": var["attacker_target"], "label_map": var["label_map"],
                    "state": var["state"], "question": var["question"]},
                    ensure_ascii=False) + "\n")

    cases_path = Path(args.cases) if args.cases else variants.CORPUS_DIR / "seed_cases.jsonl"
    policies_path = Path(args.policies) if args.policies else variants.CORPUS_DIR / "policies.json"
    run = {
        "skill": SKILL, "execution_tier": "T0",
        "command": recorded_command(argv if argv is not None else sys.argv[1:], arms),
        "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "seed": args.seed, "depth": args.depth, "techniques_per_axis": depth["mode"],
        "repeats": args.repeats, "repeat_scope": args.repeat_scope, "axes": list(axes),
        "corpus": {"cases_file": cases_path.name, "policies_file": policies_path.name,
                   "bundled": not args.cases, "sha256": corpus_hash([cases_path, policies_path]),
                   "cases_total": len(cases), "cases_run": len(chosen),
                   "case_ids": [c["id"] for c in chosen]},
        "arms": [adapter.public_arm(a) for a in arms],
        "plan": totals,
        "context": evalkit.load_context(args.review),
    }
    (out / "results" / "run.json").write_text(json.dumps(run, indent=2) + "\n")

    all_rows: list[dict] = []
    wired = True
    for arm, public in zip(arms, run["arms"]):
        if arm["model_is_alias"]:
            print(f"[{arm['name']}] model id {arm['model']!r} looks like a moving alias; a "
                  "versioned id makes the run repeatable", file=sys.stderr)
        rows = run_arm(arm, requests, samples_path, args)
        all_rows += rows
        echoed = sorted({r["model_echo"] for r in rows if r["model_echo"]})
        n_ans = sum(r["outcome"] == "answered" for r in rows)
        public["resolved_models"] = echoed
        public["requests_sent"] = len(rows)
        print(f"[{arm['name']}] {len(rows)} requests: {n_ans} answered, "
              f"{sum(r['outcome'] == 'refusal' for r in rows)} refused, "
              f"{sum(r['outcome'] == 'error' for r in rows)} errors; server model id: "
              f"{', '.join(echoed) or 'not reported'}", file=sys.stderr)
        if len(echoed) > 1:
            print(f"[{arm['name']}] the server reported more than one model id during the run",
                  file=sys.stderr)
        wired = wired and n_ans > 0
    run["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    (out / "results" / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    update_manifest(out, run, all_rows)
    print(samples_path)
    # Exit 1 only when an arm produced no answer at all (a wiring failure, not a result).
    return 0 if wired else 1


if __name__ == "__main__":
    raise SystemExit(main())
