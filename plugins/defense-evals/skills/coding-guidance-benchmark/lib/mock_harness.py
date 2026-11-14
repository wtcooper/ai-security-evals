"""The `mock` harness: a plain-Python stand-in for a coding agent. No model, no network, no
key. It exists so that task selection, arm installation, scoring, samples.jsonl and the
report can be run end to end; nothing it produces says anything about a real agent.

What it does in a workspace:
  * lists the files it finds there (an installed arm shows up here);
  * on a seeded coin flip "reads" the first of them and logs a Read tool call, so the
    touched-the-arm diagnostic has something to find;
  * writes fixed code into `code/`:
      - for a fake task, one of four canned files (correct and clean, correct with the fake
        weakness, wrong reply, unparsable), drawn with a hash of the seed, the task, the
        repeat and the NAMES of the files in the workspace;
      - for any other task, a copy of the `--mock-code` directory.
The draw depends on file names so that installing an arm perturbs the outcome the way any
change of context perturbs a real agent. The arm's content is never used, so the difference
between arms under this harness is noise by construction.
Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

VERSION = "1"
VARIANTS = (("good", 0.55), ("insecure", 0.75), ("broken", 0.90), ("nobuild", 1.0))


def _draw(seed: int, task_id: str, repeat: int, names: list[str]) -> tuple[float, float]:
    digest = hashlib.sha256(f"{seed}|{task_id}|{repeat}|{'|'.join(names)}".encode()).digest()
    return (int.from_bytes(digest[:4], "big") / 2 ** 32,
            int.from_bytes(digest[4:8], "big") / 2 ** 32)


def fake_app(expect: dict, variant: str) -> str:
    if variant == "nobuild":
        return "{ this is not JSON"
    reply = expect["reply"] if variant != "broken" else "wrong " + expect["reply"]
    app: dict = {"routes": {expect["route"]: reply}}
    if variant == "insecure":
        app["debug"] = True
    return json.dumps(app, indent=2) + "\n"


def run(task: dict, workspace: str | Path, seed: int, repeat: int,
        mock_code: str | Path | None = None) -> dict:
    """Act as the agent for one sample. Returns token counts, wall time and a transcript in
    the normalised form the diagnostic reads ({"type": "tool_call", "tool", "input"})."""
    start = time.monotonic()
    workspace = Path(workspace)
    names = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*")
                   if p.is_file())
    u_variant, u_read = _draw(seed, task["id"], repeat, names)
    transcript: list[dict] = []
    read_chars = 0
    if names and u_read < 0.75:
        target = workspace / names[0]
        read_chars = len(target.read_bytes())
        transcript.append({"type": "tool_call", "tool": "Read",
                           "input": {"file_path": str(target)}})

    code = workspace / "code"
    code.mkdir(parents=True, exist_ok=True)
    written = 0
    if "expect" in task:
        variant = next(name for name, upto in VARIANTS if u_variant < upto)
        text = fake_app(task["expect"], variant)
        (code / "app.json").write_text(text)
        written = len(text)
        transcript.append({"type": "tool_call", "tool": "Write",
                           "input": {"file_path": str(code / "app.json")}})
    elif mock_code:
        variant = "mock-code"
        for dirpath, _, filenames in os.walk(mock_code):
            for name in sorted(filenames):
                src = Path(dirpath) / name
                dest = code / src.relative_to(mock_code)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                written += src.stat().st_size
                transcript.append({"type": "tool_call", "tool": "Write",
                                   "input": {"file_path": str(dest)}})
    else:
        raise ValueError("the mock harness needs --mock-code <dir> for tasks that are not fake "
                         "tasks: it has no model to write an app with")
    tokens_in = (len(task.get("prompt", "")) + read_chars) // 4
    tokens_out = written // 4
    return {"variant": variant, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "wall_s": round(time.monotonic() - start, 4), "transcript": transcript,
            "harness_version": VERSION, "error": None}
