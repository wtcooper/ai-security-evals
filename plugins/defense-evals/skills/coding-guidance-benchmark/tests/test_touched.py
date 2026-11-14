"""The touched-the-arm diagnostic: generic signals from tool calls, arm never interpreted."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import transcript  # noqa: E402

WS, HOME = "/app", "/root"
PLAN = [
    {"src": "/does/not/exist/NOTES.md", "rel": "NOTES.md", "root": "workspace",
     "dest": "/app/NOTES.md", "mode": 0o644},
    {"src": "/does/not/exist/SKILL.md", "rel": ".agent/skills/demo/SKILL.md", "root": "workspace",
     "dest": "/app/.agent/skills/demo/SKILL.md", "mode": 0o644},
    {"src": "/does/not/exist/config.toml", "rel": ".config/tool/config.toml", "root": "home",
     "dest": "/root/.config/tool/config.toml", "mode": 0o644},
]


def call(tool, **inp):
    return {"type": "tool_call", "tool": tool, "input": inp}


def touched(*rows, plan=PLAN):
    return transcript.touched(list(rows), plan, WS, HOME)


def test_reading_an_arm_file_by_absolute_or_relative_path():
    assert touched(call("Read", file_path="/app/NOTES.md"))["arm_file"] is True
    assert touched(call("read_file", path="NOTES.md"))["arm_file"] is True
    assert touched(call("Read", file_path="./.agent/skills/demo/SKILL.md"))["arm_file"] is True


def test_shell_command_that_names_an_arm_path():
    assert touched(call("Bash", command="cat ./NOTES.md | head -5"))["arm_file"] is True
    assert touched(call("shell", command=["bash", "-lc", "ls -la .agent/skills"]))["arm_file"] is True
    assert touched(call("Bash", command="cat ~/.config/tool/config.toml"))["arm_file"] is True


def test_other_files_do_not_count():
    result = touched(call("Write", file_path="/app/code/app.py", content="see NOTES for details"),
                     call("Read", file_path="/app/code/NOTES.md"),
                     call("Bash", command="ls /app && python3 code/app.py"),
                     call("Read", file_path="/root/.bashrc"))
    assert result == {"arm_file": False, "skill": False, "mcp": False}


def test_skill_and_mcp_signals_come_from_the_tool_name_alone():
    assert touched(call("Skill", skill="demo"))["skill"] is True
    assert touched(call("mcp__docs__search", query="x"))["mcp"] is True
    assert touched(call("Bash", command="echo skill mcp__x"))["skill"] is False


def test_baseline_has_no_arm_file_signal_but_still_reports_skill_and_mcp():
    result = touched(call("Read", file_path="/app/NOTES.md"), call("mcp__a__b"), plan=[])
    assert result == {"arm_file": None, "skill": False, "mcp": True}


def test_diagnostic_uses_installed_paths_only_and_never_opens_the_arm():
    # Every `src` in PLAN points at a file that does not exist: nothing is read.
    assert touched(call("Read", file_path="/app/NOTES.md"))["arm_file"] is True
    assert "/app/.agent" in transcript.arm_paths(PLAN, WS, HOME)
    assert WS not in transcript.arm_paths(PLAN, WS, HOME)
    assert HOME not in transcript.arm_paths(PLAN, WS, HOME)


def test_tool_calls_are_read_from_assistant_messages_and_deduplicated():
    messages = [
        {"role": "user", "tool_calls": None},
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": "Read", "arguments": {"file_path": "/app/NOTES.md"}}]},
        {"role": "tool", "tool_calls": None},
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "function": "Read", "arguments": {"file_path": "/app/NOTES.md"}},
            {"id": "c2", "function": "Write", "arguments": {"file_path": "/app/code/app.py"}}]},
    ]
    rows = transcript.tool_calls_from_messages(messages)
    assert [(r["tool"], r["input"]["file_path"]) for r in rows] == [
        ("Read", "/app/NOTES.md"), ("Write", "/app/code/app.py")]
    assert transcript.touched(rows, PLAN, WS, HOME)["arm_file"] is True


def test_transcript_round_trip(tmp_path):
    rows = [call("Read", file_path="/app/NOTES.md")]
    transcript.write(tmp_path / "t" / "x.jsonl", rows)
    assert transcript.read(tmp_path / "t" / "x.jsonl") == rows
