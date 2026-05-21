# Security Policy

## Reporting a vulnerability

**Please don't open a public GitHub issue for security vulnerabilities.**

Use GitHub's **Private Vulnerability Reporting**:

1. Go to the [Security tab](https://github.com/wtcooper/ai-security-evals/security) of this repo.
2. Click **Report a vulnerability**.
3. Fill in the details. The report is visible only to repo maintainers.

If you can't use that flow, email **wadetcooper@gmail.com** with `SECURITY` in the subject line.

We'll acknowledge within **3 business days** and aim to share an initial assessment within **7 days**. If the issue is confirmed, we'll work with you on a coordinated disclosure timeline (typically 30–90 days depending on severity and complexity).

## Scope

This repo is a **harness for evaluating AI security defenses** — it sends adversarial prompts to LLM gateways and classifies the responses. That puts the security boundaries in a few specific places:

### In scope

- **Credential/secret leakage** in the harness, mock handlers, examples, or docs (e.g. a code path that logs `LITELLM_API_KEY`, `HF_TOKEN`, or any provider key).
- **Prompt injection paths** that could redirect the judge's classification (e.g. crafted response text that flips the judge's outcome — this is a real concern because the judge IS an LLM).
- **Unsanitized handling** of user-supplied corpus content (path traversal via case IDs, JSON injection into transcripts, etc.).
- **Dependency vulnerabilities** that materially affect this codebase (Dependabot will catch most; report anything Dependabot misses).
- **Mock proxy / `local/`** code paths that could be tricked into proxying to attacker-controlled upstreams or leaking the `master_key`.
- **Reproducibility / integrity** issues — corpus tampering paths, judge prompt drift between versions that silently changes results.

### Out of scope

- Adversarial prompts in the bundled corpus (`data/corpus_v1.json`) — those are the test inputs, not vulnerabilities. They're sourced from peer-reviewed benchmarks with attribution.
- Findings against an upstream model provider (OpenAI, Anthropic, etc.) — report those to the provider directly.
- Findings against a third-party guardrail vendor — report to the vendor.
- Findings that require attacker control of the user's `~/.ssh/`, `~/.aws/`, `.env.local`, or write access to `local/litellm_config.yaml`.
- DoS against the local LiteLLM proxy from local clients.

### Especially welcome

- Demonstrations that the judge can be reliably tricked via a crafted response text (and a defensible mitigation).
- Demonstrations of `transcript.jsonl` leaking content from `.env.local` or memory the user didn't intend to record.
- Audit findings about the four-outcome taxonomy mapping to TP/FP/FN/TN in `metrics.py`.

## Disclosure handling

- Fixes for confirmed reports are coordinated privately, then released with credit to the reporter (unless they prefer to remain anonymous).
- We do not currently offer a paid bounty.
- A public security advisory (GHSA) is published alongside the fix release.

## Supported versions

This project is pre-1.0; only the latest commit on `main` is supported for security fixes. Pin a specific commit if you need long-term reproducibility, and reach out before adopting it in production-critical paths.
