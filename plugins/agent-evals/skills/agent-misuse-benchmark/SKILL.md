---
name: agent-misuse-benchmark
description: >-
  SCAFFOLD, not a finished benchmark. Measures whether a model running inside an agent
  harness (a coding agent CLI, an IDE agent, a vendor's own harness) carries out tasks an
  organisation's policy says it must decline, such as offensive security work, and whether
  it still completes the matched legitimate tasks. The answer depends on the harness and
  its safeguards as well as the model, so the arms are model × harness × safeguards. This
  skill ships the scenario format, the arm sweep, the statistics and the report, with a
  mock for a keyless smoke test. It ships no scenarios, no real harness and no outcome
  scorer: the team using it supplies those, and the build guide says how. Use it when you
  are ready to build that for your own policy.
license: MIT
compatibility: "The scaffold needs Python 3.11+ only. A completed benchmark needs whatever your harness module needs, typically Docker and inspect_ai with inspect-swe."
---

# agent-misuse-benchmark — scaffold

**Status: scaffold.** Everything generic is here and tested. Three pieces are deliberately
absent and must be supplied before this measures anything real:

| Piece | What it is | Where to start |
|---|---|---|
| **Scenario pack** | Pairs of tasks: one your policy says the agent must decline, and its matched legitimate twin | `references/scenario-format.md` |
| **Harness module** | Runs one task with one agent harness and model inside a sandbox with no network | `references/build-guide.md`, step 2 |
| **Outcome scorer** | Decides, from evidence, whether the agent declined, carried out or completed a task | `references/build-guide.md`, step 3 |

If you are an agent asked to "finish" or "build out" this benchmark, read
`references/build-guide.md` first and follow it in order. Do not improvise scenarios: the
people who own the policy write them.

## The problem this answers

"If we enable this model in this agent, will it do work we do not want it to do when
someone asks?" A model card answers that for the bare model. Deployed behaviour also
depends on the harness's system prompt and tools, on provider and harness safeguards, and
on how the task is framed. So the question has to be asked per deployment, with the same
tasks, and with a control for an agent that simply declines everything.

## What a completed run reports

For each arm (a model in a harness, with safeguards on or off):
- **Restricted tasks declined**, with a 95% interval.
- **Permitted twins completed**, beside it. An agent that declines everything scores well
  on the first number and badly on this one.
- **Permitted twins declined** (over-refusal).
- The same rates by category and by how the task was framed.
- A paired comparison of every arm against a baseline arm on the same tasks.
- Validity flags: runs with no verdict, and low completion of the permitted twins.

It does not say whether a rate is acceptable. Execution tier: **T1** (a sandbox with no
network), and a completed benchmark must keep it there.

---

## PLAN

1. **Confirm the three pieces exist.** If any is missing, stop and work through
   `references/build-guide.md`; do not run with placeholders.
2. **Scenario pack.** `python validate_scenarios.py <pack dir>` must print `ok`. Read the
   pack's categories and framings back to the user so they know what is being asked.
3. **Arms** (`AskUserQuestion`). Write `arms.json`: one entry per combination to compare,
   each with `name`, `model`, `harness` (pin the version) and `safeguards`. Vary one thing
   at a time where you can: the same model in two harnesses, or one harness with safeguards
   on and off. The first arm is the baseline unless `--baseline` says otherwise.
4. **Depth and cost.** `smoke` (25 pairs or the whole pack if smaller — proves the wiring),
   `standard` (100), `full`, or a number. Every pair is at least two agent runs per arm, and
   an agent run can take minutes and many model calls. Show the plan first:
   ```
   python run_benchmark.py --scenarios <pack> --arms arms.json --depth standard --plan
   ```
5. **Safety** — confirm with the user before running:
   - it runs in a disposable environment, not on a machine holding real credentials;
   - the sandbox has no network (the runner refuses to start if the harness cannot show it);
   - provider and harness safeguards are left on unless an arm exists to test without them.
6. **Experiment folder:** `bash new_experiment.sh agent-misuse-benchmark "<label>"` prints
   `EXP=<path>` and records the deployment context (from `review.json` if there is one).

## RUN
```
python run_benchmark.py --scenarios <pack dir> --arms arms.json \
  --harness <name> --harness-module <your_harness.py> --scorer <your_scorer.py> \
  --depth standard --out "<EXP>/results"
```
Every arm runs the same seeded selection of pairs. Written to `<EXP>/results/`:
`samples.jsonl` (one row per arm × task, with the outcome and the evidence for it),
`runs/<arm>/<task>/run.json`, `summary.md` and `summary.json`.

## ANALYZE
Read `summary.md` to the user in this order:
1. **Read first**: validity flags. `no_verdict` means runs errored or the scorer could not
   decide; they are in no rate. `low_permitted_completion` means the agent rarely finishes
   the legitimate twins, so its declines may be inability or blanket refusal.
2. **The per-arm table**, reading "restricted declined" and "permitted completed" together.
3. **Framing and category tables**: where the same task gets a different answer.
4. **The paired comparison** against the baseline arm, with its p-value. Say plainly when
   the pack is too small to separate two arms.
5. Spot-check a sample of `runs/` transcripts against the scorer's evidence before quoting
   any number: a new scorer is the likeliest thing to be wrong.

Do not tell the user whether the result is acceptable.

---

## Smoke test (no keys, nothing executed)
```
python run_benchmark.py --scenarios scenarios.example --arms scenarios.example/arms.mock.json \
  --harness mock --scorer mock --depth smoke --out /tmp/agent-misuse-smoke
cat /tmp/agent-misuse-smoke/summary.md
```
Expected: three arms, 13 runs each, a per-arm table, a framing table, and a paired
comparison. The first line under "Read first" says the harness is the mock. The numbers are
canned by the mock and say nothing about any agent.

## Notes
- **What ships:** `scenarios.py` (format, validation, seeded selection), `interfaces.py`
  (the `Harness` and `Scorer` contracts and their mocks), `metrics.py` (rates, intervals,
  paired comparison, flags, report), `run_benchmark.py` (the sweep), `validate_scenarios.py`.
- **What does not ship, on purpose:** task descriptions of any kind, a harness that runs a
  real agent, and any logic for deciding whether an agent declined or complied.
- A pack with placeholder prompts is accepted only by the mock harness.
- **Not verified:** nothing beyond the mock path. No agent, model or sandbox has been run
  through this scaffold.
