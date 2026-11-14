---
name: guardrail-benchmark
description: >-
  Measure how well a guardrail works, two ways. DIRECT mode sends a bundled labelled
  corpus (harmful vs benign, plus flattened multi-turn) straight to the guardrail or
  classifier API, with no model in the loop, and scores its own verdict: catch rate
  against false-block rate, by technique. IN-LINE mode runs standard Inspect benchmarks
  with the same model behind each guardrail arm and reports the risk each guardrail
  removes beside what it costs in over-blocking, paired on the same samples. Use to
  characterise one guardrail, compare vendors, or show the effect of enabling one. The
  guardrail is supplied by the user. For an app endpoint use app-benchmark; for comparing
  models use model-benchmark.
license: MIT
compatibility: "Direct mode requires python>=3.11 and node>=18 (promptfoo). In-line mode requires Python 3.11+ and a separate virtual environment with inspect_ai, inspect_evals and openai."
---

# guardrail-benchmark — how good is this guardrail?

You are running this skill **on behalf of a user** who wants evidence about a guardrail
they already have or are considering: a vendor guardrail API, a classifier or guardrail
model, or a guardrail configured on their model gateway. Drive **Plan → Run → Analyze**.

The arm that varies is the **guardrail**; the corpus or benchmark, and in in-line mode the
model, are held fixed. This skill measures. It ships no guardrail and does not say whether
a result is acceptable. Execution tier: **T0/T1**. Use `AskUserQuestion` for choices.

| Mode | Question it answers | Engine | Judge |
|---|---|---|---|
| **Direct** | Given harmful and benign text, what does the guardrail catch and what does it wrongly block? | promptfoo | none: the guardrail's own verdict is scored |
| **In-line** | With this guardrail in front of our model, how much does risk drop inside a real benchmark, and how much legitimate work gets blocked? | Inspect | only for judged benchmarks |

Run direct mode to characterise or compare guardrails cheaply. Run in-line mode when the
question is the effect on a deployed model, including injected tool output during agent
tool calls, which direct mode cannot see.

---

## PLAN

### 1. Choose the mode, and record the context (`AskUserQuestion`)
Ask which question above the user has. If a `review.json` exists it is recorded with the
results; otherwise note where the guardrail sits (input, output, tool results) in the
manifest.

### 2a. Direct mode — profile the guardrail
`bash install_dependencies.sh` (installs promptfoo locally). Then gather:
- **Endpoint URL** + **auth** (the scan/classify route — not a model).
- **Request schema** — where the candidate text goes (`{messages:[…]}`, `{input:…}`,
  `{text:…}`, `{prompt:…}`). Edit `promptfooconfig.yaml` `providers[0].config.body`,
  keeping `{{prompt}}` for the candidate.
- **Verdict shape** — how a block is signalled. `adapters/generic_guardrail.js` already
  recognises `action:block`, `blocked:true`, `flagged:true`, `is_malicious:true` and a
  `400` status. If the vendor differs, set `GUARDRAIL_BLOCK_STATUSES` (e.g. `400,446`)
  and/or `GUARDRAIL_BLOCK_FIELD` + `GUARDRAIL_BLOCK_VALUE` (dotted path) in `.env`.
  Confirm with one curl of a known-bad and a known-good input before a full run.
- **Channel:** input or output guardrail? Run them as separate experiments.

`cp env.example .env`; fill `GUARDRAIL_URL`, `GUARDRAIL_API_KEY` and any overrides.
Validate: `npx promptfoo validate -c promptfooconfig.yaml`.

**Depth** (the labelled corpus is bundled in `corpus/`, about 2,900 cases): `smoke`
(`--filter-sample 30`), `standard` (`--filter-sample 150`), or `full` (omit the flag).
One request per case, no model calls. For a vendor comparison plan one run per vendor
with the same depth.

### 2b. In-line mode — profile the gateway
```
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai openai 'inspect_evals[agentdojo,cyberseceval_4]'
```
Gather:
- **Gateway base URL + key** — the OpenAI-compatible gateway that applies guardrails.
- **Connector:** `litellm` (guardrail param = top-level `guardrails:[name]`, the default)
  or `openai` (configurable field, the base for other gateways).
- **Model under test** — the same model on every arm.
- **Guardrail names**, exactly as registered in the gateway.
- **Judge model** on the same gateway, if a judged benchmark is selected. It is called
  directly, never through a guardrail, and must not be the model under test.

Write `arms.json`: a baseline with no guardrail, then one entry per guardrail:
```json
[{"name": "baseline"},
 {"name": "vendor-a", "guardrails": ["vendor-a-prompt-injection"]}]
```
**Confirm the guardrail fires before spending a run:** curl the gateway with a known-bad
prompt, once without and once with the `guardrails` param. If the guarded call does not
block (refusal or 4xx), the name or gateway config is wrong.

**Checks** (`--checks`): the `guardrail` profile is `cyse4_mitre` (direct misuse),
`cyse4_mitre_frr` (benign security questions refused — the over-block cost),
`cyse4_multilingual_prompt_injection` and `agentdojo` (injected tool output). Any check id
from `lib/inspect_suite.py` works. **Depth:** `smoke` (25 — wiring only), `standard`
(100), `full`, or a number. Show the cost first:
```
python run_inline.py --arms arms.json --checks guardrail --depth standard --plan
```

