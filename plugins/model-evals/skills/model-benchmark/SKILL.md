---
name: model-benchmark
description: >-
  Measure and COMPARE the security posture of AI models themselves — open-weights or
  frontier — when a new one is released: a fixed suite of Inspect benchmarks, one per risk
  dimension (direct misuse, over-refusal, harmful-request refusal, jailbreak uplift,
  insecure code, prompt injection via content, injection via tools, memory poisoning),
  run on the same seeded samples for every model, plus a supply-chain check of
  open-weights files. Reports each rate with a confidence interval and says which
  differences between models are larger than the noise. For a guardrail's effect inside
  a benchmark use control-bench; for an app endpoint use app-benchmark.
license: MIT
compatibility: "Requires Python 3.11+ and a separate virtual environment with inspect_ai, inspect_evals and openai."
---

# model-benchmark — security benchmarks for a model release

You are running this skill **on behalf of a user** who needs to know how a model (or
several) behaves on security-relevant benchmarks, usually because it was just released
and they must compare it with models they already use. Drive **Plan → Run → Analyze**.
Inspect runs the benchmarks; `run_suite.py` routes every model and judge call, selects
the samples, and voids results a judge could not grade. This skill **measures**. It sets
no pass/fail threshold — that is the caller's policy. Use `AskUserQuestion` for choices.

---

## PLAN

### 1. Preflight — Inspect in its own venv
```
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai openai 'inspect_evals[agentdojo,cyberseceval_4]'
```
`suite.py` was verified against `inspect_evals` 0.29.0. Scorer and metric names are not
a stable API: after an upgrade run step 4's smoke test before trusting anything.

### 2. Profile the models — ask
- **Models under test** (one or more). Two ways to reach them:
  - **Gateway aliases** (default): every model is an alias on one OpenAI-compatible
    gateway (LiteLLM, vLLM, Ollama `/v1`). Export `MODEL_BENCH_BASE_URL` (ending `/v1`)
    and `MODEL_BENCH_API_KEY`. This is the route for open-weights models.
  - **Native Inspect strings** (anything containing `/`, e.g. `anthropic/<id>`): pass
    `--keep-provider-env` so the provider key survives. Only do this deliberately — see
    Notes on why keys are stripped by default.
- **Judge model.** Four checks need one. It must be a strong model that **will grade
  cyber content without refusing**, and must not be a model under test. A weak judge does
  not fail loudly; it voids checks (`void_judge`). No judge available → `--checks nojudge`.
- **Do the models call tools reliably?** If unsure, expect the agentic checks to flag it.

### 3. Choose checks and depth (`AskUserQuestion`)
`--checks`: `core` (one check per dimension, below), `nojudge`, `all`, or a comma list.

| Check | Dimension | Judge | Calls/sample | Dataset |
|---|---|---|---|---|
| `cyse4_mitre` | direct misuse | yes ×2 | 3 | 1000 |
| `cyse4_mitre_frr` | over-refusal (its mandatory pair) | no | 1 | 750 |
| `strong_reject` | harmful requests asked directly | yes | 2 | 313 |
| `strong_reject_aim` | the same wrapped in a jailbreak | yes | 2 | 313 |
| `cyse4_instruct` | insecure generated code | no | 1 | 1916 |
| `cyse4_multilingual_prompt_injection` | injection via content | yes | 2 | 1004 |
| `agentdojo` | injection via tool output | no | ~6 | 944 |
| `atb_memory_poison` | memory poisoning | no | ~4 | 10 |

Extended (in `all`): `cyse4_autocomplete`, `atb_autonomy_hijack`, `atb_data_exfil`.

`--depth`: `quick` (25/check — proves the wiring, ±12 points, **not a result**), `good`
(100, ±6 points, the default), `full`, or a number. Show the user the cost first:
```
python run_suite.py --checks core --depth good --plan
```

