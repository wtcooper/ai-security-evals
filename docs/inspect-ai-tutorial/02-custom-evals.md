# Writing Custom Evals

When no prebuilt benchmark fits, an Inspect eval is one small Python file:

```
dataset (Samples) → solver (how the model is driven) → scorer (pass/fail) = Task
```

```python
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import generate
from inspect_ai.scorer import includes

@task
def my_eval():
    return Task(
        dataset=MemoryDataset([Sample(input="What port does SSH use?", target="22")]),
        solver=generate(),
        scorer=includes(),
    )
```

```bash
.venv-inspect/bin/inspect eval my_eval.py \
  --model openai-api/litellm/gemma4 --log-dir .evals/inspect-tutorial/logs
```

A file can hold several `@task`s — select one with `my_eval.py@task_name`.

---

## Scorer types

| Scorer | What it checks | Analogue in promptfoo |
|--------|---------------|----------------------|
| `includes()` | Target appears in output (case-insensitive) | `icontains` |
| `match()` | Output begins/ends with target | — |
| `exact()` | Output equals target | `equals` |
| `answer()` | Target after an "ANSWER:"-style prefix | — |
| `choice()` | MCQ — pair with the `multiple_choice()` solver | — |
| `model_graded_qa()` | LLM judge grades against free-text criteria | `llm-rubric` |
| `model_graded_fact()` | LLM judge checks output states a target fact | `llm-rubric` |

`model_graded_qa` is the workhorse for open-ended security behavior ("did the model
refuse?", "does the answer avoid operational detail?").

## LLM-as-judge with a local grader

Model-graded scorers use a **separate** judge model. Resolution order:

1. Explicit in the scorer: `model_graded_qa(model="openai-api/litellm/qwen3.5")`
2. The `grader` model role (keeps the eval file model-agnostic — preferred):
   ```bash
   .venv-inspect/bin/inspect eval my_eval.py \
     --model openai-api/litellm/gemma4 \
     --model-role grader=openai-api/litellm/qwen3.5
   ```
3. Fallback: the model under test grades itself (avoid — biased).

Per-sample grading criteria go in `Sample(..., target="...")`; the judge sees the
question, the model's answer, and the criterion. Pass `grade_pattern` /
`instructions` to `model_graded_qa` for custom rubric scales.

## Datasets from files

Beyond `MemoryDataset`, load real datasets:

```python
from inspect_ai.dataset import csv_dataset, json_dataset, hf_dataset

dataset = json_dataset("probes.jsonl")          # fields: input, target, id, metadata
dataset = csv_dataset("probes.csv")
dataset = hf_dataset("walledai/CyberSecEval", split="train",
                     sample_fields=FieldSpec(input="prompt", target="judge"))
```

---

## Templates

| File | Pattern |
|------|---------|
| [templates/eval-template.py](templates/eval-template.py) | String/MCQ-scored cyber knowledge eval — no judge needed |
| [templates/judge-eval-template.py](templates/judge-eval-template.py) | Refusal/safety testing with `model_graded_qa` + local judge |

```bash
.venv-inspect/bin/inspect eval docs/inspect-ai-tutorial/templates/eval-template.py \
  --model openai-api/litellm/gemma4 --log-dir .evals/inspect-tutorial/logs

.venv-inspect/bin/inspect eval docs/inspect-ai-tutorial/templates/judge-eval-template.py \
  --model openai-api/litellm/gemma4 \
  --model-role grader=openai-api/litellm/qwen3.5 \
  --log-dir .evals/inspect-tutorial/logs
```
