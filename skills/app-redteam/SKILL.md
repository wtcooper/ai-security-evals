---
name: app-redteam
description: >-
  Adaptive live red team of an LLM app via promptfoo's attack engine: genuine
  multi-turn attacks (crescendo, jailbreak:tree) that read the target's real
  responses and adapt on refusals, seeded by a bundled cross-domain objective
  pack. Use to actively find vulnerabilities or stress-test multi-turn robustness.
  For a fast reproducible benchmark use app-eval; for a guardrail in isolation use
  control-isolate.
disable-model-invocation: true
user-invocable: true
dependencies:
  - node>=18
allowed-tools:
  - bash
---

# app-redteam — adaptive red team (promptfoo)

You are running this skill **on behalf of a user** who wants to actively red-team
their LLM application. Drive **Plan → Run → Analyze**: gather the target + attacker/
grader models, write the config, run the live attack, then summarize the
vulnerabilities. Use `AskUserQuestion` for choices. This makes **real adversarial
calls** to the target — confirm the user is authorized before running.

---

## PLAN

### 1. Preflight
`bash install_dependencies.sh` (installs promptfoo locally, sets air-gap env). Confirm node.

### 2. Profile the target — ask, then write the config
Gather (the user may paste a `curl`):
- **Endpoint URL**, **method**, **auth** header.
- **Request body shape.** This skill sends a running conversation — the body uses
  `messages: "{{ messages }}"`. Adjust `targets[0].config.body` if the app expects a
  different envelope, keeping `{{ messages }}` where the conversation array goes.
- **Statefulness:** does the app accept the full `messages[]` each call
  (`stateful: false`, promptfoo owns history), or persist a server-side session
  (`stateful: true`, then wire `sessionParser` / `{{sessionId}}`)? Ask and set it on
  each strategy.

Then `cp env.example .env`; fill `TARGET_URL`, `TARGET_API_KEY`, and edit
`promptfooconfig.yaml` `targets[0].config` to match the app.

### 3. Choose attacker + grader models
Both are OpenAI-compatible — point them at the user's **production LiteLLM** (or any
gateway). Ask for and set in `.env`:
- **Attacker:** `ATTACKER_MODEL` / `ATTACKER_BASE_URL` / `ATTACKER_API_KEY` (a capable
  instruct model attacks best).
- **Grader:** `GRADER_MODEL` / `GRADER_BASE_URL` / `GRADER_API_KEY`. **Keep it a
  different model from the target** — warn if they match.

### 4. Choose the attack plan (`AskUserQuestion`)

**What to probe.** The config already points the local `intent` plugin at the bundled
objective pack (`objectives/redteam_objectives.json`, ~73 goals across cyber /
prompt_injection / data_leakage / content_safety); the strategies escalate toward each.
This is the air-gapped default — promptfoo's built-in plugins are remote-only or fetch
datasets at run time (the config comment explains why). One limit to note to the user:
`intent` goals can't replicate the *structural* plugins (`bfla`/`bola`/`ssrf`/`mcp`/RAG),
which need the app's own tools.

**Strategies** — with remote generation disabled, these run on your `redteam.provider`:
- **Local-capable:** `crescendo` (default), `jailbreak:tree`, `custom`, classic iterative
  `jailbreak` (pin `iterative`), `basic`, `prompt-injection`.
- **Remote-only (throw air-gapped):** `goat`, `mischievous-user`, plain `jailbreak` (→`jailbreak:meta`).

**Scope.** ~73 objectives × multi-turn is a big run. First pass: point `intent` at
`objectives/redteam_objectives.smoke.json` (2 goals) or set `numTests` low + `maxTurns: 3`.
Filter to one audience (e.g. cyber) via the category tags in
`objectives/redteam_objectives.manifest.json`.

Edit the `redteam:` block to reflect their choices, then validate:
`npx promptfoo validate -c promptfooconfig.yaml`.

### 5. Open an experiment folder (captures this run)
Propose a short legible label (target + attack, e.g. `acme-prod-crescendo`), confirm it,
then `bash new_experiment.sh app-redteam "<label>"`. It prints `EXP=<path>` under
`.evals/app-redteam/<label>_<date>/` and snapshots the config + objective pack +
redacted `.env`. Use that `<EXP>` path below.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo redteam run -c promptfooconfig.yaml -d "<label>" \
  --output "<EXP>/inputs/generated_probes.yaml"
npx promptfoo export eval latest -o "<EXP>/results/redteam.results.json"   # results + transcripts
```
`redteam run`'s `--output` saves the generated attack probes; `export eval latest`
writes the run's results (with multi-turn transcripts) into the experiment. Record the
command + choices in `<EXP>/manifest.json`.
This is slow and adaptive (the attacker model drives many turns). Narrate that it's
running live attacks. Note: under `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`, the
local-capable strategies (crescendo/custom/jailbreak:tree/basic) run on your attacker
model; the remote-only ones (goat/mischievous-user/plain jailbreak) error with
"requires remote generation" — that's expected, switch to crescendo/custom or enable
the hosted service.

---

## ANALYZE
```
node lib/extract_transcript.js "<EXP>/results/redteam.results.json" > "<EXP>/transcripts/transcript.jsonl"
npx promptfoo redteam report     # opens the vulnerability report UI
```
Summarize for the user in plain text:
- Which **plugins/strategies succeeded** (got the target to comply) and example
  transcripts — especially any **multi-turn** success (crescendo/GOAT), since those
  reveal escalation weaknesses a static benchmark misses.
- Where the target held (refused/blocked) across turns.
- **State the caveat plainly: ASR is noisy.** A single run is a sample. For any number
  you'll report or act on, **run repeated trials and report the variance** — don't
  treat one run's success rate as the truth.
- Point to `<EXP>/` — `transcripts/transcript.jsonl` (turn-by-turn), `results/` (native),
  and the report UI.

End by offering: a deeper run (more turns/plugins), a focused run on the one strategy
that worked, or `app-eval` for a fast reproducible regression number.

## Notes
- Only run against apps the user is authorized to test; prompts will appear in the
  target's logs.
- Multi-turn strategies require the attacker model configured (air-gap: no hosted
  generation).
