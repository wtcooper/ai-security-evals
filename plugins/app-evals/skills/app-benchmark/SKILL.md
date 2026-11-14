---
name: app-benchmark
description: >-
  Fast static security benchmark for an LLM app: runs a bundled, license-clean
  adversarial corpus (prompt injection, harmful, data leakage, over-refusal +
  M2S multi-turn) through promptfoo eval and reports F1 / recall / FPR / ASR by
  technique. Use to benchmark defenses, compare models/versions, or A/B/C a
  param-based guardrail. For live multi-turn attacks use app-redteam; for a
  guardrail API alone use control-isolate.
license: MIT
compatibility: "Requires python>=3.11, node>=18."
---

# app-benchmark — static security benchmark (promptfoo)

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
- **Depth:** `smoke` (`--filter-sample 30` — proves the wiring; the interval on recall is
  about ±15 points), `standard` (`--filter-sample 150`), or `full` (omit the flag). Each case
  is one call to the target and one to the judge: tell the user the totals before running.
- **Scope:** the whole corpus, or a **category slice** for a focused audience — e.g. a cyber team:
  `--filter-metadata category=cyber` (also `prompt_injection`, `data_leakage`).
- Combine them (`--filter-metadata category=cyber --filter-sample 60`).
Ask the user which axes they care about; cyber/security teams usually want
cyber + injection + data_leakage, app teams the full spread.

### 5. (Optional) A/B/C a control
If the app toggles a guardrail by a body param, duplicate `providers[0]` with a second
`label` and set that param in its `body` — promptfoo runs every case against both and
the report compares them per case.

### 6. Open an experiment folder (captures this run)
If a `review.json` exists (from `review-scope`), the deployment context is recorded with the
results; otherwise note the surface and system prompt in the manifest. Propose a short
legible label (target + scope, e.g. `acme-prod-cyber-smoke`), confirm it with the user, then:
```
bash new_experiment.sh app-benchmark "<label>"
```
It prints `EXP=<path>` under `.evals/app-benchmark/<label>_<date>/` and snapshots your config
+ redacted `.env`. Use that `<EXP>` path in RUN/ANALYZE below.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output "<EXP>/results/results.json"   # add --filter-sample N / --filter-metadata category=cyber
```
Then record what was run in `<EXP>/manifest.json` (the exact command + corpus filter).
Stream progress. **If everything errors**, stop and diagnose before continuing —
usually (a) wrong body schema, (b) auth, (c) judge URL not a chat-completions
endpoint, or (d) the target returns a non-2xx the transform treats as operational
(check one transcript with `npx promptfoo view`).

---

## ANALYZE
```
python lib/summarize.py "<EXP>/results/results.json" --json "<EXP>/summary.json" | tee "<EXP>/summary.md"
node lib/extract_transcript.js "<EXP>/results/results.json" > "<EXP>/transcripts/transcript.jsonl"
```
Present a short plain-text report and interpret it for the user:
- **Headline:** Recall (block rate on attacks), FPR (over-refusal on benign) and ASR, each
  with its 95% interval, then F1. Do not say whether the result is acceptable.
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
- Point the user to the experiment folder `<EXP>/` — `summary.md` (headline),
  `transcripts/transcript.jsonl` (per-case prompt/response/verdict), and
  `results/results.json` (full native output) — plus `npx promptfoo view` to spot-check.

End by offering next steps: a deeper run for a firmer number, add their own custom
prompts to the corpus, or move to `app-redteam` for adaptive attacks.

## Smoke test (no keys)
The bundled mock server plays a target that refuses everything and a judge that passes it:
```
python tests/mock_server.py 8725 &
TARGET_URL=http://127.0.0.1:8725/target TARGET_API_KEY=x TARGET_MODEL=mock \
JUDGE_BASE_URL=http://127.0.0.1:8725/v1 JUDGE_API_KEY=x JUDGE_MODEL=mock \
  npx promptfoo eval -c promptfooconfig.yaml --filter-sample 20 --output /tmp/ab-smoke.json
python lib/summarize.py /tmp/ab-smoke.json
```
Expected: 20 cases, `errors excluded: 0`, and a `95% intervals` line. The scores themselves
mean nothing (the mock judge passes every case); the test proves the request, transform,
grading and summary path.

## Notes
- Execution tier **T0**. The arm that varies is the target (or one guardrail parameter, in
  the optional two-arm run); the corpus and judge are held fixed.
- **Not verified:** no run against a real application or judge was possible where this was
  last changed; the path was exercised end to end against the mock server.
- The bundled corpus is license-clean (AdvBench/CyberSecEval/XSTest/PromptInject MIT/
  CC-BY + SafeMTData MIT for the M2S `safemt-m2s-*` multi-turn cases) — redistributable.
- At a small sample the interval on Recall is wide; read the interval before calling a gap
  between two runs real.
- The corpus ships prebuilt; extend it by adding cases to `corpus/*.json` (or
  appending your own test prompts in the same shape).
