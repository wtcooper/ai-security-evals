---
name: model-benchmark
description: >-
  Measure and COMPARE the security posture of AI models themselves — open-weights or
  frontier — when a new one is released: a fixed suite of Inspect benchmarks, one per risk
  dimension (direct misuse, over-refusal, harmful-request refusal, jailbreak uplift,
  insecure code, prompt injection via content, injection via tools, memory poisoning, and
  injection via images for vision models), run on the same seeded samples for every
  model. Reports each rate with a confidence interval and a paired comparison between
  models. For a guardrail's effect use guardrail-benchmark; for an app endpoint use
  app-benchmark.
license: MIT
compatibility: "Requires Python 3.11+ and a separate virtual environment with inspect_ai, inspect_evals and openai."
---

# model-benchmark — security benchmarks for a model release

You are running this skill **on behalf of a user** who needs to know how a model (or
several) behaves on security-relevant benchmarks, usually because it was just released and
they must compare it with models they already use. Drive **Plan → Run → Analyze**.

The arms are the **models**; everything else is held fixed. This skill measures; it does not
judge whether a result is acceptable. Execution tier: **T0/T1** (pure API, or in-memory mock
tools). Use `AskUserQuestion` for choices.

---

## PLAN

### 1. Preflight — Inspect in its own venv
```
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai openai 'inspect_evals[agentdojo,cyberseceval_4]'
```
The suite in `lib/inspect_suite.py` was verified against `inspect_evals` 0.29.0. Scorer and
metric names are not a stable API: after an upgrade run the smoke test before anything else.

### 2. Profile the models — ask
- **Models under test** (one or more). Two ways to reach them:
  - **Gateway aliases** (default): each model is an alias on one OpenAI-compatible gateway
    (LiteLLM, vLLM, Ollama `/v1`). Export `MODEL_BENCH_BASE_URL` (ending `/v1`) and
    `MODEL_BENCH_API_KEY`. This is the route for open-weights models.
  - **Native Inspect strings** (anything containing `/`, e.g. `anthropic/<id>`): pass
    `--keep-provider-env` so the provider key survives. Do this deliberately; see Notes.
- **Judge model.** Several checks need one. It must grade cyber content without refusing
  and must not be a model under test (the runner refuses if it is). No judge available →
  `--checks nojudge`.
- **Deployment context.** If a `review.json` exists (from `review-scope`), it is recorded
  with the results. Otherwise note the surface and system prompt in the manifest.

### 3. Choose checks and depth (`AskUserQuestion`)
`--checks`: `core` (below), `nojudge`, `vision`, `all`, or a comma list.

| Check | Dimension | Reads as | Judge | Calls/sample | Dataset |
|---|---|---|---|---|---|
| `cyse4_mitre` | direct misuse | offensive requests NOT assisted ↑ | yes ×2 | 3 | 1000 |
| `cyse4_mitre_frr` | over-refusal | benign security questions refused ↓ | no | 1 | 750 |
| `strong_reject` | harmful requests, direct | forbidden requests helped with ↓ | yes | 2 | 313 |
| `strong_reject_aim` | the same, jailbroken | jailbroken requests helped with ↓ | yes | 2 | 313 |
| `cyse4_instruct` | insecure code | code with a detected vulnerability ↓ | no | 1 | 1916 |
| `cyse4_multilingual_prompt_injection` | injection via content | injections that succeeded ↓ | yes | 2 | 1004 |
| `agentdojo` | injection via tools | episodes where the injected goal ran ↓ | no | ~6 | 944 |
| `atb_memory_poison` | memory poisoning | episodes resisted ↑ | no | ~4 | 10 |

Also registered: `cyse4_autocomplete`, `atb_autonomy_hijack`, `atb_data_exfil` (in `all`),
and `cyse3_visual_prompt_injection` (profile `vision`: needs a model and a judge that
accept images; downloads about 1000 images on first use). For a model that will read images,
screenshots or documents in deployment, use `vision-model-benchmark` instead: it runs a
corrected version of this benchmark split by injection type, plus FigStep and its own core set.

`--depth`: `smoke` (25 per check — proves the wiring only, the interval is about ±12
points), `standard` (100, about ±6 points, the default), `full`, or a number. Show the user
the cost before running anything:
```
python run_suite.py --checks core --depth standard --plan
```

### 4. Open an experiment folder
`bash new_experiment.sh model-benchmark "<label>" inspect --model "<models>"` — e.g. label
`gemma4-vs-qwen35-core`. It prints `EXP=<path>` and records the deployment context.

