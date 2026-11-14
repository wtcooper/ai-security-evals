# Arm format

An arm is a folder. Before the agent starts, the benchmark copies the folder into the
agent's container and then leaves it alone. It does not parse, render, validate or filter
anything in it, so an arm can be any control a coding agent can be given through files: a
skill, a rules or instruction file, a hook, an MCP server configuration, or a mix.

This repository ships one arm, `arms/placebo`. Every other arm comes from the user.

## Layout

```
my-arms/                      <- pass this to --arms
├── team-rules/               <- one arm; the folder name is the arm name
│   ├── arm.json              <- optional label, never copied
│   ├── <files and folders>   <- copied into the agent's working directory
│   └── _home/                <- optional; its contents are copied into the agent user's home
└── placebo/                  <- copy of arms/placebo, to show the noise floor
```

- **`baseline`** is implicit: nothing installed. It is always run and no folder may use the
  name.
- **Arm names** are folder names: letters, digits, `.`, `_`, `-`.
- **`arm.json`** is one line that names the control type for the report:
  `{"control_type": "skill"}` (optionally with a `"description"`). It is the only file the
  benchmark reads, and it reads nothing else from it. Without it the report says "not labelled".
- **Working directory.** For BaxBench tasks it is `/app`; the agent is told to write the app
  into `/app/code`. A file `team-rules/X.md` lands at `/app/X.md`, and
  `team-rules/.agent/skills/a/SKILL.md` at `/app/.agent/skills/a/SKILL.md`. Nothing from the
  arm is placed in `/app/code`, so the arm is never part of the scored app unless the agent
  copies it there.
- **`_home/`** is for controls a harness reads from the user's home directory.
  `team-rules/_home/.config/x.toml` lands at `$HOME/.config/x.toml` (the container user is
  root for BaxBench's images).

## What the copy preserves

- File bytes, exactly. Binary files are fine.
- Permission bits, so a hook script stays executable.
- Symlinks are followed when they point inside the arm folder. A symlink that points outside
  it is an error.
- Not preserved: empty directories, ownership, timestamps.

`run.json` records each arm's file count and a sha256 fingerprint over every file's path and
bytes, so a result can be tied to the exact folder that produced it.

## Put files where your harness looks

The benchmark does not know which files a harness loads. Lay the folder out exactly as the
files would sit in a project (or home directory) on a developer's machine, using the
harness's own documentation. Then check, on a `smoke` run, that the arm was reached (below).

Three constraints come from how the agent is run:

1. **No network in the container.** An MCP server in an arm must be a local process whose
   runtime is already in the task image; a remote MCP server cannot be reached. A hook can
   only call programs present in the image. BaxBench's images are Debian-based and hold the
   framework's own toolchain.
2. **inspect-swe writes some configuration itself, after the arm is copied.** A file from
   the arm at the same path is overwritten. Read from the inspect-swe 0.3.0 source:

   | Harness | File inspect-swe writes on every run |
   |---|---|
   | `claude_code` | `$HOME/.claude/settings.json` |
   | `codex_cli` | `<working directory>/.codex/config.toml` (it also points `CODEX_HOME` at `<working directory>/.codex`) |
   | `gemini_cli` | `$HOME/.gemini/settings.json` |
   | `opencode` | `$HOME/.config/opencode/opencode.json` |

   If your control needs one of these exact files, it cannot be tested as a plain folder
   with this version; use a location the harness reads that is not in the table.
3. **The harness runs unattended.** inspect-swe 0.3.0 starts `claude_code` with permission
   prompts skipped and `codex_cli` with approvals set to never (read from its source; the
   other two were not checked). A control that works by asking the user a question will not
   behave as it does interactively.

## The placebo

`arms/placebo` holds notes about office plants and a tide table. Nothing in it concerns
code. It answers one question: how different do two arms look on this run when the arm
cannot matter? Read your arm's difference from baseline against the placebo's.

As shipped, the placebo is files a harness is unlikely to load by itself, so it mostly shows
run-to-run noise. If your control is delivered through a file the harness loads into every
conversation, make your own placebo of the same kind: copy `arms/placebo/NOTES.md` into a
new arm folder under the file name your control uses. That placebo also costs context
tokens, as your control does, and so is the fairer comparison.

## Was the arm reached?

Three places to look after a `smoke` run:

- **Installed files.** Each Inspect sample log has an info event with source
  `coding_guidance_benchmark` listing the paths that were written.
- **The diagnostic table** in `summary.md`, read from tool calls only:
  - *Named an arm path*: a tool call argument named a file the arm installed, or a directory
    that holds arm files. Only the installed paths are used; file contents are not.
  - *Called a skill tool*: a tool whose name is or ends in `skill` was called.
  - *Called an MCP tool*: a tool whose name starts with `mcp__` was called.
  The last two are shown for the baseline too, as the level to compare against.
- **`transcripts/<harness>__<model>/<arm>/<task>__r<i>.jsonl`**: the tool calls of one run.

What the diagnostic cannot see: a file the harness loads into context by itself leaves no
tool call, and a hook runs outside the model's view. "No signal" means the transcript holds
no evidence, not that the arm had no effect. The skill and MCP signals follow Claude Code's
tool naming and were not checked against the other harnesses.
