"""Transcripts and the touched-the-arm diagnostic. Stdlib only.

A normalised transcript is a list of rows; the ones that matter here are tool calls:

    {"type": "tool_call", "tool": "<name the harness gave the tool>", "input": {...}}

The diagnostic answers one question without interpreting the arm: is there any sign in the
transcript that the agent used what was installed? It looks for three generic signals.

  arm_file  a tool call argument names a path the arm installed (a file, or a directory
            that holds arm files). Only the installed PATHS are used, never file contents.
  skill     a tool whose name is, or ends in, "skill" was called (how harnesses load a skill).
  mcp       a tool whose name starts with "mcp__" was called (the name Claude Code gives MCP
            tools; inspect-swe builds its allow-list from the same pattern).

What it cannot see: a file the harness loads into context by itself (its instruction file)
leaves no tool call, and a hook runs outside the model's view. So "no signal" does not prove
the arm was unused; "signal" does show it was reached. The skill and mcp signals are also
reported for the baseline, as the level to compare an arm against.
"""
from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path

SPLIT = re.compile(r"""[\s"'`=,;:()<>|&\[\]{}]+""")


def tool_calls_from_messages(messages: list[dict]) -> list[dict]:
    """Tool calls from Inspect chat messages (dict form). With inspect-swe the harness runs
    its own tools inside the sandbox, so they appear as `tool_calls` on assistant messages,
    not as Inspect tool events."""
    rows, seen = [], set()
    for message in messages or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            key = call.get("id") or json.dumps(call, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            args = call.get("arguments")
            rows.append({"type": "tool_call", "tool": str(call.get("function", "")),
                         "input": args if isinstance(args, dict) else {"value": args}})
    return rows


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def arm_paths(plan: list[dict], workspace: str, home: str) -> set[str]:
    """Absolute paths the arm put in place: each installed file and every directory between
    it and the root it was copied into (the roots themselves excluded)."""
    paths = set()
    for item in plan:
        root = home if item.get("root") == "home" else workspace
        dest = posixpath.normpath(item["dest"])
        paths.add(dest)
        parent = posixpath.dirname(dest)
        while parent and parent != posixpath.normpath(root) and parent != "/":
            paths.add(parent)
            parent = posixpath.dirname(parent)
    return paths


def touched(rows: list[dict], plan: list[dict], workspace: str, home: str) -> dict:
    """The three signals for one run. `arm_file` is None when nothing was installed."""
    targets = arm_paths(plan, workspace, home)
    arm_file = False if plan else None
    skill = mcp = False
    for row in rows:
        if row.get("type") != "tool_call":
            continue
        name = str(row.get("tool", ""))
        lowered = name.lower()
        if lowered.startswith("mcp__"):
            mcp = True
        if lowered == "skill" or lowered.endswith("skill"):
            skill = True
        if plan and not arm_file:
            for text in _strings(row.get("input")):
                for token in SPLIT.split(text):
                    if not token:
                        continue
                    if token.startswith("~/"):
                        token = posixpath.join(home, token[2:])
                    path = posixpath.normpath(posixpath.join(workspace, token))
                    if path in targets:
                        arm_file = True
                        break
                if arm_file:
                    break
    return {"arm_file": arm_file, "skill": skill, "mcp": mcp}


def write(path: str | Path, rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def read(path: str | Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]
