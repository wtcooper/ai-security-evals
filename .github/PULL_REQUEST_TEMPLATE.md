<!--
Thanks for opening a PR! Please fill in the sections below. Delete any
that don't apply rather than leaving them blank.
-->

## What

<!-- One or two sentences. What does this PR change? -->

## Why

<!-- The problem this solves or the improvement it makes. Link the issue if
     one exists: "Fixes #123" or "Closes #456". -->

## How tested

<!-- Required. Concrete steps a reviewer can re-run.
     - "uv run pytest passes" is fine for code changes.
     - For harness/runner changes: include the local-proxy integration
       result, or a baseline-vs-guarded smoke comparison.
     - For corpus changes: include before/after case counts and any tier
       redistribution numbers. -->

## Checklist

- [ ] Tests added or updated for the behavior change
- [ ] `uv run pytest` is green locally
- [ ] Commits are signed off (`git commit -s` — see CONTRIBUTING.md)
- [ ] Docs updated where the change is user-visible (SKILL.md, README, etc.)
- [ ] No keyword/regex-based outcome classification introduced in the eval pipeline (mock handlers in `local/` are exempt)
- [ ] If this touches `data/corpus_v1.json` or `scripts/build_corpus.py`: ran the builder locally and verified `is_partial` / `missing_sources` are correct

## Reviewer notes (optional)

<!-- Anything specific you want the reviewer to look at, or context that
     isn't obvious from the diff. -->
