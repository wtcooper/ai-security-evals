#!/usr/bin/env python3
"""Run the voice-model benchmark: the same seeded cases, typed and spoken, against one
realtime model, and write samples.jsonl, summary.md and summary.json.

    python run_benchmark.py --model gpt-realtime-2.1 --depth standard --plan
    VOICE_TARGET_API_KEY=... VOICE_JUDGE_BASE_URL=https://gateway/v1 VOICE_JUDGE_API_KEY=... \
    <venv>/bin/python run_benchmark.py --model gpt-realtime-2.1 --judge <judge-model> \
        --depth standard --out <EXP>

The one axis is the INPUT CONDITION. Arms:
    text      the prompt typed into the realtime session            (baseline for the modality gap)
    speech    the prompt synthesised locally, unmodified            (baseline for perturbations)
    <name>    the speech clip with one perturbation from perturbations.json
Everything else is held fixed: model, session configuration, output modality, judge, cases.

Steps: select cases -> synthesise speech locally -> perturb -> one fresh realtime session
per (arm, case) -> judge the reply transcript -> metrics. Nothing is sent before the plan
is printed; `--plan` stops there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import adapters  # noqa: E402
import audio  # noqa: E402
import cases as caselib  # noqa: E402
import evalkit  # noqa: E402
import judge as judgelib  # noqa: E402
import perturb  # noqa: E402
import report  # noqa: E402
import synth  # noqa: E402
from adapters.base import TargetInput  # noqa: E402

BUILTIN_ARMS = ("text", "speech")
# OpenAI's Realtime cost guide: user audio is 1 token per 100 ms. Used for an ESTIMATE only.
INPUT_AUDIO_TOKENS_PER_SECOND = 10


def resolve_arms(spec: str, perturbation_arms: dict, default: list[str]) -> list[str]:
    if spec == "default":
        arms = [*BUILTIN_ARMS, *default]
    elif spec == "all":
        arms = [*BUILTIN_ARMS, *perturbation_arms]
    else:
        arms = [a.strip() for a in spec.split(",") if a.strip()]
    unknown = [a for a in arms if a not in BUILTIN_ARMS and a not in perturbation_arms]
    if unknown:
        raise ValueError(f"unknown arm(s) {unknown}; known: "
                         f"{[*BUILTIN_ARMS, *perturbation_arms]}")
    if len(set(arms)) != len(arms):
        raise ValueError("an arm is listed twice")
    return arms


def print_plan(cases: list[dict], arms: list[str], tts: str, clips: dict | None,
               max_output_tokens: int | None, file=None, title: str = "") -> dict:
    """Print what the run will send. Returns the plan as counts (no prices: they change, and
    the provider's model page is the place to read them)."""
    file = file or sys.stderr
    if title:
        print(title, file=file)
    n_by_type = {t: sum(1 for c in cases if c["type"] == t) for t in caselib.TYPES}
    rows = [{"name": f"{t} requests", "samples": n, "calls": 2 * n,
             "note": " 1 realtime response + 1 judge call each"} for t, n in n_by_type.items()]
    evalkit.print_plan(rows, arms=len(arms), file=file)
    audio_arms = [a for a in arms if a != "text"]
    n = len(cases)
    if clips:
        secs = {a: sum(c["seconds"] for c in clips["clips"] if c["arm"] == a) for a in audio_arms}
        basis = "measured from the clips"
    else:
        base = sum(synth.estimate_seconds(c["prompt"], tts) for c in cases)
        secs = {a: base for a in audio_arms}
        basis = (f"ESTIMATED from prompt length for engine '{tts}', before perturbation; "
                 "exact figures are printed once clips exist")
    total_secs = sum(secs.values())
    plan = {
        "cases": n, "cases_by_type": n_by_type, "arms": arms,
        "realtime_responses": n * len(arms), "judge_calls": n * len(arms),
        "clips_to_synthesise": n if audio_arms else 0,
        "clips_to_perturb": n * len([a for a in audio_arms if a != "speech"]),
        "input_audio_seconds": round(total_secs, 1),
        "input_audio_seconds_basis": basis,
        "estimated_input_audio_tokens": int(round(total_secs * INPUT_AUDIO_TOKENS_PER_SECOND)),
        "max_output_tokens_per_response": max_output_tokens,
    }
    print(f"  total: {plan['realtime_responses']} realtime responses, {plan['judge_calls']} "
          f"judge calls", file=file)
    print(f"  local, free: synthesise {plan['clips_to_synthesise']} clip(s), perturb "
          f"{plan['clips_to_perturb']}", file=file)
    print(f"  input audio: {plan['input_audio_seconds']} s across {len(audio_arms)} audio arm(s) "
          f"({basis})", file=file)
    print(f"  input audio tokens: ~{plan['estimated_input_audio_tokens']} (estimate: "
          f"{INPUT_AUDIO_TOKENS_PER_SECOND} per second of user audio, per the provider's cost "
          "guide; session instructions and tools add text tokens to every response)", file=file)
    if max_output_tokens:
        print(f"  output: at most {max_output_tokens} tokens per response, so at most "
              f"{max_output_tokens * plan['realtime_responses']} in total", file=file)
    else:
        print("  output: NOT bounded. Reply length decides output tokens; pass "
              "--max-output-tokens to bound it", file=file)
    print("  prices are not printed here: read the model's page and multiply these counts",
          file=file)
    return plan


def prepare_clips(cases: list[dict], arms: list[str], perturbation_arms: dict, clips_dir: Path,
                  tts: str, voice: str | None, seed: int) -> dict | None:
    """Synthesise the speech clip for every case and apply each perturbation arm."""
    audio_arms = [a for a in arms if a != "text"]
    if not audio_arms:
        return None
    manifest_path = clips_dir / "manifest.json"
    engine = synth.make_engine(tts, voice)
    synth.synthesize_all(cases, clips_dir, engine)
    wanted = {a: perturbation_arms[a] for a in audio_arms if a != "speech"}
    doc = json.loads(manifest_path.read_text())
    if wanted:
        doc["clips"] += perturb.perturb_manifest(manifest_path, wanted, clips_dir, seed)
    doc["perturbation_seed"] = seed
    doc["perturbation_arms"] = wanted
    manifest_path.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def load_clips(clips_dir: Path, cases: list[dict], arms: list[str]) -> dict:
    """Use clips prepared earlier (or imported from a public set) instead of synthesising."""
    doc = json.loads((clips_dir / "manifest.json").read_text())
    have = {(c["arm"], c["case_id"]) for c in doc["clips"]}
    missing = [(a, c["id"]) for a in arms if a != "text" for c in cases
               if (a, c["id"]) not in have]
    if missing:
        raise ValueError(f"{len(missing)} clip(s) missing from {clips_dir}, e.g. {missing[:3]}")
    return doc


def run_one(adapter, judge, case: dict, arm: str, clip: dict | None, clips_dir: Path,
            target_name: str, save_audio_to: Path | None) -> dict:
    """One (arm, case): send, grade, and return the samples.jsonl row."""
    if arm == "text":
        item = TargetInput(case_id=case["id"], modality="text", text=case["prompt"])
    else:
        samples, rate = audio.read_wav(clips_dir / clip["path"])
        if audio.sha256_pcm(samples) != clip["sha256"]:
            raise ValueError(f"clip {clip['path']} does not match its manifest hash")
        item = TargetInput(case_id=case["id"], modality="audio", pcm=audio.to_bytes(samples),
                           rate=rate)
    result = adapter.respond(item)
    row = {"arm": arm, "target": target_name, "sample": case["id"], "case_type": case["type"],
           "source": case.get("source"), "modality": item.modality, "prompt": case["prompt"],
           "perturbation": (clip or {}).get("perturbation"),
           "clip_sha256": (clip or {}).get("sha256"), "clip_seconds": (clip or {}).get("seconds"),
           "response_status": result.status, "status_reason": result.status_reason,
           "transcript": result.transcript, "target_error": result.error,
           "input_transcript": result.input_transcript, "tool_calls": result.tool_calls,
           "usage": result.usage, "latency_s": result.latency_s,
           "output_audio_seconds": round(len(result.output_audio) / 2 / result.output_rate, 3),
           "output_audio_path": None, "session_model": result.session_model,
           "verdict": None, "graded_by": None, "judge_reason": None, "judge_raw": None,
           "judge_error": None}
    if save_audio_to is not None and result.output_audio:
        audio.write_wav(save_audio_to, audio.from_bytes(result.output_audio), result.output_rate)
        row["output_audio_path"] = str(save_audio_to)
    if result.error:
        return row
    if not result.transcript:
        if result.status_reason == "content_filter":
            # The provider cut the reply off before anything was said. Nothing was complied with.
            row.update({"verdict": "refused", "graded_by": "status:content_filter"})
        else:
            row["target_error"] = f"empty reply (status {result.status}, reason {result.status_reason})"
        return row
    graded = judge.grade(case, result.transcript)
    row.update({"verdict": graded["verdict"], "graded_by": "judge",
                "judge_reason": graded["reason"], "judge_raw": graded["raw"],
                "judge_error": graded["error"]})
    return row


def build_context(review: str | None, adapter_info: dict) -> dict:
    """The deployment context this result applies to: a review profile when there is one,
    filled in with what the run itself knows."""
    context = evalkit.load_context(review)
    session = adapter_info.get("session") or {}
    known = {
        "surface": f"{adapter_info.get('adapter')} over WebSocket, one session per case",
        "harness": "voice-model-benchmark",
        "system_prompt": session.get("instructions") or "none set (provider default)",
        "tools": [t.get("name") for t in session.get("tools") or []] or "none",
        "safeguards": "provider defaults; nothing added by this skill",
    }
    return {**known, **context}


def update_manifest(out: Path, run: dict, summary: dict, command: str) -> None:
    """Fill the experiment manifest that new_experiment.sh opened, if `out` is one."""
    path = out / "manifest.json"
    if not path.is_file():
        return
    doc = json.loads(path.read_text())
    doc["command"] = command
    doc["corpus"] = (f"{run['corpus']['path']} sha256 {run['corpus']['sha256'][:12]}; seeded "
                     f"selection seed={run['seed']} depth={run['depth']}: "
                     f"{run['plan']['cases_by_type']}")
    doc["context"] = {**(doc.get("context") or {}), **run["context"]}
    doc.setdefault("tool", {}).update({"name": "voice-model-benchmark", "version": "1"})
    doc.setdefault("model", {})["id"] = run["model"]
    doc["arms"] = [{"name": a, "condition": run["perturbations"].get(a, a)} for a in run["arms"]]
    doc["k"] = run["plan"]["cases"]
    doc["paired"], doc["pair_on"] = True, ["target", "sample"]
    doc["scorers"] = [{"name": "transcript-judge", **run["judge_info"]}]
    doc.setdefault("benchmark", {}).update({"name": "voice-model-benchmark corpus subset"})
    usage = [b["reported_usage"] for b in summary["arms"].values()]
    doc["cost"] = {"usd": None, "tokens_in": sum(u.get("input_tokens", 0) for u in usage),
                   "tokens_out": sum(u.get("output_tokens", 0) for u in usage),
                   "wall_s": run.get("wall_s")}
    done = {"tool.name", "model.id", "k", "arms", "scorers"}
    doc["_todo"] = [t for t in doc.get("_todo", []) if t not in done]
    path.write_text(json.dumps(doc, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--model", help="realtime model under test, e.g. gpt-realtime-2.1")
    p.add_argument("--judge", help="judge model on the judge endpoint, or 'mock' with --target mock")
    p.add_argument("--depth", default="standard",
                   help="smoke (25 per case type) | standard (100) | full | N")
    p.add_argument("--seed", type=int, default=caselib.DEFAULT_SEED,
                   help="case selection and noise seed")
    p.add_argument("--arms", default="default",
                   help="default | all | comma list of: text, speech, <perturbation arm>")
    p.add_argument("--perturbations", help="perturbation definitions (default perturbations.json)")
    p.add_argument("--corpus", help="cases.jsonl (default: the vendored corpus)")
    p.add_argument("--out", default="voice-model-benchmark-out",
                   help="experiment folder (EXP from new_experiment.sh) or any directory")
    p.add_argument("--plan", action="store_true", help="print the plan and exit")
    p.add_argument("--target", default="openai-realtime",
                   help=f"adapter ({', '.join(adapters.ADAPTERS)}) or 'mock' for the bundled mock server")
    p.add_argument("--target-url", help="realtime endpoint (default: $VOICE_TARGET_URL or the adapter's)")
    p.add_argument("--output", default="audio", choices=("audio", "text"),
                   help="what the model produces, held fixed across arms")
    p.add_argument("--session-config", help="JSON file merged into the session: instructions, "
                                            "tools, voice, reasoning ... of the deployment under review")
    p.add_argument("--max-output-tokens", type=int, help="bound each response (recorded; same for all arms)")
    p.add_argument("--input-transcription", metavar="MODEL",
                   help="also ask the provider to transcribe input audio with this model (billed separately)")
    p.add_argument("--audio-input", default="buffer", choices=("buffer", "item"),
                   help="send audio through the input buffer (default) or as one audio message")
    p.add_argument("--transport", default="stdlib", choices=("stdlib", "websockets"))
    p.add_argument("--timeout", type=float, default=90.0, help="seconds to wait on the target per event")
    p.add_argument("--tts", default="piper", choices=("piper", "tone"),
                   help="local speech engine; 'tone' is not speech and only allowed with --target mock")
    p.add_argument("--voice", help="Piper voice name or .onnx path")
    p.add_argument("--clips", help="use clips prepared earlier (a directory holding manifest.json)")
    p.add_argument("--save-audio", default="5",
                   help="keep the model's spoken output for the first N cases of each type in "
                        "every arm (same cases in each arm), or 'all' or 0")
    p.add_argument("--concurrency", type=int, default=4, help="parallel realtime sessions")
    p.add_argument("--review", help="review profile (review.json) for the context block")
    p.add_argument("--resume", action="store_true",
                   help="keep rows already in samples.jsonl and run only what is missing or errored")
    for name, default in report.DEFAULT_LIMITS.items():
        p.add_argument(f"--max-{name.replace('_', '-')}", type=float, default=default,
                       help=f"validity-flag limit (default {default}); not an acceptance bar")
    args = p.parse_args(argv)
    command = "run_benchmark.py " + " ".join(argv if argv is not None else sys.argv[1:])

    perturbation_doc = json.loads(Path(args.perturbations or perturb.DEFAULTS_FILE).read_text())
    perturbation_arms = perturb.load_arms(args.perturbations)
    try:
        arms = resolve_arms(args.arms, perturbation_arms, perturbation_doc.get("default", []))
        depth = evalkit.resolve_depth(args.depth)
    except ValueError as exc:
        p.error(str(exc))
    corpus_path = Path(args.corpus) if args.corpus else caselib.CORPUS
    selected = caselib.select(caselib.load_cases(corpus_path), depth, args.seed)
    out = Path(args.out)
    clips_dir = Path(args.clips) if args.clips else out / "results" / "clips"
    is_mock = args.target == "mock"

    existing = None
    if args.clips and (clips_dir / "manifest.json").is_file():
        existing = load_clips(clips_dir, selected, arms)
    plan = print_plan(selected, arms, args.tts, existing, args.max_output_tokens)
    if args.plan:
        return 0

    # --- checks that must hold before anything is sent ---------------------------------------
    if not args.model and not is_mock:
        p.error("--model is required")
    model = args.model or "mock-realtime"
    if not args.judge:
        p.error("--judge is required: a judge model on VOICE_JUDGE_BASE_URL, or 'mock' with --target mock")
    if args.judge == "mock" and not is_mock:
        p.error("--judge mock grades only the mock server's fixed phrases; use it with --target mock")
    if args.tts == "tone" and not is_mock and not args.clips:
        p.error("--tts tone is not speech; it is only allowed with --target mock")
    if args.judge != "mock" and judgelib.same_model(args.judge, model):
        p.error("the judge must not be the model under test")
    if "speech" not in arms and any(a not in BUILTIN_ARMS for a in arms):
        print("note: no 'speech' arm, so perturbation deltas against clean speech cannot be "
              "computed", file=sys.stderr)

    # Credentials are read from VOICE_* only, then every provider key is dropped from the
    # environment so nothing can fall back to one implicitly.
    target_key = os.environ.get("VOICE_TARGET_API_KEY")
    target_url = args.target_url or os.environ.get("VOICE_TARGET_URL")
    judge_base = os.environ.get("VOICE_JUDGE_BASE_URL")
    judge_key = os.environ.get("VOICE_JUDGE_API_KEY")
    clean = evalkit.scrub_provider_credentials(dict(os.environ))
    os.environ.clear()
    os.environ.update(clean)
    if args.judge != "mock" and not judge_base:
        p.error("VOICE_JUDGE_BASE_URL is not set (an OpenAI-compatible endpoint ending in /v1). "
                "The judge is always routed explicitly.")
    if not is_mock and not target_key:
        p.error("VOICE_TARGET_API_KEY is not set")

    # --- local preparation ---------------------------------------------------------------------
    (out / "results").mkdir(parents=True, exist_ok=True)
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    (out / "inputs" / "cases.jsonl").write_text(
        "".join(json.dumps(c, sort_keys=True) + "\n" for c in selected))
    started = time.time()
    clips = existing or prepare_clips(selected, arms, perturbation_arms, clips_dir, args.tts,
                                      args.voice, args.seed)
    if clips and not existing:
        plan = print_plan(selected, arms, args.tts, clips, args.max_output_tokens,
                          title="clips are ready; the plan with measured audio lengths:")
    if clips and not clips["engine"].get("is_speech", True) and not is_mock:
        p.error("these clips are not speech (engine 'tone'); they can only go to --target mock")
    clip_index = {(c["arm"], c["case_id"]): c for c in (clips or {}).get("clips", [])}

    # --- target and judge ----------------------------------------------------------------------
    session = json.loads(Path(args.session_config).read_text()) if args.session_config else None
    server = None
    if is_mock:
        import mock_realtime_server
        server = mock_realtime_server.MockRealtimeServer(
            selected, (clips or {}).get("clips", [])).start()
        target_url, target_key, adapter_name = server.url, "mock-key", "openai-realtime"
    else:
        adapter_name = args.target
    adapter = adapters.get(adapter_name)(
        model=model, api_key=target_key, url=target_url, output_modality=args.output,
        session=session, audio_input=args.audio_input,
        input_transcription_model=args.input_transcription,
        max_output_tokens=args.max_output_tokens, timeout=args.timeout, transport=args.transport)
    judge = judgelib.MockJudge() if args.judge == "mock" else judgelib.ChatJudge(
        args.judge, judge_base, judge_key)
    adapter_info = adapter.describe()
    if is_mock:
        adapter_info["mock"] = True

    # --- which (arm, case) pairs to run ----------------------------------------------------------
    samples_path = out / "samples.jsonl"
    done: set[tuple] = set()
    if samples_path.exists():
        if not args.resume:
            p.error(f"{samples_path} exists; pass --resume to continue it or choose a new --out")
        done = {(r["arm"], r["sample"]) for r in report.load_samples(samples_path)
                if not r.get("target_error")}
    keep = len(selected) if args.save_audio == "all" else int(args.save_audio)
    keep_ids = set()
    for case_type in caselib.TYPES:
        keep_ids |= {c["id"] for c in [c for c in selected if c["type"] == case_type][:keep]}
    todo = [(arm, case) for arm in arms for case in selected if (arm, case["id"]) not in done]
    print(f"running {len(todo)} of {len(arms) * len(selected)} (arm, case) pairs against "
          f"{model} ...", file=sys.stderr, flush=True)

    lock = threading.Lock()
    progress = {"n": 0}

    def work(pair):
        arm, case = pair
        save_to = None
        if args.output == "audio" and case["id"] in keep_ids:
            save_to = out / "results" / "output_audio" / arm / f"{case['id']}.wav"
        try:
            row = run_one(adapter, judge, case, arm, clip_index.get((arm, case["id"])),
                          clips_dir, model, save_to)
        except Exception as exc:  # noqa: BLE001 - record and continue
            row = {"arm": arm, "target": model, "sample": case["id"], "case_type": case["type"],
                   "prompt": case["prompt"], "verdict": None,
                   "target_error": f"{type(exc).__name__}: {exc}"}
        if row.get("output_audio_path"):
            row["output_audio_path"] = str(Path(row["output_audio_path"]).relative_to(out))
        with lock:
            evalkit.append_samples(samples_path, [row])
            progress["n"] += 1
            if progress["n"] % 50 == 0 or progress["n"] == len(todo):
                print(f"  {progress['n']}/{len(todo)}", file=sys.stderr, flush=True)

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            list(pool.map(work, todo))
    finally:
        if server is not None:
            server.stop()

    # --- record and summarise --------------------------------------------------------------------
    kept = sorted({r["sample"] for r in report.load_samples(samples_path)
                   if r.get("output_audio_path")})
    spot = {"directory": "results/output_audio", "cases": kept}
    run = {
        "model": model, "adapter": adapter_info["adapter"], "target": adapter_info,
        "judge": judge.model, "judge_info": judge.describe(),
        "depth": args.depth, "seed": args.seed, "arms": arms,
        "perturbations": {a: perturbation_arms[a] for a in arms if a in perturbation_arms},
        "corpus": {"path": corpus_path.name,
                   "sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest()},
        "tts": (clips or {}).get("engine"), "output_modality": args.output,
        "plan": plan, "context": build_context(args.review, adapter_info),
        "command": command, "wall_s": round(time.time() - started, 1), "spot_check": spot,
    }
    (out / "results" / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    limits = {name: getattr(args, f"max_{name}") for name in report.DEFAULT_LIMITS}
    summary = report.write_summary(samples_path, out, limits, run)
    update_manifest(out, run, summary, command)
    for flag in summary["validity_flags"]:
        print(f"validity flag: {flag['flag']} ({flag['scope']}) observed "
              f"{flag['observed']:.3f} > limit {flag['limit']}", file=sys.stderr)
    print(out / "summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
