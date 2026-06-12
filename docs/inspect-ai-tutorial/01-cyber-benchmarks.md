# Out-of-the-Box Cyber Benchmarks

`inspect-evals` ships a cybersecurity suite you can run with zero eval-writing.
They split into two tiers:

| Tier | Benchmarks | Needs |
|------|-----------|-------|
| **Knowledge / safety QA** — run anywhere | SecQA, CyberMetric, WMDP-Cyber, SEvenLLM, CyberSecEval 2 | Just a model (2 of the cyse2 tasks also need a judge model) |
| **Agentic CTFs** — sandboxed | Cybench, InterCode CTF, GDM in-house CTF, CyberSecEval 4 | Docker (or k8s), big disk, hours of runtime |

Start with tier 1 — every command below runs against the local gateway. Setup
(once per shell):

```bash
export LITELLM_BASE_URL=http://localhost:4000/v1
export LITELLM_API_KEY=sk-mock
LOGS=.evals/inspect-tutorial/logs
```

---

## SecQA — computer-security MCQ (easiest start)

Multiple-choice security questions (v1 = foundational, v2 = harder). `choice()`
scored — no judge model, no downloads beyond a public HF dataset.

```bash
.venv-inspect/bin/inspect eval inspect_evals/sec_qa_v1 \
  --model openai-api/litellm/gemma4 --limit 20 --log-dir $LOGS

# variants: sec_qa_v2, sec_qa_v1_5_shot, sec_qa_v2_5_shot
```

## CyberMetric — cyber-knowledge MCQ at 4 sizes

RAG-sourced cybersecurity certification-style questions. Pick the size by suffix:
`cybermetric_80`, `_500`, `_2000`, `_10000`.

```bash
.venv-inspect/bin/inspect eval inspect_evals/cybermetric_80 \
  --model openai-api/litellm/gemma4 --log-dir $LOGS
```

## WMDP-Cyber — hazardous-knowledge proxy MCQ

1,987 MCQs measuring potentially hazardous cyber knowledge (the "weapons of mass
destruction proxy" benchmark — used for unlearning/safeguard research; a *high*
score means more hazardous knowledge, so read it inverted vs the others).

```bash
.venv-inspect/bin/inspect eval inspect_evals/wmdp_cyber \
  --model openai-api/litellm/gemma4 --limit 50 --log-dir $LOGS
```

## SEvenLLM — cyber-incident analysis

Understanding/analysis of real security incidents. MCQ variants score locally;
needs an extra: `uv pip install --python .venv-inspect/bin/python 'inspect-evals[sevenllm]'`.

```bash
.venv-inspect/bin/inspect eval inspect_evals/sevenllm_mcq_en \
  --model openai-api/litellm/gemma4 --limit 20 --log-dir $LOGS
```

## CyberSecEval 2 — risky-capability + injection testing (Meta)

Three tasks, all prompt-based (no sandbox). This is the closest analogue to the
promptfoo red-team packs — it measures whether the model *complies with* abuse:

| Task | Measures | Judge model? |
|------|----------|--------------|
| `cyse2_prompt_injection` | Does injected text override the system prompt? | ✅ |
| `cyse2_interpreter_abuse` | Compliance with malicious code-interpreter requests | ✅ |
| `cyse2_vulnerability_exploit` | Can it actually solve memory-corruption exploit puzzles? | ❌ (programmatic) |

The judged tasks default their judge to `openai/gpt-4o-mini` — point it at a local
model on the gateway with `-T judge_llm=…` (use a *stronger* model than the target;
a weak judge under-reports failures). Default is 4 epochs; use `--epochs 1` for
quick runs.

```bash
.venv-inspect/bin/inspect eval inspect_evals/cyse2_prompt_injection \
  --model openai-api/litellm/gemma4 \
  -T judge_llm=openai-api/litellm/qwen3.5 \
  --epochs 1 --limit 20 --log-dir $LOGS
```

> **PASS/FAIL direction:** for `prompt_injection` and `interpreter_abuse`, a higher
> score = more resistant (safer). For `vulnerability_exploit`, higher = more capable
> of exploitation — decide which direction is "good" for your threat model.

> ⏱️ **Slow on local models.** A judged cyse2 run is two model calls per sample, and a
> local *reasoning* judge (e.g. `qwen3.5`) emits long chains of thought — a 3-sample
> `--limit 3 --epochs 1` run took **~26 min** on this setup. For quick iteration use a
> non-reasoning local model as the judge, or a cheap cloud judge
> (`-T judge_llm=openai-api/litellm/gemini-3.1-flash-lite`), and keep `--limit` tiny.

---

## Tier 2 — agentic CTF benchmarks (Docker required)

These give the model a shell in a sandboxed environment and score real
flag-capture. Substantially heavier — expect long runtimes and (for the GDM
tasks) 65 GB+ of images:

| Task | What it is |
|------|-----------|
| `inspect_evals/cybench` | 40 professional CTF challenges, Kali-style env; install `'inspect-evals[cybench]'`; default sandbox is k8s, Docker needs an explicit risk-acknowledgment env var |
| `inspect_evals/gdm_intercode_ctf` | 78 picoCTF challenges (bash/python in Docker) |
| `inspect_evals/gdm_in_house_ctf` | Google DeepMind's in-house CTF suite |
| `inspect_evals/cyse4_*` | CyberSecEval 4 family (mitre, mitre_frr, multiturn_phishing, …) |

Pattern is identical — `inspect eval inspect_evals/cybench --model … --limit 1` —
just make sure Docker is running and start with `--limit 1` to gauge cost. See each
eval's page at <https://ukgovernmentbeis.github.io/inspect_evals/> for
sandbox-specific setup.

---

## Comparing models side by side

Pass multiple models in one run — Inspect evaluates each and `inspect view` shows
them side by side:

```bash
.venv-inspect/bin/inspect eval inspect_evals/sec_qa_v1 \
  --model openai-api/litellm/gemma4,openai-api/litellm/qwen3.5 \
  --limit 20 --log-dir $LOGS
```

## Pulling scores programmatically

```bash
.venv-inspect/bin/python - <<'PY'
from inspect_ai.log import list_eval_logs, read_eval_log
for p in list_eval_logs(".evals/inspect-tutorial/logs"):
    log = read_eval_log(p)
    print(log.eval.task, log.eval.model,
          {s.name: {m: v.value for m, v in s.metrics.items()} for s in (log.results.scores or [])})
PY
```

---

## Gotchas

| Symptom | Cause + fix |
|---------|-------------|
| Run hammers Ollama / times out | Default `--max-connections` is 10 — set `--max-connections 2` for local models |
| cyse2 run is 4× longer than expected | Default `--epochs 4`; pass `--epochs 1` |
| Judge calls fail with auth/model errors | The cyse2 judge defaults to `openai/gpt-4o-mini` — override with `-T judge_llm=openai-api/litellm/<model>` |
| `openai-api` provider can't find credentials | The `<name>` segment in `openai-api/<name>/<model>` must match your env-var prefix: `litellm` → `LITELLM_BASE_URL`/`LITELLM_API_KEY` |
| Cybench refuses to start under Docker | It defaults to k8s and requires an explicit risk-acknowledgment env var for Docker — see the cybench eval page |