### 3. Open an experiment folder
`bash new_experiment.sh guardrail-benchmark "<label>" <promptfoo|inspect>` — e.g.
`vendor-a-direct-smoke` or `vendor-a-vs-baseline-agentdojo`. It prints `EXP=<path>` and
snapshots the config, `arms.json` and a redacted `.env`.

---

## RUN

### Direct mode
```
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --filter-sample 150 \
  --output "<EXP>/results/results.json"
```
If everything errors, recheck the request schema and the block-signal mapping with a
manual curl: the adapter only flags what it can recognise.

### In-line mode
```
SHIM_GATEWAY_URL=<gateway-url> SHIM_GATEWAY_KEY=<key> SHIM_CONNECTOR=litellm \
.venv-inspect/bin/python run_inline.py --arms arms.json --model <model> --judge <judge> \
  --checks guardrail --depth standard --out "<EXP>/results"
```
`run_inline.py` starts one injection shim per arm, which adds that arm's guardrail to every
request and turns a guardrail block (HTTP 400/403 with a block body) into a refusal the
benchmark can score instead of an aborted run. Every arm runs the same seeded samples.
Written to `<EXP>/results/`: `results.json`, `samples.jsonl` and `logs/`.

Record the exact command in `<EXP>/manifest.json` in both modes.

---

## ANALYZE

### Direct mode
```
python lib/summarize.py "<EXP>/results/results.json" --json "<EXP>/summary.json" \
  | tee "<EXP>/summary.md"
node lib/extract_transcript.js "<EXP>/results/results.json" > "<EXP>/transcripts/transcript.jsonl"
```
Present:
- **Recall** (catch rate on attacks) and **FPR** (benign wrongly blocked), each with its
  95% interval, then precision and F1. A guardrail that blocks everything has high recall
  and a high FPR; always report the two together.
- **The status histogram and warnings.** An `AMBIGUOUS` warning means a non-2xx had no
  recognisable block or error signal and was excluded. If it is really a block, map it and
  re-run, or the guardrail is undercounted.
- **`by_technique_family` and `by_category`.** Name the blind spots, and flag families
  with small n as low-confidence.
- For input-vs-output or vendor comparisons, put the tables side by side.

### In-line mode
```
python report.py "<EXP>/results/results.json" --baseline baseline \
  --json "<EXP>/summary.json" | tee "<EXP>/summary.md"
```
Present, in this order:
1. **The "Read first" section** — errors and validity flags (`judge_unresolved`,
   `low_utility` on `agentdojo`). A flag does not remove the number.
2. **Risk removed:** the attack benchmarks, baseline against each guardrail, with the
   paired change on the same samples.
3. **What it cost:** `cyse4_mitre_frr` (benign questions now refused) and, for
   `agentdojo`, the companion utility metric. A guardrail that lowers attack success by
   blocking legitimate work shows up here. Report both sides together, never the risk
   number alone.

Do not tell the user whether the trade-off is acceptable; that is theirs to decide.

End by offering: the other mode, the other channel (input vs output), another vendor, or a
deeper run on what was too close to call.

---

## Smoke test (no keys)

**Direct mode** — the mock guardrail blocks on a few words:
```
python tests/mock_server.py 8723 &
GUARDRAIL_URL=http://127.0.0.1:8723/guardrail GUARDRAIL_API_KEY=x \
  npx promptfoo eval -c promptfooconfig.yaml --filter-sample 40 --output /tmp/gb-direct.json
python lib/summarize.py /tmp/gb-direct.json
```
Expected: 40 cases, 0 errors, a low recall and FPR 0 (the mock only knows a few words).

**In-line mode** — the mock gateway blocks broadly when a guardrail is requested:
```
python tests/mock_gateway.py 8724 &
printf '[{"name":"baseline"},{"name":"mock-guard","guardrails":["mock-guard"]}]' > /tmp/arms.json
SHIM_GATEWAY_URL=http://127.0.0.1:8724 .venv-inspect/bin/python run_inline.py \
  --arms /tmp/arms.json --model mock-model --checks cyse4_mitre_frr --depth 20 --out /tmp/gb-inline
python report.py /tmp/gb-inline/results.json --baseline baseline
```
Expected: `baseline` refuses nothing; `mock-guard` refuses a share of the benign questions,
and the paired table shows the guarded arm worse on those samples. That is the over-block
cost made visible.

## Notes
- Direct mode measures the classifier, not end-to-end risk; in-line mode measures the
  effect on one model and one benchmark. Neither is the whole picture alone.
- The shim converts a block to a refusal by default (`GUARDRAIL_BLOCK_STATUSES` for other
  block codes; `SHIM_BLOCK_AS_REFUSAL=false` to pass blocks through). Operational errors
  are passed through and surface as errors.
- In-line mode strips provider API keys before running, so a benchmark whose judge was not
  routed fails instead of calling a provider nobody chose.
- AWS Bedrock: use the `ApplyGuardrail` API in direct mode. Azure Content Safety: map
  `categoriesAnalysis` severities to a block.
- The bundled corpus is licence-clean (see `corpus/` manifest); the flattened multi-turn
  cases come from SafeMTData (MIT).
- **Not verified:** no run against a real guardrail vendor or gateway was possible where
  this was built. Both modes were exercised end to end against the bundled mocks.
