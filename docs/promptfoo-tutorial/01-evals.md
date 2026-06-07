# Promptfoo Evals

Evals test model **quality** — correctness, tone, instruction-following, safety rubrics. Not adversarial.

---

## How it works

```
prompts × providers × tests  →  promptfoo eval  →  results table
```

- **providers** — models to compare (gemma4 vs gemma4:e2b, or local vs cloud)
- **prompts** — template strings with `{{variable}}` slots
- **tests** — input variables + assertion rules that define pass/fail
- **assert** — the scoring engine: exact string match, regex, or LLM-as-judge rubric

---

## Quick run

```bash
npx promptfoo@latest eval \
  --config docs/promptfoo-tutorial/templates/eval-template.yaml

npx promptfoo@latest view      # open browser results UI
```

---

## Assertion types

| Type | What it checks | Example |
|------|---------------|---------|
| `icontains` | Case-insensitive substring match | `value: Paris` |
| `not-icontains` | Substring must NOT appear | `value: I don't know` |
| `regex` | Regex match on output | `value: '\d{3}-\d{4}'` |
| `llm-rubric` | LLM grades output against a free-text criterion | `value: "Response is polite and under 50 words"` |
| `javascript` | Custom JS function, return true/false | `value: "output.length < 200"` |
| `similar` | Semantic similarity to a reference string | `value: "The capital is Paris"` |

`llm-rubric` is the most powerful for open-ended safety or quality testing. The grader LLM sees your criterion and the model output and returns pass/fail + reasoning.

---

## LLM-as-judge (llm-rubric) with expected responses

This is the "input prompt + expected response, graded by an LLM" pattern. Put the
input in `vars`, the grading criterion (which can reference your expected answer)
in an `llm-rubric` assert:

```yaml
tests:
  - vars:
      prompt: Explain quantum entanglement to a 10-year-old.
    assert:
      - type: llm-rubric
        value: >-
          Response uses an analogy a child would understand, avoids unexplained
          jargon (e.g. "superposition"), and is between 50 and 150 words.

  - vars:
      prompt: What is the refund window for a standard order?
    assert:
      - type: llm-rubric
        value: >-
          The answer must state that refunds are available within 30 days.
          Mark FAIL if it gives any other number or refuses to answer.
```

The judge model is set in `defaultTest.options.provider` (or falls back to promptfoo cloud if unset). All of this is **single-turn** — one prompt, one response, one grade.

---

## Multi-model comparison

List multiple providers — promptfoo runs every prompt against every model and shows a side-by-side table.

```yaml
providers:
  - id: openai:chat:gemma4
    config:
      apiBaseUrl: http://localhost:4000/v1
      apiKey: sk-mock
  - id: openai:chat:gemma4:e2b
    config:
      apiBaseUrl: http://localhost:4000/v1
      apiKey: sk-mock
```

---

## Template config

See [`templates/eval-template.yaml`](templates/eval-template.yaml) — fully commented with every toggle.

---

## Key toggles

| Setting | Location | Effect |
|---------|----------|--------|
| `evaluateOptions.cache: false` | top-level | Disable response caching (always re-run) |
| `evaluateOptions.maxConcurrency` | top-level | Parallel requests to providers |
| `evaluateOptions.repeat` | top-level | Run each test N times (variance testing) |
| `defaultTest.options.provider` | defaultTest | Judge model for `llm-rubric` assertions |
| `--filter-first-n N` | CLI flag | Run only the first N tests (quick smoke check) |
| `--no-cache` | CLI flag | Same as `cache: false` but per-run |
