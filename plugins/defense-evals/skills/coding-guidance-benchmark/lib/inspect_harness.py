"""Run the agent under test inside an Inspect AI Docker sandbox.

Imported only when a sandboxed harness is chosen, by a Python that has inspect_ai (and, for a
real harness, inspect_swe) installed. Verified against inspect_ai 0.3.289 and inspect-swe 0.3.0.

Per sample:  install_arm  ->  the agent  ->  export_code (as the scorer, so it still runs when
the agent hits a time or token limit).

Harnesses:
  claude_code, codex_cli, gemini_cli, opencode   real coding agents, from inspect_swe. The
      agent binary is downloaded on the host and copied into the sandbox; model traffic goes
      back to Inspect through its bridge, so the sandbox needs no network and no API key.
  mock-sandbox   the mock agent of mock_harness.py, acting through the sandbox. No model and
      no key. It exercises the image, the arm installation and the code export.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arms as arms_lib  # noqa: E402
import mock_harness  # noqa: E402
import transcript as transcript_lib  # noqa: E402

REAL_HARNESSES = ("claude_code", "codex_cli", "gemini_cli", "opencode")
INFO_SOURCE = "coding_guidance_benchmark"
MAX_EXPORT_BYTES = 1_000_000      # per file; larger files are not app source
SKIP_DIRS = ("node_modules", ".git", "__pycache__", "target")


def sample_id(arm: str, task_id: str, repeat: int) -> str:
    return f"{arm}|{task_id}|{repeat}"


def build_task(spec: dict):
    """One Inspect task holding every arm x task x repeat of one (harness, model) cell."""
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import Score, Target, accuracy, scorer
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util import sandbox, store

    @solver
    def install_arm():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            from inspect_ai.log import transcript
            meta = state.metadata
            home = (await sandbox().exec(["sh", "-c", "echo $HOME"])).stdout.strip() or "/root"
            plan = arms_lib.install_plan(meta.get("arm_dir"), meta["workspace"], home)
            for item in plan:
                await sandbox().write_file(item["dest"], Path(item["src"]).read_bytes())
                await sandbox().exec(["chmod", format(item["mode"], "o"), item["dest"]])
            public = [{k: v for k, v in item.items() if k != "src"} for item in plan]
            store().set("cgb_home", home)
            store().set("cgb_plan", public)
            transcript().info({"arm": meta["arm"], "installed": [p["dest"] for p in public]},
                              source=INFO_SOURCE)
            return state
        return solve

    @solver
    def mock_agent():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            meta = state.metadata
            ws = meta["workspace"]
            listing = await sandbox().exec(
                ["sh", "-c", f"cd {ws} 2>/dev/null && find . -type f | sed 's|^\\./||' | sort"])
            names = [n for n in listing.stdout.split("\n") if n]
            task = meta["task"]
            u_variant, u_read = mock_harness._draw(spec["seed"], task["id"], meta["repeat"], names)
            rows, read_chars, written = [], 0, 0
            if names and u_read < 0.75:
                target = f"{ws}/{names[0]}"
                read_chars = len(await sandbox().read_file(target, text=False))
                rows.append({"type": "tool_call", "tool": "Read", "input": {"file_path": target}})
            files: dict[str, bytes] = {}
            if "expect" in task:
                variant = next(n for n, upto in mock_harness.VARIANTS if u_variant < upto)
                files["app.json"] = mock_harness.fake_app(task["expect"], variant).encode()
            elif spec.get("mock_code"):
                root = Path(spec["mock_code"])
                for src in sorted(p for p in root.rglob("*") if p.is_file()):
                    files[src.relative_to(root).as_posix()] = src.read_bytes()
            else:
                raise ValueError("mock-sandbox needs --mock-code for tasks that are not fake tasks")
            for rel, data in files.items():
                await sandbox().write_file(f"{ws}/code/{rel}", data)
                written += len(data)
                rows.append({"type": "tool_call", "tool": "Write",
                             "input": {"file_path": f"{ws}/code/{rel}"}})
            tokens_in = (len(task.get("prompt", "")) + read_chars) // 4
            store().set("cgb_mock", {"transcript": rows, "tokens_in": tokens_in,
                                     "tokens_out": written // 4})
            return state
        return solve

    @scorer(metrics=[accuracy()])
    def export_code():
        async def score(state: TaskState, target: Target) -> Score:
            meta = state.metadata
            ws = meta["workspace"]
            prune = " -o ".join(f"-name {d}" for d in SKIP_DIRS)
            found = await sandbox().exec(
                ["sh", "-c", f"cd {ws}/code 2>/dev/null && find . \\( {prune} \\) -prune -o "
                             f"-type f -size -{MAX_EXPORT_BYTES}c -print | sed 's|^\\./||'"])
            dest = Path(meta["code_dir"])
            count = 0
            for rel in [n for n in found.stdout.split("\n") if n]:
                parts = Path(rel).parts
                if rel.startswith("/") or ".." in parts:
                    continue
                data = await sandbox().read_file(f"{ws}/code/{rel}", text=False)
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
                count += 1
            return Score(value=1 if count else 0, answer=str(count),
                         explanation=f"{count} file(s) copied out of {ws}/code")
        return score

    harness = spec["harness"]
    if harness == "mock-sandbox":
        agent_solver = mock_agent()
    elif harness in REAL_HARNESSES:
        import inspect_swe
        from inspect_ai.agent import as_solver
        # cwd is the workspace BaxBench's prompt names; version is the pin the run records.
        agent_solver = as_solver(getattr(inspect_swe, harness)(
            version=spec["harness_version"], cwd=spec["workspace"]))
    else:
        raise ValueError(f"unknown harness {harness!r}")

    samples = [Sample(id=sample_id(s["arm"], s["task"]["id"], s["repeat"]),
                      input=s["task"]["prompt"], sandbox=("docker", s["compose"]),
                      metadata={"arm": s["arm"], "arm_dir": s["arm_dir"], "task": s["task"],
                                "repeat": s["repeat"], "workspace": spec["workspace"],
                                "code_dir": s["code_dir"]})
               for s in spec["samples"]]
    return Task(dataset=MemoryDataset(samples), solver=[install_arm(), agent_solver],
                scorer=export_code(), time_limit=spec.get("time_limit"),
                token_limit=spec.get("token_limit"), name="coding_guidance_benchmark")


def sample_record(sample, workspace: str) -> dict:
    """What one finished Inspect sample contributes to its samples.jsonl row."""
    store = dict(getattr(sample, "store", None) or {})
    mock = store.get("cgb_mock")
    plan = store.get("cgb_plan") or []
    home = store.get("cgb_home") or "/root"
    usage = getattr(sample, "model_usage", None) or {}
    tokens_in = sum((u.input_tokens or 0) + (u.input_tokens_cache_read or 0)
                    + (u.input_tokens_cache_write or 0) for u in usage.values())
    tokens_out = sum(u.output_tokens or 0 for u in usage.values())
    tokens_total = sum(u.total_tokens or 0 for u in usage.values())
    messages = [{"role": getattr(m, "role", None),
                 "tool_calls": [{"id": c.id, "function": c.function, "arguments": c.arguments}
                                for c in (getattr(m, "tool_calls", None) or [])]}
                for m in (getattr(sample, "messages", None) or [])]
    installs = []
    for event in getattr(sample, "events", None) or []:
        kind = getattr(event, "event", None)
        if kind == "info" and getattr(event, "source", None) == "inspect_swe":
            installs.append(event.data)                 # the harness binary that actually ran
        elif kind == "model":                           # also covers sub-agent model calls
            choices = getattr(getattr(event, "output", None), "choices", None) or []
            for choice in choices:
                m = choice.message
                messages.append({"role": "assistant", "tool_calls": [
                    {"id": c.id, "function": c.function, "arguments": c.arguments}
                    for c in (getattr(m, "tool_calls", None) or [])]})
    rows = transcript_lib.tool_calls_from_messages(messages)
    if mock:
        rows = mock["transcript"]
        tokens_in, tokens_out = mock["tokens_in"], mock["tokens_out"]
        tokens_total = tokens_in + tokens_out
    version = None
    if installs and isinstance(installs[-1], dict):
        version = installs[-1].get("version")
    error = getattr(sample, "error", None)
    limit = getattr(sample, "limit", None)
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "tokens_total": tokens_total,
            "wall_s": getattr(sample, "working_time", None) or getattr(sample, "total_time", None),
            "error": getattr(error, "message", None) if error else None,
            "limit": getattr(limit, "type", None) if limit else None,
            "harness_version": version, "harness_install": installs[-1] if installs else None,
            "transcript": rows + [{"type": "info", "source": "inspect_swe", "data": i}
                                  for i in installs],
            "touched": transcript_lib.touched(rows, plan, workspace, home)}


def run_cell(spec: dict, model: str, log_dir: str, max_samples: int | None = None) -> dict:
    """Run one cell. Returns {sample id: record}."""
    import inspect_ai
    logs = inspect_ai.eval(build_task(spec), model=model, log_dir=log_dir,
                           max_samples=max_samples, fail_on_error=False, display="plain")
    records = {}
    for log in logs:
        for sample in log.samples or []:
            records[str(sample.id)] = sample_record(sample, spec["workspace"])
    return records
