---
name: control-bench
description: >-
  Measure the risk reduction from enabling a security control inside any Inspect
  benchmark (AgentDojo for indirect prompt injection during tool calling,
  CyberSecEval MITRE/FRR, or any inspect_evals task): a param-injection shim adds a
  guardrail per arm at the model boundary and Inspect runs the A/B/C sweep natively,
  comparing scores. Vendor-agnostic gateway connectors (litellm first). For a
  guardrail in isolation use control-isolate; for an app benchmark use app-eval.
disable-model-invocation: true
user-invocable: true
allowed-tools:
  - bash
---

# control-bench — A/B/C control effectiveness inside Inspect benchmarks

You are running this skill **on behalf of a user** who wants to know whether enabling
a security control (a guardrail on their gateway) measurably reduces risk inside a
realistic benchmark. Drive **Plan → Run → Analyze**. Inspect runs the sweep, scoring,
and comparison natively; the only custom piece is the **injection shim** that adds the
per-arm guardrail param at the model boundary (Inspect has no per-request body hook).
Use `AskUserQuestion` for choices.

---

## PLAN

### 1. Preflight — Inspect in its own venv
`inspect_ai`/`inspect_evals` **conflict with `litellm[proxy]`**, so install them in a
separate env (control-bench talks to the gateway over HTTP — they never share a venv):
```
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai 'inspect_evals[agentdojo]'
# add 'inspect_evals[cyberseceval_4]' for cyse4_mitre / cyse4_mitre_frr
```

### 2. Profile the gateway — ask
- **Gateway base URL + key** (the OpenAI-compatible gateway that applies guardrails —
  e.g. their LiteLLM, Netskope).
- **Connector:** `litellm` (guardrail param = top-level `guardrails:[name]`) or
  `openai` (configurable field, base for Netskope/others). Default `litellm`.
- **Model under test** — the SAME model on every arm (only the guardrail differs).
- **Guardrail names** to compare, exactly as registered in the gateway.

### 3. Write the arms and confirm the control actually fires
Write `arms.json`: baseline + one entry per control, e.g.
```json
[{"name":"baseline"},
 {"name":"prisma","guardrails":["prisma-airs-pi"]}]
```
**Sanity-check before a full run:** curl the gateway directly with a known-bad prompt,
once without and once with the `guardrails` param, and confirm the guarded call blocks
(refusal or 4xx). If it doesn't, the guardrail name or gateway config is wrong — fix
before proceeding.

### 4. Choose the benchmark(s) (`AskUserQuestion`)
Any `inspect_evals` task works; priority ones:
- **`inspect_evals/agentdojo`** — agent tool-calling with **indirect prompt injection**
  in tool results. Best for "does the guardrail catch injected tool content". Metrics:
  targeted attack-success + utility.
- **`inspect_evals/cyse4_mitre`** — cyber-attack assistance; pair with
  **`cyse4_mitre_frr`** to capture the over-block cost.
- Others: `cyse2_prompt_injection`, `cyse2_interpreter_abuse`, …
Pick task(s) + a `--limit` for a first pass (keep it small; agentdojo runs many calls).

---

## RUN

### 1. Launch one shim per arm
```
SHIM_GATEWAY_URL=<gateway-url> SHIM_GATEWAY_KEY=<key> SHIM_CONNECTOR=litellm \
  python injection_shim.py --arms arms.json --base-port 8901
```
It prints the env vars and the exact `--model` string to use. The shim also converts a
guardrail block (HTTP 400) into a 200 refusal so blocks **score** instead of aborting
the run.

### 2. Run the sweep (Inspect does A/B/C natively)
Export the printed `*_BASE_URL` / `*_API_KEY` vars, set `MODEL`, then run the chosen
task once across all arms (using the `.venv-inspect` python/inspect):
```
.venv-inspect/bin/inspect eval inspect_evals/agentdojo \
  --model "openai-api/baseline/$MODEL,openai-api/prisma/$MODEL" --limit 50
```
Swap the task name for any other inspect_evals task — no skill changes.

---

## ANALYZE
Compare arms with `inspect view`, or pull scores in Python (find scorer names first
with `inspect log dump file://<log>.eval | jq '.results.scores[].name'`):
```
.venv-inspect/bin/python - <<'PY'
from inspect_ai.log import list_eval_logs, read_eval_log
for p in list_eval_logs("./logs"):
    log = read_eval_log(p)
    print(log.eval.model, {s.name: s.metrics for s in (log.results.scores or [])})
PY
```
Present for the user:
- **Risk reduction:** the attack-success / targeted-ASR scorer, baseline vs each
  control (down = the control helped). State the delta.
- **Over-block cost:** the utility scorer (AgentDojo) or `cyse4_mitre_frr` — a control
  that drops attacks but craters utility / spikes FRR is over-blocking; report both
  numbers together, not just the risk number.
- Note any arm with sample errors (`log.status`) — a misconfigured arm isn't a result.

End by offering: add another control arm, run the FRR companion, or scale `--limit` up
for a firmer number.

## Notes
- Same model on every arm; only the guardrail differs.
- The shim converts HTTP 400 → 200 refusal by default (`GUARDRAIL_BLOCK_STATUSES` for
  other block codes; `SHIM_BLOCK_AS_REFUSAL=false` to pass blocks through).
- AgentDojo's enhanced attacks (beyond `important_instructions`) are not bundled.
