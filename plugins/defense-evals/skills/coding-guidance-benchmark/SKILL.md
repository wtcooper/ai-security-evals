---
name: coding-guidance-benchmark
description: >-
  A/B test of guidance placed in front of a coding agent: does a skill, rules file, hook,
  MCP server configuration, or any mix of them change the security of the code the agent
  writes? Each arm is an opaque folder copied into the agent's workspace before it starts;
  the baseline has nothing installed. A real coding-agent harness (Claude Code, Codex CLI,
  Gemini CLI or OpenCode, run through Inspect AI's inspect-swe) builds the same seeded
  BaxBench tasks under every arm, and BaxBench's functional tests and exploits score the
  result. Reports the correct-and-secure rate per arm with intervals, the paired difference
  from baseline, functional and secure rates separately, failed builds, the tokens and time
  the guidance cost, and whether the agent touched the guidance at all. Use it when someone
  asks whether a piece of coding guidance works. It ships no guidance of its own. For a
  guardrail or content filter use guardrail-benchmark.
license: MIT
compatibility: "Requires Docker, git, and two Python environments: one with inspect_ai 0.3.289 and inspect-swe 0.3.0 plus the SDK of the model provider (runs the agent), and Python 3.12 with pipenv (runs BaxBench's scoring). The keyless smoke test needs only Python 3.11+."
---

# coding-guidance-benchmark — does this guidance make the agent's code more secure?

You are running this skill **on behalf of a user** who has some guidance for a coding agent
and wants to know whether it changes the security of the code the agent writes. Drive
**Plan → Run → Analyze**. Use `AskUserQuestion` for choices.

The arms are the one thing that varies. Everything else is held fixed: the harness and its
version, the model, the tasks, the prompt, the scorer. This skill measures; it does not say
whether a result is good enough, and it ships no guidance, rules, hooks or templates. The
only arm in this folder is a placebo.

Execution tier: **T1**. The agent works in a Docker container with no network. See Notes for
what scoring does.

| Held fixed | Varied |
|---|---|
| Harness and pinned version, model, time limit | The arm: a folder copied in before the agent starts |
| The seeded draw of BaxBench tasks, the same for every arm | `baseline` = nothing installed (always run) |
| BaxBench's prompt with **no** safety prompt | |
| BaxBench's functional tests and exploits | |

```
SKILL.md  run_benchmark.py  report.py  new_experiment.sh
arms/placebo/            the only arm shipped: irrelevant content
fixtures/                fake tasks and fixed code for the keyless checks (not BaxBench content)
lib/                     arms, tasks, baxbench (+ bridge), harnesses, transcript, stats, evalkit
references/arm-format.md             how to lay out an arm folder
references/baxbench-integration.md   what is taken from BaxBench and how results are read
```

---

## PLAN

### 1. Preflight
- `docker info` works.
- **Agent environment** (runs Inspect and the harness):
  ```
  uv venv .venv-agent
  uv pip install --python .venv-agent/bin/python inspect_ai==0.3.289 inspect-swe==0.3.0 anthropic
  ```
  Replace `anthropic` with the SDK of the provider that serves the model. Inspect names the
  missing package if one is needed. The provider's API key stays on this machine; it is not
  passed into the agent's container.
- **BaxBench environment** (runs scoring): Python 3.12 and `pipenv`. The runner clones
  BaxBench at its pinned commit on first use; then run `pipenv sync` once inside the clone
  (`--baxbench-dir`, default `~/.cache/coding-guidance-benchmark/baxbench-<commit>`).
- The harness binary is downloaded on this machine and copied into each container, so this
  machine needs network access; the containers do not.

### 2. Ask the user
- **Arms.** A directory whose subfolders are the arms, one folder per piece of guidance.
  The user supplies them; read `references/arm-format.md` with them and check each folder is
  laid out the way their harness will find it. Add `arms/placebo` beside their arms: it shows
  how far two arms differ when the arm cannot matter.
- **Harness and version**, e.g. `claude_code@2.1.311`. A version number is required so the
  result can be reproduced. `codex_cli`, `gemini_cli` and `opencode` are accepted too.
- **Model**, as an Inspect model string (`anthropic/<id>`, `openai/<id>`, ...).
- **Frameworks** (optional): restrict the draw, e.g. `--frameworks Python-Flask,JavaScript-express`,
  when the guidance is about one stack.
- **Depth and repeats** (next step).

### 3. Depth, repeats and cost (`AskUserQuestion`)
`--depth`: `smoke` (25 tasks; proves the wiring only: a per-arm rate near 50% has an
interval of about ±19 points), `standard` (100 tasks, about ±10 points), `full` (all 392,
or all tasks of the chosen frameworks), or a number. `--repeats N` runs each task N times per arm; agents are not deterministic, so use
at least 2 when the user wants to know how stable a result is. Show the cost first:

```
python run_benchmark.py --arms <arms dir> --harness claude_code@<version> \
  --model <model> --depth standard --repeats 2 --plan
```
The plan lists agent runs and app builds per arm and for the whole run, and a power line:
how precise a rate is at this many tasks, and how many tasks two arms must differ on, all in
one direction, to be separated once the report's McNemar tests are Holm-adjusted. Say so
when that is larger than the effect the user hopes to see. It does **not** estimate tokens: token cost depends on the harness, the model and how long the agent works
on a task. Run `smoke` first and read the Cost table before committing to a deeper run.
A deeper run with the same `--seed` contains every task of a shallower one.

### 4. Open an experiment folder
```
bash new_experiment.sh coding-guidance-benchmark "<label>" inspect \
  --arms baseline,<arm>,placebo --k <repeats> --tool <harness>@<version> --model <model> \
  --benchmark baxbench@de885cd
```
It prints `EXP=<path>`. The runner fills in the manifest's command, task draw, harness
context, arm fingerprints and token totals when `--out` is `<EXP>/results`.

Before the first agent run the runner writes the analysis plan to `<out>/plan.json`: arms
and baseline, the three metrics, depth, seed, repeats, harness/model cells, frameworks, arm
fingerprints, no judge (scoring is BaxBench's deterministic tests), the task corpus (BaxBench
at its commit, public) and the organisation's `criteria.json` if one is found. The report
lists any departure from it; `--plan-reason "<text>"` records why a plan was changed.

---

## RUN
```
.venv-agent/bin/python run_benchmark.py --arms <arms dir> \
  --harness claude_code@<version> --model <model> \
  --depth smoke --repeats 1 --out "<EXP>/results"
```
What happens, per harness and model:
1. BaxBench is asked for each task's agent prompt and Dockerfile. One agent image per
   framework environment is built from BaxBench's own Dockerfile, cut before the step that
   copies generated code.
2. For every arm × task × repeat a fresh container starts with no network. The arm folder
   is copied in, then the harness runs with BaxBench's prompt in `/app`.
3. What the agent left in `/app/code` is copied out to
   `<out>/baxbench/<harness>__<model>__<arm>/<scenario>/<framework>/temp0.0-openapi-none/sample<i>/code`.
4. BaxBench `--mode test` builds each app, runs functional tests and exploits, and writes
   `test_results.json` beside `code/`.

Written to `<out>/`: `plan.json`, `samples.jsonl` (one row per arm × task × repeat, with `repeat`: functional pass,
secure, correct-and-secure, build_ok, tokens, wall time, the diagnostic), `summary.md`,
`summary.json`, `run.json` (settings, arms and their fingerprints, the drawn tasks),
`transcripts/` (tool calls per run), `logs/` (Inspect `.eval` logs), `baxbench/`.

Several harnesses or models can be given comma-separated; each harness × model pair is
reported as its own comparison against its own baseline. If scoring is interrupted,
`--score-only --out <same dir>` scores the code already generated without running the
agent again.

**Before scaling up from `smoke`, check in `summary.md`:**
- the harness version shown is the one requested;
- "No code written" and "Build failed" are not most of the runs. If they are, read one
  `test.log` under `<out>/baxbench/`: a build that fails for every arm is an environment
  problem (see Notes), not a finding;
- the diagnostic table for each real arm. If the user expects the agent to read a file or
  call a tool from the arm and there is no signal, check the arm's layout before spending more.

---

## ANALYZE
`<out>/summary.md` is written by the run. To rebuild it, or to compare against another arm:
```
python report.py "<EXP>/results" [--baseline <arm>] --json "<EXP>/summary.json" > "<EXP>/summary.md"
```
Present to the user in this order:
1. **Read first.** Failed builds, runs with no code, harness errors, exploits that could
   not complete, and `near_ceiling` (every arm at or above `--ceiling`, default 0.95, on a
   metric: the tasks separate arms poorly). These change how the rates should be read; none
   of them hides a number. Then the analysis plan and any departure from it.
2. **Outcome per arm.** Correct and secure is the headline: every functional test passed
   and no exploit succeeded. Always read it beside the other two columns. An arm can raise
   the secure rate by producing apps that do not work, so the functional-pass rate is shown
   separately, and the secure rate only counts apps whose exploits actually ran.
3. **Paired difference from baseline**, per metric: the difference in points with its
   interval, how many tasks changed in each direction, and the exact McNemar p-value with
   its Holm-adjusted value beside it (adjusted across every arm, metric and harness/model
   cell in the report). Call a difference unlikely to be noise only on the adjusted value,
   and say plainly when the interval includes zero: the run did not separate the arm from
   the baseline. Compare the arm's difference with the placebo's; a difference no larger than
   the placebo's is within noise for this run.
4. **Repeats** (with `--repeats` 2 or more): the flip rate per arm and metric (share of
   tasks whose outcome changed between repeats), the rate in each repeat, and the tasks that
   flipped. Flip rates under the baseline and the placebo are the noise floor.
5. **Cost.** Tokens and wall time per run, and what the arm added.
6. **Diagnostic.** Whether the transcript shows the agent naming a path from the arm,
   calling a skill tool or calling an MCP tool. It separates "the guidance did not help"
   from "the guidance was never reached". No signal is not proof of no use: a file the
   harness loads by itself, or a hook, leaves no tool call.

Do not tell the user whether the guidance is worth adopting. Offer next steps instead: a
deeper `--depth` or more `--repeats` when the interval is wide, a framework restriction that
matches what the guidance covers, or another harness or model on the same seed.

---

## Smoke test (no model, no key, no Docker, a few seconds)
```
python run_benchmark.py --arms arms --harness mock --tasks fixtures/fake_tasks.json \
  --depth smoke --repeats 2 --out /tmp/coding-guidance-smoke
cat /tmp/coding-guidance-smoke/summary.md
```
The `mock` harness is a plain-Python stand-in that writes fixed code; the tasks and the
scorer are bundled fakes, not BaxBench. Expected: 32 rows in `samples.jsonl` (2 arms × 8
tasks × 2 repeats), a `summary.md` whose "Read first" section says the harness is a mock,
a paired-difference table for `placebo` with a `p (Holm)` column, an `Analysis plan`
section with no departures, a `Repeats` table listing the tasks that flipped, some failed
builds, and a diagnostic row showing the placebo was named in some runs. The mock's draw depends on the file names in its
workspace, so the two arms differ by chance alone: this is what a noise floor looks like.
The numbers say nothing about any agent.

Two further keyless checks, when Docker and the two environments are set up:
```
# the Inspect sandbox path: image, arm installation in the container, code export
.venv-agent/bin/python run_benchmark.py --arms arms --harness mock-sandbox \
  --tasks fixtures/fake_tasks.json --depth 3 --out /tmp/coding-guidance-sandbox

# the BaxBench scoring path: fixed code through BaxBench's real test mode
.venv-agent/bin/python run_benchmark.py --arms arms --harness mock-sandbox \
  --frameworks Python-Flask --depth 1 --mock-code fixtures/mock-app --out /tmp/coding-guidance-scoring
```
Expected for the second: `build_ok` true and `functional_pass` false in `samples.jsonl`
(the fixed app answers 404 to everything). "Build failed" here means BaxBench's image does
not build on this machine; fix that before a real run.

## Notes
- **What a number means.** The rates are for this harness version, this model and the drawn
  tasks. BaxBench is public and may be in training data; read the difference between arms,
  not the level.
- **No safety prompt.** BaxBench can add a generic or CWE-specific security reminder to its
  prompt. This skill always asks for none, so the arm is the only security guidance.
- **Failed builds.** BaxBench records a failed build as every test raising an exception and
  an empty CWE list. The runner reads BaxBench's `test.log` to tell a failed build from an
  app that ran, counts it as not correct-and-secure, and leaves it out of the secure rate.
- **No judge.** Scoring is BaxBench's tests and exploits, so blind-judge prompts, reply
  length and second-judge re-grading do not apply.
- **Repeats.** Per-arm intervals are Wilson intervals over runs. The paired difference
  resamples whole tasks, and McNemar uses one outcome per task (a strict majority of its
  repeats), so repeats are not counted as independent evidence.
- **Scoring is not sandboxed by this skill.** The agent's container has no network.
  BaxBench then builds and runs the generated apps in its own containers, on Docker's
  default network with a published port, and builds need package registries. Run on a
  machine where that is acceptable.
- **inspect-swe writes some harness configuration itself** and will overwrite an arm file at
  the same path. See `references/arm-format.md`.
- **Disk.** BaxBench leaves one image per framework (`baxbench_<language>_<framework>`), and
  the runner one `cgb-agent:<hash>` image per framework environment. Remove them with
  `docker image rm` when done.
- **Verified here** (2026-11-14, no API key): the smoke test; `mock-sandbox` through Inspect
  with a no-network container; BaxBench cloned at the pinned commit, its prompt and
  Dockerfiles read for all 392 tasks; code scored by BaxBench's real test mode for one
  Python-Flask task, giving a correct-and-secure result, a result with CWE-94 and CWE-400,
  and a failed build; and `claude_code@2.1.311` driven by a scripted mock model, which
  installed the binary in the container, wrote code that was exported, and produced the
  transcript the diagnostic reads.
- **Not verified:**
  - No run with a real model. Token counts, time limits and agent behaviour on BaxBench
    tasks are untested.
  - `codex_cli`, `gemini_cli` and `opencode` were not run at all. The transcript reader was
    checked against Claude Code's tool calls only; the skill and MCP signals rely on Claude
    Code's tool naming.
  - Agent images were built and used for Python-Flask only. The Dockerfile cut was checked
    as text for all 14 frameworks, not built.
  - BaxBench's stock Python image did not build in the build environment: on 2026-11-14
    `apt-get install sqlite3` in its Dockerfile got a 404 from the Debian bullseye security
    archive, and HTTPS from containers was intercepted by a local proxy. Scoring was
    verified with a locally patched base image (sqlite3 pinned to the main archive, proxy
    CA added); BaxBench's code was not changed. Run the scoring check above on your machine.
  - Whether a given harness loads a given file from an arm. The benchmark copies the folder;
    it does not know what the harness does with it.
  - Hooks and MCP servers inside an arm were not exercised.
  - The registered plan, Holm column, repeat flip rates and near-ceiling flag were exercised
    with the mock harness and fake scorer only. They are added by `report.py` around
    `lib/stats.py`'s report, so a change to that report's table layout needs `report.py`
    (and `tests/test_report.py`) updated with it.
