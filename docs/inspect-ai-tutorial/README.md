# Inspect AI Quick-Start Guide

[Inspect AI](https://inspect.aisi.org.uk/) (UK AI Security Institute) is an eval
framework: you point it at a model, it runs a **task** (dataset + solver + scorer)
and writes a rich per-sample log. The companion
[`inspect-evals`](https://github.com/UKGovernmentBEIS/inspect_evals) package ships
100+ ready-made benchmarks, including a strong cybersecurity suite — run them
out of the box with one CLI command.

| What you want | Where to look |
|---------------|---------------|
| Run ready-made cyber benchmarks (SecQA, CyberSecEval 2, CyberMetric, WMDP…) | [01-cyber-benchmarks.md](01-cyber-benchmarks.md) |
| Write your own eval (custom dataset + scorer) | [02-custom-evals.md](02-custom-evals.md) |
| Copy-paste task templates | [templates/](templates/) |

---

## Prerequisites

> ⚠️ `inspect-ai`/`inspect-evals` **conflict with `litellm[proxy]`** (this repo's main
> venv), so install them in their own venv — same convention the `control-bench`
> skill uses. Inspect talks to the gateway over HTTP; they never need to share a venv.

```bash
uv venv .venv-inspect
# `openai` is required by the openai-api provider used to reach the gateway below
uv pip install --python .venv-inspect/bin/python inspect-ai inspect-evals openai

bash targets/proxy/start_proxy.sh &   # LiteLLM gateway on :4000 (serves the local Ollama models)
ollama list                            # Ollama running + models pulled (gemma4, qwen3.5, …)
```

All commands below use `.venv-inspect/bin/inspect` explicitly so you never need to
activate the venv.

---

## Connecting to your model

Inspect addresses models as `<provider>/<model>`. Two ways to reach the local models:

**1. Through the LiteLLM gateway (recommended — matches the rest of this repo):**

The generic `openai-api/<name>/<model>` provider speaks the OpenAI wire format and
reads `<NAME>_BASE_URL` / `<NAME>_API_KEY` env vars (the `<name>` segment is
arbitrary — it only selects the env-var prefix):

```bash
export LITELLM_BASE_URL=http://localhost:4000/v1
export LITELLM_API_KEY=sk-mock

.venv-inspect/bin/inspect eval inspect_evals/sec_qa_v1 \
  --model openai-api/litellm/gemma4        # any model_name from targets/proxy/litellm_config.yaml
```

**2. Local Ollama, directly** (no gateway):

```bash
.venv-inspect/bin/inspect eval inspect_evals/sec_qa_v1 --model ollama/gemma4
# base URL defaults to http://localhost:11434/v1; override with OLLAMA_BASE_URL
```

The gateway route is handy for one place to manage keys, add guardrails, or A/B
local vs cloud — and lets the same model string cover a cloud model later (e.g.
`openai-api/litellm/gemini-3.1-flash-lite`).

---

## Viewing results

Every run writes a `.eval` log containing full per-sample transcripts. Keep logs
under `.evals/` (this repo's experiment-output convention, gitignored):

```bash
.venv-inspect/bin/inspect eval ... --log-dir .evals/inspect-tutorial/logs
.venv-inspect/bin/inspect view --log-dir .evals/inspect-tutorial/logs   # browser UI on :7575
```

`inspect view` auto-refreshes as new runs finish — start it once and leave it open.

---

## Glossary

**Task** — the unit Inspect runs: dataset + solver + scorer, declared with `@task`
**Sample** — one dataset row: `input` (prompt) + `target` (expected answer)
**Solver** — how the model is driven: `generate()` (single turn), chains, agents with tools
**Scorer** — pass/fail logic: `choice()` (MCQ), `includes()`/`match()` (string), `model_graded_qa()` (LLM judge)
**Epochs** — times each sample is run (variance / pass@k); some benchmarks default >1
**Grader / judge** — a *separate* model used by model-graded scorers; set with `--model-role grader=…` or a task arg
**`inspect_evals/<task>`** — addressing for the prebuilt benchmarks, e.g. `inspect_evals/cyse2_prompt_injection`

**Useful flags**: `--limit 10` (first N samples), `--epochs 1`, `--temperature 0`,
`--max-connections 2` (keep low for local models), `-T key=val` (task args),
`-M key=val` (model args), `--log-dir <dir>`.
