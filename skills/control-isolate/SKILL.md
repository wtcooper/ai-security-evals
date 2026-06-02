---
name: control-isolate
description: >-
  Characterize a guardrail / classifier API in isolation (no model in the loop):
  sends a bundled labeled corpus (harmful vs benign + M2S multi-turn) straight to
  the guardrail and grades its verdict, reporting F1 / precision / recall / FPR by
  technique. Vendor-agnostic: maps any HTTP status or JSON verdict to a normalized
  block signal. Use to measure catch vs over-block rate or compare guardrail
  vendors (Bedrock/Prisma/Lakera/Azure). For end-to-end app testing use app-eval;
  for control effect inside a benchmark use control-bench.
disable-model-invocation: true
user-invocable: true
argument-hint: "[smoke|mid|full]"
dependencies:
  - python>=3.11
  - node>=18
allowed-tools:
  - bash
---

# control-isolate — direct guardrail classification (promptfoo)

You are running this skill **on behalf of a user** who wants to measure a guardrail's
classification quality by itself. Drive **Plan → Run → Analyze**: profile the
guardrail endpoint, map its verdict, build the labeled corpus, run, then report F1.
No LLM judge is involved — the metric is the control's own verdict. Use
`AskUserQuestion` for choices.

---

## PLAN

### 1. Preflight
`bash install_dependencies.sh` (installs promptfoo locally). Confirm python + node.

### 2. Profile the guardrail — ask, then write the config
Gather:
- **Endpoint URL** + **auth** (the guardrail/scan/classify route — NOT a model).
- **Request schema** — where the candidate text goes (`{messages:[…]}`, `{input:…}`,
  `{text:…}`, `{prompt:…}`). Edit `promptfooconfig.yaml` `providers[0].config.body`
  accordingly, keeping `{{prompt}}` for the candidate.
- **Verdict shape** — how a block is signaled. The adapter
  `adapters/generic_guardrail.js` already recognizes `action:block`, `blocked:true`,
  `flagged:true`, `is_malicious:true`, and a `400` status. If the vendor differs,
  set in `.env`: `GUARDRAIL_BLOCK_STATUSES` (e.g. `400,446`) and/or
  `GUARDRAIL_BLOCK_FIELD` + `GUARDRAIL_BLOCK_VALUE` (dotted path). Confirm with one
  curl of a known-bad and known-good input before spending a full run.
- **Channel:** is this the **input** guardrail or the **output** guardrail? (Affects
  which route you point at; run them as separate experiments to compare.)

`cp env.example .env`; fill `GUARDRAIL_URL`, `GUARDRAIL_API_KEY`, and any block-signal
overrides. Validate: `npx promptfoo validate -c promptfooconfig.yaml`.

### 3. Choose how much of the corpus to run (`AskUserQuestion`)
The labeled corpus is **bundled** in `corpus/` (guardrail-assertion variant: harmful →
`not-guardrails`/pass-when-blocked, benign → `guardrails`/pass-when-allowed). Pick a
run-time sample (add `--filter-sample N` in RUN): smoke `30` / mid `150` / full (omit).

### 4. (Optional) Vendor comparison
To compare guardrail vendors, plan one run per vendor (separate `.env` / `GUARDRAIL_URL`)
and diff the F1 / FPR tables in Analyze.

### 5. Open an experiment folder (captures this run)
Propose a short legible label (guardrail + scope, e.g. `prisma-airs-pi-smoke`), confirm
it, then `bash new_experiment.sh control-isolate "<label>"`. It prints `EXP=<path>` under
`.evals/control-isolate/<label>_<date>/` and snapshots the config + redacted `.env`. Use
that `<EXP>` path below.

---

## RUN
```
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output "<EXP>/results/results.json"
```
Record the command + corpus filter in `<EXP>/manifest.json`. If everything errors,
recheck the request schema and the block-signal mapping with a manual curl (the adapter
only flags what it can recognize).

---

## ANALYZE
```
python lib/summarize.py "<EXP>/results/results.json" | tee "<EXP>/summary.txt"
node lib/extract_transcript.js "<EXP>/results/results.json" > "<EXP>/transcripts/transcript.jsonl"
```
Present and interpret:
- **F1 / precision / recall / FPR.** Recall = catch rate on attacks; FPR = over-block
  rate on benign (the cost). A guardrail that blocks everything has high recall but
  terrible FPR/F1.
- **Per-status histogram + warnings.** Shows how the guardrail's responses were bucketed.
  An `unmapped` / `AMBIGUOUS` warning means a non-2xx had no recognizable block/error
  signal and was excluded — if it's actually a block, map it via `GUARDRAIL_BLOCK_STATUSES`
  or `GUARDRAIL_BLOCK_FIELD`/`VALUE` and re-run, so you don't undercount the guardrail.
- **`by_technique_family`.** Call out blind spots — e.g. "catches `direct_harmful`
  0.9 but `m2s_*` flattened multi-turn 0.2" or "misses `system_prompt_exfiltration`".
- For input-vs-output runs or vendor comparisons, put the F1/FPR numbers side by side
  and state the tradeoff (catch rate vs over-block).
- Point to `<EXP>/` — `summary.txt`, `transcripts/transcript.jsonl`, and
  `results/results.json` — plus `npx promptfoo view` for per-case verdicts.

End by offering: test the other channel (input vs output), compare another vendor, or
bump the tier.

## Notes
- This measures the classifier, not end-to-end app risk (use control-bench for that).
- AWS Bedrock: use the `ApplyGuardrail` API (assesses text with no model call). Azure
  Content Safety: map `categoriesAnalysis` severities to a block.
- M2S `safemt-m2s-*` cases come from SafeMTData (MIT) — bundled and redistributable.

