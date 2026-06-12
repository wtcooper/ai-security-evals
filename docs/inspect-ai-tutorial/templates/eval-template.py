"""Cyber-knowledge eval template — string and MCQ scoring, no judge model needed.

Two tasks in one file:
  knowledge_qa  — free-text answers scored with includes() (substring match)
  knowledge_mcq — multiple choice scored with choice()

Run (from repo root, gateway on :4000):
  export LITELLM_BASE_URL=http://localhost:4000/v1 LITELLM_API_KEY=sk-mock
  .venv-inspect/bin/inspect eval docs/inspect-ai-tutorial/templates/eval-template.py \
    --model openai-api/litellm/gemma4 --log-dir .evals/inspect-tutorial/logs

Select one task with  eval-template.py@knowledge_mcq
View results with     .venv-inspect/bin/inspect view --log-dir .evals/inspect-tutorial/logs
"""

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import choice, includes
from inspect_ai.solver import generate, multiple_choice


@task
def knowledge_qa():
    """Free-text Q&A: pass if the target string appears in the output."""
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="What TCP port does HTTPS use by default? Answer with the number only.",
                    target="443",
                ),
                Sample(
                    input="Name the OWASP Top 10 category for SQL injection (one word).",
                    target="injection",
                ),
                Sample(
                    input="What hashing algorithm does bcrypt build on?",
                    target="Blowfish",
                ),
            ]
        ),
        solver=generate(),       # single-turn: send input, take the reply
        scorer=includes(),       # case-insensitive substring; swap for match()/exact()
    )


@task
def knowledge_mcq():
    """Multiple choice: multiple_choice() formats the options, choice() scores the letter."""
    return Task(
        dataset=MemoryDataset(
            [
                Sample(
                    input="Which attack intercepts traffic between two parties?",
                    choices=[
                        "SQL injection",
                        "Man-in-the-middle",
                        "Buffer overflow",
                        "Cross-site scripting",
                    ],
                    target="B",
                ),
                Sample(
                    input="What does the 'S' in HTTPS guarantee on the wire?",
                    choices=[
                        "Server availability",
                        "Schema validation",
                        "Transport encryption",
                        "Source-code signing",
                    ],
                    target="C",
                ),
            ]
        ),
        solver=multiple_choice(),
        scorer=choice(),
    )
