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
Every case is graded by an LLM judge (promptfoo `llm-rubric`). Ask for the judge
gateway (`JUDGE_URL` = full chat-completions endpoint, `JUDGE_API_KEY`, `JUDGE_MODEL`).
**REQUIRED gate — do not skip:** before running, compare the judge to the target. If
`JUDGE_MODEL` is the same model as the target (or `JUDGE_URL` is the same endpoint as
`TARGET_URL` pointing at the same model), STOP and tell the user the eval would be
self-graded and invalid; have them pick a different judge model before proceeding.
A small capable model from a different family (e.g. gpt-4o-mini) is a good default.

### 4. Choose the corpus tier (`AskUserQuestion`)
- **smoke** (~30) — wiring/cost check. Good first run.
- **mid** (~150) — routine regression.
- **full** (~2000) — comprehensive; final decisions.
Build it: `python ../_shared/build_corpus.py --tier <tier>`. It prints the
available-vs-emitted split (injection / harmful / leakage / benign).

### 5. (Optional) A/B/C a control
If the app toggles a guardrail by a body param, duplicate `providers[0]` with a second
`label` and set that param in its `body` — promptfoo runs every case against both and
the report compares them per case.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output results.json
```
Stream progress. **If everything errors**, stop and diagnose before continuing —
usually (a) wrong body schema, (b) auth, (c) judge URL not a chat-completions
endpoint, or (d) the target returns a non-2xx the transform treats as operational
(check one transcript with `npx promptfoo view`).

---

## ANALYZE
```
python ../_shared/summarize.py results.json
```
Present a short plain-text report and interpret it for the user:
- **Headline:** F1, Recall (block rate on attacks), FPR (over-refusal on benign), ASR.
- **Negative class matters:** benign is the negative class, so FPR is the over-block
  cost — a defense that refuses everything scores high recall but bad F1/FPR.
- **Always read `by_technique_family`.** Call out gaps overall recall hides, e.g.
  "strong on `direct_harmful` (0.95) but only 0.30 on `m2s_*` flattened multi-turn" or
  "misses `system_prompt_exfiltration`". Flag families with n < 10 as low-confidence.
- For an A/B/C run, diff the arms and state the marginal effect of the control.
- Point the user to `results.json` and `npx promptfoo view` to spot-check any judge
  decision.

End by offering next steps: bump the tier for a firmer number, add their own custom
prompts to the corpus, or move to `app-redteam` for adaptive attacks.

## Notes
- Don't report bundled-mock numbers as a real app's.
- M2S `mhj-m2s-*` cases derive from the research-only MHJ set — confirm authorization
  before sharing a built corpus.
- At smoke tier the CI on Recall is wide (±~8 pts); don't call a small gap real —
  push to mid/full before a vendor or release decision.