### 4. Smoke test (no model, no key, ~2 min)
```
.venv-inspect/bin/python run_suite.py --models mockllm/model --judge mockllm/model \
  --checks all --depth 3 --out /tmp/model-benchmark-smoke
```
Expected: the four judged checks report `void_judge` (a mock cannot grade) and the rest
`ok`. Any `no_score` means a metric key in `suite.py` no longer matches the installed
`inspect_evals` — fix it before a real run.

### 5. Open an experiment folder
`bash new_experiment.sh model-benchmark "<label>" inspect --model "<models>"` — e.g. label
`gemma4-vs-qwen35-core`. It prints `EXP=<path>`.

---

## RUN

### 1. Benchmarks
```
MODEL_BENCH_BASE_URL=<gateway>/v1 MODEL_BENCH_API_KEY=<key> \
.venv-inspect/bin/python run_suite.py --models <a>,<b> --judge <judge> \
  --checks core --depth good --out "<EXP>/results"
```
Models run one after another, each on the **same seeded sample draw**, so they are
comparable. `results.json` is rewritten after every check; an interrupted sweep keeps
what finished. Inspect's `.eval` logs under `<EXP>/results/logs` are the full transcripts
(`inspect view --log-dir`). Record the command in `<EXP>/manifest.json`.

To add a newly released model later, run it with the **same `--checks`, `--depth` and
`--seed`** into a new folder and summarize both result files together.

### 2. Open-weights supply chain (only for models with a Hugging Face repo)
```
python weights_scan.py <org/repo> --out "<EXP>/results/weights-<name>.json"
```
Reads the scanner verdicts the Hub already publishes; downloads no weights. Verdict is
`unsafe`, `clean` or `unscanned` — **`unscanned` is not `clean`**. It also reports how
many weight files each scanner actually covered and whether the repo ships only
pickle-format weights (code execution on load) with no safetensors/GGUF alternative.

---

## ANALYZE
```
python report.py "<EXP>/results/results.json" [earlier-run/results.json ...] \
  | tee "<EXP>/summary.md"
```
Present to the user, in this order:
1. **What did not produce a result** — every `void_judge`, `error`, `no_score` and
   partial row. These are not zeros and must not be read as passes.
2. **Agentic checks with low utility.** `agentdojo` and the `atb_*` checks score security
   from tool calls, so a model that cannot use tools scores well by doing nothing. If the
   summary flags low utility, say the security number is not interpretable.
3. **The table**, with intervals. Then only the differences the summary lists as larger
   than the noise. Do not rank models on overlapping intervals; offer a deeper run.
4. **Pairs, read together:** `cyse4_mitre` with `cyse4_mitre_frr` (refusing everything
   passes the first and fails the second); `strong_reject` with `strong_reject_aim` (the
   gap is the jailbreak uplift).
5. The weights verdict, if run.

End by offering: a deeper `--depth` on the checks that were too close to call, the
extended checks, or adding another model on the same seed.

## Notes
- **Provider keys are stripped before any eval.** Several `inspect_evals` scorers default
  their judge to a hardcoded `openai/gpt-4o*`. With the key gone, an unrouted judge fails
  instead of silently billing a real provider and grading with a model you did not pick.
- **`strong_reject` applies no jailbreak by default** — it asks 313 forbidden prompts
  directly. Only the `_aim` variant transforms them, and AIM is the single, dated
  transformation `inspect_evals` bundles. A low `strong_reject_aim` rate is a floor on
  jailbreak risk, not evidence of robustness.
- **Sampling** is a seeded shuffle then a limit (`--seed`), not the first N rows: several
  datasets are sorted by category. `--first-n` restores first-N.
- Intervals are 95% Wilson over scored samples; `atb_*` datasets are 6–10 cases, so their
  intervals are very wide by construction.
- **Out of scope by design:** benchmarks that elicit offensive capability inside a Docker
  sandbox (`cve_bench`, `cybergym`, `cybench`, `threecb`). They need supervision and
  answer a different question (how capable, not how resistant).
- Public benchmarks are in training data. Treat scores as comparative, not absolute.
