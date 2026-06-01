---
name: app-eval
description: >-
  Fast static security benchmark for an LLM application. Runs a bundled,
  license-clean adversarial corpus (prompt injection, harmful content, data
  leakage, over-refusal) plus M2S-flattened multi-turn jailbreaks through
  promptfoo eval, then reports F1 / recall / FPR / ASR with a per-technique
  breakdown. Use to benchmark an app or chatbot's defenses quickly, compare
  models or app versions, or A/B/C a param-based guardrail (control on vs off) —
  without a live red-team engine. Triggers: "benchmark our chatbot", "is our app
  safe", "injection/jailbreak benchmark", "F1 / FRR / recall", "compare guardrail
  configs". For adaptive multi-turn attacks use app-redteam; to test a guardrail
  API in isolation use control-isolate.
disable-model-invocation: true
user-invocable: true
argument-hint: "[smoke|mid|full]"
dependencies:
  - python>=3.11
  - node>=18
allowed-tools:
  - bash
---

# app-eval — static security benchmark (promptfoo)

You are running this skill **on behalf of a user** who wants to benchmark their LLM
application against a standard adversarial corpus. Drive the whole journey:
**Plan → Run → Analyze**. Use `AskUserQuestion` for choices, gather endpoint details
conversationally, write the config files yourself, then run and analyze. Narrate
briefly; stop and ask on anything ambiguous rather than guessing.

---

## PLAN

### 1. Preflight
From this skill's directory, run `bash install_dependencies.sh` (installs promptfoo
locally, sets air-gap env). Confirm `python` and `node` exist.

### 2. Profile the target — ask, then write the config
Gather these from the user (one or two at a time; they may paste a working `curl`):
- **Endpoint URL** and **HTTP method** (usually POST).
- **Auth** — header name + scheme (e.g. `Authorization: Bearer …`, `x-api-key: …`).
- **Request body shape** — how the user prompt is embedded. Common shapes:
  `{messages:[{role:user,content:"…"}]}`, `{input:"…"}`, `{prompt:"…"}`,
  `{query:"…"}`. Get a real example.
- **Response shape** — where the reply text lives (the shared transform already
  handles OpenAI/Anthropic/`response`/`output`/`text`/`messages[]`; only note it if
  it's unusual).
- Whether the app exposes a **param to toggle a guardrail** (for the optional A/B/C).

Then **do the setup for them**:
1. `cp env.example .env` and fill `TARGET_URL`, `TARGET_API_KEY`, and the judge vars
   (next step). `.env` is gitignored.
2. **Edit `promptfooconfig.yaml`** `providers[0].config` so `body` and `headers` match
   the app's real schema (replace the default `messages` body if needed; keep
   `{{prompt}}` where the user input goes). Leave `transformResponse` as-is.
3. Validate: `npx promptfoo validate -c promptfooconfig.yaml`.

### 3. Choose the judge
Every case is graded by an LLM judge (promptfoo `llm-rubric`) via an OpenAI-compatible
provider. Ask for the judge gateway (`JUDGE_BASE_URL` = gateway base `…/v1`,
`JUDGE_API_KEY`, `JUDGE_MODEL`).
**REQUIRED gate — do not skip:** before running, compare the judge to the target. If
`JUDGE_MODEL` is the same model as the target (or `JUDGE_BASE_URL` points at the same
model as the target), STOP and tell the user the eval would be
self-graded and invalid; have them pick a different judge model before proceeding.
A small capable model from a different family (e.g. gpt-4o-mini) is a good default.

### 4. Choose how much / which of the corpus to run (`AskUserQuestion`)
The **full corpus (~2900 cases) is bundled** in `corpus/` — no build step. It's tagged
by `category` (cyber / prompt_injection / data_leakage / content_safety). Pick:
- **Scope:** a whole-corpus sample (`--filter-sample 30|150` for smoke/mid, omit for full),
  or a **category slice** for a focused audience — e.g. a cyber team:
  `--filter-metadata category=cyber` (also `prompt_injection`, `data_leakage`).
- Combine them (`--filter-metadata category=cyber --filter-sample 60`).
Ask the user which axes they care about; cyber/security teams usually want
cyber + injection + data_leakage, app teams the full spread.

### 5. (Optional) A/B/C a control
If the app toggles a guardrail by a body param, duplicate `providers[0]` with a second
`label` and set that param in its `body` — promptfoo runs every case against both and
the report compares them per case.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output results.json   # add --filter-sample N
```
Stream progress. **If everything errors**, stop and diagnose before continuing —
usually (a) wrong body schema, (b) auth, (c) judge URL not a chat-completions
endpoint, or (d) the target returns a non-2xx the transform treats as operational
(check one transcript with `npx promptfoo view`).

---

## ANALYZE
```
python lib/summarize.py results.json
```
Present a short plain-text report and interpret it for the user:
- **Headline:** F1, Recall (block rate on attacks), FPR (over-refusal on benign), ASR.
- **Negative class matters:** benign is the negative class, so FPR is the over-block
  cost — a defense that refuses everything scores high recall but bad F1/FPR.
- **Read the per-status histogram** ("Response classes" / "HTTP statuses"). It shows
  what the target returned and how each was bucketed (answer / block / error / ambiguous).
  Any `WARNING: … AMBIGUOUS …` means a non-2xx couldn't be auto-classified and was
  judged — eyeball those and, if a status is always a block, set `GUARDRAIL_BLOCK_STATUSES`.
- **Read `by_category`** (cyber / prompt_injection / data_leakage / content_safety): call out which axis the target is weak on; for a cyber audience, lead with the cyber + injection + leakage numbers.
- **Always read `by_technique_family`.** Call out gaps overall recall hides, e.g.
  "strong on `direct_harmful` (0.95) but only 0.30 on `m2s_*` flattened multi-turn" or
  "misses `system_prompt_exfiltration`". Flag families with n < 10 as low-confidence.
- For an A/B/C run, diff the arms and state the marginal effect of the control.
- Point the user to `results.json` and `npx promptfoo view` to spot-check any judge
  decision.

End by offering next steps: bump the tier for a firmer number, add their own custom
prompts to the corpus, or move to `app-redteam` for adaptive attacks.

## Notes
- The bundled corpus is license-clean (AdvBench/CyberSecEval/XSTest/PromptInject MIT/
  CC-BY + SafeMTData MIT for the M2S `safemt-m2s-*` multi-turn cases) — redistributable.
- At a small sample the CI on Recall is wide (±~8 pts at ~30); don't call a small gap
  real — run more cases before a vendor or release decision.
- To regenerate/extend the corpus, see `tools/` (maintainer tooling).
