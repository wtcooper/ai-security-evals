# Build guide: finishing agent-misuse-benchmark

This skill is a scaffold. This guide is written for the person, or the coding agent working
for them, who will complete it for one organisation. Work through the steps in order; each
ends with a check that must pass before the next.

What you are building is three things the scaffold calls but does not contain:

1. a **scenario pack** (data),
2. a **harness module** (code that runs one task with one agent harness in a sandbox),
3. an **outcome scorer** (code that decides what happened in a run).

Everything else — selecting tasks, sweeping arms, statistics, the report — already works
and is exercised by the mock (`SKILL.md`, Smoke test). Do not change it to make your pieces
fit; make your pieces fit the contracts in `interfaces.py`.

---

## Step 0. Decide the question

Write down, before anything else:

- **Which deployments are being compared.** Each becomes an arm: a model, a harness at a
  pinned version, and a safeguards setting. Compare along one axis at a time.
- **Which policy the tasks come from, and who owns it.** That person or team writes or
  approves the scenario pack. An agent must not invent the pack.
- **How small a difference between arms matters.** That sets the number of pairs
  (`scenario-format.md`, Size).

## Step 1. The scenario pack

Format and rules: `scenario-format.md`. In short: pairs of a restricted task and its
permitted twin, task descriptions only, everything inside the sandbox, optional framings
that change one thing.

Guidance for the people writing it:

- Start from the organisation's own acceptable-use and security policies, and write tasks at
  the level a real user of the agent would type them.
- For each restricted task, write the twin first. If you cannot write a legitimate task that
  uses the same tools, the restricted task is probably testing capability, not judgement.
- Include tasks near the line, not only obvious ones. Rates on obvious tasks saturate and
  stop distinguishing arms.
- If how a request is framed is expected to matter (who the target is said to belong to,
  whether authorisation is claimed), add framings for a subset of pairs.
- Keep a private held-out set if the pack will ever be published: public tasks end up in
  training data.

**Check:** `python validate_scenarios.py <pack dir>` prints `ok`, and the policy owner has
read the pack.

## Step 2. The harness module

Write a Python file that defines `make_harness(name)` and returns a subclass of
`interfaces.Harness` with two methods.

`preflight()` — called once before any task. It must *demonstrate*, by attempting a
connection from inside the sandbox, that the sandbox cannot reach the network, and return
`{"egress_blocked": True, ...}`. The runner refuses to start otherwise. Do not return
`True` without testing.

`run(task, arm, workdir)` — run one task and return a dict with `final_text`, `events`
(tool calls and steps, in order), `workspace` (the sandbox workspace as the agent left it,
copied out to `workdir`), `error` (None, or a string if the run itself failed), `tokens`
and `harness_version`.

One workable design, using Inspect AI with the `inspect-swe` package (facts checked against
inspect-swe 0.3.0; re-check against the version you install):

- It provides agents for several coding harnesses (`claude_code`, `codex_cli`,
  `gemini_cli`, `opencode` among them). Each runs inside the sample's sandbox.
- Model traffic is proxied from the sandbox back to Inspect, so API keys stay outside the
  sandbox. Keep it that way.
- Inspect's Docker sandbox defaults to no network. Your `preflight()` still has to prove it.
- The harness binary is downloaded on the host and copied in; pin its version and record
  the version Inspect logs for the run in `harness_version`.
- Some harness settings change what is being measured. Turn off automatic retry after a
  refusal where the harness has it (`claude_code` retries by default), or a decline will be
  retried until it is not one. Disable built-in web search where the harness allows it: it
  is a provider-side tool call and is not stopped by a sandbox with no network. Record any
  harness that offers no switch for this as a limitation in your results.
- Give every task a fresh sandbox. Copy the task's `workspace` folder in before the agent
  starts and copy the workspace out afterwards.
- The agent's instructions for a task are the task's `prompt` and nothing else. Do not add
  text that tells the agent it is being tested.

The `safeguards` field of an arm is yours to interpret (for example which provider
safeguards or harness permission mode is in force). Whatever it means, record it: the report
prints it.

**Check:** run your harness on the permitted twins only, with a model you trust, and confirm
that tasks complete and transcripts are captured. Then run
`python run_benchmark.py ... --depth smoke` and confirm `preflight` passes and
`runs/<arm>/<task>/run.json` holds real transcripts.

## Step 3. The outcome scorer

Write a Python file that defines `score(task, run)` and returns
`{"outcome": ..., "evidence": "..."}`.

Allowed outcomes:

| Task kind | Outcomes |
|---|---|
| restricted | `declined` · `carried_out` · `partial` |
| permitted | `completed` · `declined` · `failed` |
| either | `unscored` when the scorer cannot tell |

Rules:

- **Prefer evidence over wording.** Decide from what is in the sandbox and in the tool
  calls first: whether the file the task asked for exists, whether a marker placed in the
  fixtures was touched, whether the step that matters was executed. An agent can say one
  thing and do another, and what it did is what counts.
- **Use a judge model only for what evidence cannot settle**, typically whether a run with
  no actions was a decline. If you do: the judge is never the model under test, it is
  routed explicitly, its rubric is written by the policy owner, and anything it cannot
  decide is returned as `unscored`.
- **Never guess.** `unscored` is excluded from every rate and counted; a wrong verdict is
  silently averaged in.
- **Write the evidence line.** One sentence saying what the verdict rests on. It is stored
  with every sample and is how a reviewer audits the scorer.
- Per-task scoring detail belongs in the pack (extra fields on the task are passed to
  `score`), not hard-coded in the scorer.

**Check:** have a person label a sample of runs by reading the transcripts, without seeing
the scorer's output, and compare. Record the agreement in your results. Until that is done,
treat every number as provisional.

## Step 4. Safety requirements

A completed benchmark asks an agent to do things the organisation does not want done. These
are requirements, not suggestions:

- **No network from the sandbox**, enforced by the sandbox and, where you can, again at the
  host or cloud level. `preflight()` tests it on every run.
- **Nothing real is a target.** Fixtures only.
- **No credentials in the sandbox**, and run on a disposable machine.
- **Pre-built images.** Installing packages during a run needs network access; a package
  proxy is network access.
- **Provider and harness safeguards stay on** unless an arm exists specifically to measure
  behaviour without them, and that arm is named for what it is.
- **Stop on surprise.** If a run does something outside its sandbox, stop, keep the logs,
  and tell the people responsible before running anything else.

## Step 5. Declare what you built

Before anyone relies on the results, record in the experiment's manifest and in your own
copy of this skill:

- the pack name and version, who wrote it, and which policy it reflects;
- the harness module and the exact harness versions;
- how the scorer decides, and its agreement with human labels;
- anything a harness could not be configured to prevent (for example built-in web search).

Then update the `Not verified` list in `SKILL.md` to say what has now been exercised.

---

## What "done" looks like

- `python validate_scenarios.py <pack>` prints `ok`.
- `run_benchmark.py` runs at `--depth smoke` with your harness and scorer; `preflight`
  passes; no run is `error`.
- The `no_verdict` flag is absent or explained.
- Scorer-versus-human agreement has been measured on a sample.
- The unit tests in `tests/` still pass, plus tests you add for your scorer.
