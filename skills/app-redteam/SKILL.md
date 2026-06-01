---
name: app-redteam
description: >-
  Adaptive, customized red teaming of an LLM application using promptfoo's live
  attack engine — genuine multi-turn attacks (crescendo, GOAT, mischievous-user)
  where the attacker reads the target's REAL responses each turn and backtracks on
  refusals, plus jailbreak and prompt-injection strategies. Use when someone wants
  to actively discover vulnerabilities, run a real (not static) red team, customize
  attack objectives, or stress-test multi-turn robustness. Triggers: "red team our
  app", "adaptive jailbreak", "multi-turn attack", "crescendo / GOAT", "find
  vulnerabilities". For a fast reproducible benchmark use app-eval; for a guardrail
  in isolation use control-isolate.
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
`bash ../app-eval/install_dependencies.sh` (or any promptfoo install). Confirm node.

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

**What to probe — bring our own objectives (the default).** The config ships with the
`intent` plugin pointed at a bundled, license-clean **objective pack**
(`objectives/redteam_objectives.json`, ~73 goals) spanning all four attack categories
— **cyber / prompt_injection / data_leakage / content_safety**. The local multi-turn
strategies escalate toward each objective using *your* attacker model. This is the
default because **promptfoo's built-in plugins don't survive an air gap**:

| plugin class | examples | local-only run |
|---|---|---|
| **Remote-only** (need Promptfoo Cloud) | `harmful:*` synthesis, `ascii-smuggling`, `data-exfil`, `indirect-prompt-injection`, `system-prompt-override`, `bfla`/`bola`/`ssrf`, `mcp`, RAG/agentic, vertical packs | **throws** |
| **Dataset** (fetch at run time) | `harmbench`, `beavertails`, `pliny`, `cyberseceval`, `xstest` | hits HuggingFace/GitHub — **not air-gapped, not license-pinned** |
| **Config-required (BYO)** | **`intent`**, `policy` | **fully local** ✅ |

So we drive everything through `intent` + our pack. (`intent` objectives express
harmful/cyber/injection/leakage *goals*; they can't replicate the *structural* plugins
— `bfla`/`bola`/`ssrf`/`mcp`/RAG — which need the app's tools. Note that limit to the user.)

**How (strategies).** With remote generation disabled they run on your `redteam.provider`:
  - **Local-capable** (air-gapped): `crescendo` (adaptive multi-turn, the default),
    `jailbreak:tree`, `custom` (natural-language multi-turn playbook), classic iterative
    `jailbreak` (pin the `iterative` provider), `basic`, `prompt-injection`.
  - **Remote-only** (throw under air-gap): `goat`, `mischievous-user`, plain `jailbreak`
    (aliases to `jailbreak:meta`).

**Scope/size.** ~73 objectives × multi-turn strategies is a big run. For a **first pass**,
point `intent` at `objectives/redteam_objectives.smoke.json` (2 objectives) or set
`numTests` low and `maxTurns: 3`; expand once wiring is confirmed. To focus on one
audience (e.g. a cyber team), hand-filter the pack to the `cyber` entries — the
`objectives/redteam_objectives.manifest.json` sidecar tags every objective by category.

Edit the `redteam:` block to reflect their choices. Validate:
`npx promptfoo validate -c promptfooconfig.yaml`.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo redteam run -c promptfooconfig.yaml
```
This is slow and adaptive (the attacker model drives many turns). Narrate that it's
running live attacks. Note: under `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`, the
local-capable strategies (crescendo/custom/jailbreak:tree/basic) run on your attacker
model; the remote-only ones (goat/mischievous-user/plain jailbreak) error with
"requires remote generation" — that's expected, switch to crescendo/custom or enable
the hosted service.

---

## ANALYZE
```
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

End by offering: a deeper run (more turns/plugins), a focused run on the one strategy
that worked, or `app-eval` for a fast reproducible regression number.

## Notes
- Only run against apps the user is authorized to test; prompts will appear in the
  target's logs.
- Multi-turn strategies require the attacker model configured (air-gap: no hosted
  generation).
