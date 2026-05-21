---
name: Bug report
about: Something in the harness, a skill, or the local proxy doesn't work as documented
title: "[bug] "
labels: bug
assignees: ''
---

## What happened

<!-- One or two sentences describing the bug. -->

## What you expected to happen

<!-- What the docs / SKILL.md / README led you to expect. -->

## Steps to reproduce

<!-- Be concrete. Reviewer should be able to copy-paste these and see the
     same behavior. Include the exact CLI invocation, env vars, and corpus
     path. -->

```bash
# example
LITELLM_BASE_URL=http://localhost:4000 LITELLM_API_KEY=sk-mock JUDGE_MODEL=mock-judge \
uv run python skills/ai-guardrail-eval/run_eval.py --guardrail none ...
```

## Environment

- OS: <!-- macOS 15, Ubuntu 24.04, etc. -->
- Python: <!-- output of `uv run python --version` -->
- Repo commit: <!-- output of `git rev-parse --short HEAD` -->
- LiteLLM version: <!-- output of `uv run pip show litellm | grep Version` -->
- Gateway: <!-- bundled local proxy, your own LiteLLM, etc. -->

## Logs / output

<!-- Paste the relevant snippet of stderr/stdout. For judge classification
     issues, paste 1-3 lines from .evals/experiments/<name>/transcript.jsonl
     so we can see the judge envelope. Redact any secrets. -->

```
```

## Additional context

<!-- Anything else: was it working in a previous commit? Is it environment-
     specific? Have you tried with the bundled mock proxy? -->