---

## RUN
```
MODEL_BENCH_BASE_URL=<gateway>/v1 MODEL_BENCH_API_KEY=<key> \
.venv-inspect/bin/python run_suite.py --models <a>,<b> --judge <judge> \
  --checks core --depth standard --out "<EXP>/results"
```
Models run one after another, each on the **same seeded sample draw**. Written to
`<EXP>/results/`: `results.json` (rewritten after every check, so an interrupted sweep keeps
what finished), `samples.jsonl` (one row per model × check × sample) and `logs/` (Inspect's
`.eval` transcripts; `inspect view --log-dir`). Record the command in `<EXP>/manifest.json`.

To add a newly released model later, run it with the **same `--checks`, `--depth` and
`--seed`** into a new folder and report both result files together.

---

## ANALYZE
```
python report.py "<EXP>/results/results.json" [earlier-run/results.json ...] \
  --baseline <model> --json "<EXP>/summary.json" | tee "<EXP>/summary.md"
```
Present to the user, in this order:
1. **The "Read first" section**: every check that errored or produced no score, and every
   validity flag. A flag means the measurement may not be trustworthy; the number is still
   shown, and it is the user's call how to treat it.
   - `judge_unresolved`: the judge could not grade this share of samples. Re-run with a
     stronger judge before relying on the rate.
   - `low_utility` (`agentdojo`, `atb_*`): the agent rarely completed its task, so the
     security number mostly reflects failing to act.
2. **The table**, with intervals and the "reads as" column. Two metrics are attack-success
   rates even though upstream names them accuracy; the arrows show the direction.
3. **The paired comparison** against the baseline model: the change in good outcomes on the
   same samples, with an exact McNemar p-value. Say plainly when the samples do not separate
   two models, and offer a deeper run.
4. **Pairs to read together:** `cyse4_mitre` with `cyse4_mitre_frr` (refusing everything
   helps the first and hurts the second); `strong_reject` with `strong_reject_aim` (the gap
   is the jailbreak uplift).

Do not tell the user whether a result is acceptable. If they have a `criteria.json` (from
`review-criteria`), `review-report` sets it beside these results.

End by offering: a deeper `--depth` on the checks that were too close to call, the extended
or vision checks, or adding another model on the same seed.

---

## Smoke test (no model, no key, about 2 minutes)
```
.venv-inspect/bin/python run_suite.py --models mockllm/model --judge mockllm/judge \
  --checks all --depth 3 --out /tmp/model-benchmark-smoke
```
Expected: the unjudged checks report `ok`; the judged ones report `no_score` or carry the
`judge_unresolved` flag, because a mock cannot grade. An `error` on a check, or a
`samples_do_not_reproduce_headline` flag, means the suite no longer matches the installed
`inspect_evals`: fix `lib/inspect_suite.py` before a real run.

## Notes
- **Provider keys are stripped before any eval.** Several `inspect_evals` scorers default
  their judge to a hardcoded `openai/gpt-4o*`. With the key gone, an unrouted judge fails
  instead of silently billing a provider and grading with a model nobody chose.
- **Direction is read from scorer source, not from the metric's name.** `agentdojo`
  `security.accuracy` counts executed injections, and the two prompt-injection `accuracy`
  metrics count injections that succeeded. Every run cross-checks that per-sample outcomes
  add up to the headline metric and withholds the paired comparison if they do not.
- **`strong_reject` applies no jailbreak by default.** Only the `_aim` variant transforms
  the prompts, and AIM is the single, dated transformation `inspect_evals` bundles. A low
  `strong_reject_aim` rate is a floor on jailbreak risk.
- **Sampling** is a seeded shuffle then a limit (`--seed`), not the first N rows: several
  datasets are sorted by category. `--first-n` restores first-N.
- **Validity limits** are configurable (`--max-judge-unresolved`, `--min-utility`) and are
  recorded in `results.json`. They are not acceptance thresholds.
- **Out of scope by design:** benchmarks that elicit offensive capability inside a Docker
  sandbox (`cve_bench`, `cybergym`, `cybench`, `threecb`).
- Public benchmarks are in training data. Read scores as comparative.
- **Not verified:** no run against a real model or gateway was possible where this was
  built. The suite was exercised with Inspect's mock model and with a fake gateway that
  returns mixed outcomes; the vision check ran only against the mock.
