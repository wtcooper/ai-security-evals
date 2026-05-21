---
name: ai-guardrail-eval
description: A/B/C-test AI safety defenses against a static, peer-reviewed adversarial+benign benchmark corpus. Use when the user wants to compare two or more defense configurations head-to-head, measure the marginal contribution of a control, or regression-test a defense after a change. Ships with a locally-installed LiteLLM proxy as the test gateway — mock models and a mock guardrail let you verify the full pipeline with zero API keys, then swap in real provider keys and real guardrails (Prisma AIRS, Lakera, Aporia, Bedrock Guardrails, Azure Content Safety, custom in-house classifiers, prompt-injection filters, jailbreak classifiers, refusal-tuning policies, etc.) by editing one YAML config. Reports F1, Recall, FPR, ASR with marginal-attribution breakdown (separating control-layer blocks from model-policy blocks from model-text refusals) via mandatory LLM-as-judge classification — no keyword classifiers. Not an active red-teaming engine (use PyRIT/Garak/Petri for adaptive multi-turn discovery); this harness is for standardized, reproducible side-by-side comparison.
---

# ai-guardrail-eval — interactive runbook

You are running this skill on behalf of a user who wants to benchmark one or more AI safety defenses (guardrails, content filters, refusal-tuned models, custom classifiers, prompt-injection defenses, etc.) against a static adversarial corpus.

Work through the phases below in order. Use `AskUserQuestion` for choices, narrate progress concisely, and stop on errors rather than making assumptions about the user's setup.

---

## Phase 1 — Pre-flight

Verify the environment, then ask the user how they want to be set up. Do NOT auto-start the local proxy — many users have their own LiteLLM gateway already running.

1. **Python environment.** From the repo root, check `.venv/` exists. If not, run `uv sync` to create it and install deps (Python 3.11+). If `uv` is missing, instruct the user to install it (`brew install uv` or `pipx install uv`).

2. **Existing experiments.** Glance at `.evals/experiments/`. If prior experiments exist, list their names briefly — the user may want to compare new runs against them.

3. **Existing corpora.** Check `.evals/corpus/` for prior staged corpora. Report any that exist — the user may want to reuse one.

4. **Gateway selection (ask).** Use `AskUserQuestion` to choose:
   - **Bundled local LiteLLM proxy** — ship-with-skill, mock models, no API keys. Best for first-time setup and pipeline verification.
   - **User's own LiteLLM gateway** — they already have one running locally or remotely. Ask for `LITELLM_BASE_URL` and `LITELLM_API_KEY`; do not start the local one.

   If they pick bundled, check `curl -s http://localhost:4000/health/readiness`. If not running, offer to start it: `bash local/start_proxy.sh > /tmp/litellm_proxy.log 2>&1 &`. Wait until `/health/readiness` returns 200 (typically <5s).

---

## Phase 2 — Stage the corpus

Every experiment reads from a corpus JSON file. **Always stage it in `.evals/corpus/<name>.json`** so multiple experiments can reference the same canonical file and so custom prompts can be layered in deliberately.

Use `AskUserQuestion`:

- **Use the bundled benchmark corpus as-is.** Copy `skills/ai-guardrail-eval/data/corpus_v1.json` → `.evals/corpus/<name>.json` (default `<name>` = `corpus_bundled.json`). Best for first runs; covers HarmBench, AILuminate, StrongREJECT, AdvBench, XSTest, Alpaca. Partial — no multi-turn.
- **Reuse an existing corpus in `.evals/corpus/`.** Show the list (filenames + case counts + harmful/benign split) and let the user pick.
- **Rebuild the full corpus from sources.** Runs `scripts/build_corpus.py --out .evals/corpus/<name>.json`. Adds public Crescendo (multi-turn); also adds gated MHJ + AgentHarm if the user provides `HF_TOKEN` (they must have accepted the access agreement on HuggingFace).

Then ask whether to **augment the staged corpus with custom test cases** (`AskUserQuestion` yes/no):

- **Custom proprietary harmful prompts.** The user pastes prompts (or a file path) — each becomes a `TestCase` with `label="harmful"`, `source="user_custom"`, `category=` (ask). Useful when the user has domain-specific attacks (e.g. industry-regulated jailbreaks) the public benchmarks miss.
- **Custom benign eval set.** Same shape, `label="benign"`. Useful when the user has their own legitimate-use traffic (e.g. their actual customer queries, scrubbed) and wants FPR measured against it rather than XSTest-safe.

If they add custom cases, append them to the staged corpus JSON (`cases: [...]`), recompute counts, and write back. Preserve the `is_partial` and `missing_sources` metadata from the source corpus and set `augmented_with_custom: true` so the runner can warn that this corpus is non-canonical (every run that loads it should print "Corpus includes user-augmented cases; results not directly comparable to runs using only the canonical corpus").

The point: the **default is benchmark-only**, but the user can layer in their own tests deliberately. The canonical/bundled corpus is never modified in place.

Pass the staged path via `--corpus .evals/corpus/<name>.json` to every `run_eval.py` invocation in Phase 5.

---

## Phase 3 — Decide what to test

Ask the user (`AskUserQuestion`) which analysis they want:

- **Baseline only** — measure foundation-model behavior with no guardrail. Useful to understand what the model catches on its own.
- **Single guardrail vs baseline** — the most common ask. Produces the marginal-contribution delta. Runs two experiments.
- **Multi-way comparison** — one baseline plus N guardrail-on runs. Useful for vendor evaluation. Runs N+1 experiments.
- **Just one guardrail run** — when the user already has a baseline they want to compare against later (point them at the prior `.evals/experiments/<name>/metrics.json` for the baseline reference).

If the gateway is the bundled mock proxy: target models are `mock-target-compliant`, `mock-target-refusal`, `mock-target-policy-block`. Mock guardrail is `mock-guardrail`. Judge is `mock-judge`. No API keys needed.

If the gateway is the user's own LiteLLM: ask for the model name(s) and guardrail name(s) as registered in their config. Pick a judge model that is **different from the target** — warn explicitly if they choose the same one.

---

## Phase 4 — Configure the run(s)

For each experiment, gather (one `AskUserQuestion` per item, or grouped):

- **Target model**: model name as registered in the LiteLLM `model_list` (e.g. `mock-target-refusal`, `gpt-4o-mini`, `claude-haiku-4-5`).
- **Guardrail name(s)** (skip if baseline-only): names as registered under `guardrails:` in the LiteLLM config (e.g. `mock-guardrail`, `panw-prisma-airs-pre`).
- **Judge model** (default `gpt-4o-mini` for real gateways, `mock-judge` for the bundled mock proxy). Warn if equal to target.
- **Tier**: `smoke` (≈100 cases, ±8 pt CI; for tuning), `standard` (≈300 cases, ±5 pt CI; for vendor comparison), `comprehensive` (≈600 cases, ±3.5 pt CI; for final decisions). Explain the trade-off; default to `smoke` for first runs.
- **Replicates**: 1 by default; 3 for vendor decisions to measure stability.
- **Concurrency**: 10 by default (workers + judge pool).

If the user picks `standard` or `comprehensive` and the staged corpus is the bundled partial one, the runner will warn at startup that multi-turn data is missing. If they care about multi-turn coverage, go back to Phase 2 and rebuild.

---

## Phase 5 — Name and run

Generate or accept experiment names. Default pattern: `{tier}_{guardrail-or-baseline}_{YYYYMMDD-HHMMSS}` (already implemented in `run_eval.py`). For a multi-way comparison, prompt for N distinct names (or accept `--force` to overwrite).

For each experiment, invoke:

```bash
uv run python skills/ai-guardrail-eval/run_eval.py \
    --guardrail <NAME-or-none> \
    --model <TARGET-MODEL> \
    --tier <TIER> \
    --replicates <N> \
    --concurrency <N> \
    --corpus .evals/corpus/<staged-name>.json \
    --experiment-name <NAME>
```

Pass `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `JUDGE_MODEL` in the environment so the harness points at the gateway the user chose in Phase 1. Stream stdout so the user sees progress; **do not** background — the user is waiting on results.

If a run fails with all ERROR outcomes, stop and diagnose before continuing. Common causes:
- LiteLLM `guardrails` payload shape mismatch on very old proxy versions (modern LiteLLM accepts JSON list; this was verified working on v1.85.1+).
- Auth error from the upstream provider (real-mode runs).
- Judge endpoint unreachable.

---

## Phase 6 — Analyze, plain text

After all experiments complete, read each `.evals/experiments/<name>/metrics.json` and print a per-experiment block:

```
=== <experiment-name> ===
Total: 100 (50 harmful, 50 benign), errors excluded: 2
Harmful outcomes:   refusal 0.42  control_block 0.18  compliance 0.40
Benign outcomes:    refusal 0.04  control_block 0.02  compliance 0.94
Metrics:            F1 0.79  Recall 0.60  FPR 0.06  ASR 0.40  error_rate 0.02
```

For comparison runs, append a delta block per (baseline, guarded) pair:

```
=== Delta: <guarded-name> vs <baseline-name> ===
ΔControl_block_harmful: +0.18   (the guardrail's marginal signal)
ΔControl_block_benign:  +0.02   (over-block cost)
ΔASR:                   -0.18
ΔFPR:                   +0.02
```

Then **call out one or two surprises in plain English**:
- "ASR dropped 0.18 but FPR moved only +0.02 — the guardrail catches without over-blocking."
- "Most of the apparent ASR drop came from the foundation model's own refusal text, not the guardrail (control_block_harmful only +0.04)."
- "FPR jumped 0.12 — the guardrail is over-blocking benign requests; spot-check the transcript for false positives on XSTest cases."

**Always read `metrics.json["by_technique_family"]`** when the experiment includes any attack-class data beyond plain content harm (which is most runs at smoke+ now). The corpus covers four attack classes and many technique families within each:

- **Prompt injection** families: `system_prompt_exfiltration` (Lakera Gandalf), `instruction_override` (deepset), `ignore_previous_instructions`, `system_mode` (DAN), `token_smuggling`, `language_switching`, `overload_with_information`, `persuasion`, `payload_splitting`, `output_formatting_manipulation`, `virtualization`, `indirect_reference`, `hypothetical_scenario`, `few_shot_attack`, `many_shot_attack`, `repeated_token_attack`, `mixed_techniques` (all from CyberSecEval PI)
- **Cyber attack assistance** families: `command_and_control`, `persistence`, `privilege_escalation`, `lateral_movement`, `discovery`, `evasion`, `execution`, `exfil`, `collection`, `recon` (from CyberSecEval MITRE) + interpreter-abuse families
- **Multi-turn** families: `gradual_escalation`, `code_smuggling`, `hypothetical_concretization`, `persona_split`, `cipher_substitution`, etc.

Highlight uneven coverage explicitly. A guardrail with 0.95 recall on `framing_pretext` but 0.20 on `system_prompt_exfiltration` has a real gap that overall recall hides. Example callouts:
- "Strong on content harm (recall 0.92) but only catches 0.35 of prompt-injection cases — content-safety guardrail, not a PI guardrail."
- "PI guardrail catches 0.88 of direct overrides (`ignore_previous_instructions`) but only 0.30 of `token_smuggling` and 0.40 of `language_switching` — defense pattern-matches obvious attacks but misses obfuscation."
- "Over-blocks 0.18 of `cyber_legitimate` (MITRE-FRR) — refuses security-engineering questions like firewall config and packet inspection. Real false-positive risk for any security-focused user."

Don't over-claim on small per-family n; flag the sample size when it's under 10.

Avoid dashboards, charts, or fancy formatting. Plain text only.

---

## Phase 7 — Point at the audit trail

End with the artifact paths for each experiment:

```
.evals/experiments/<name>/
  config.json     (the exact run config)
  metrics.json    (computed metrics)
  results.json    (per-test results)
  transcript.jsonl (full request/response/judge envelope per test)
```

Tell the user: "Open `transcript.jsonl` to spot-check any judge decision — every line has the full request, response, and the judge's one-sentence reasoning."

---

## Don'ts

- **Don't fall back to keyword classification** if the judge fails. The run errors loudly; that's intentional. Don't paper over it.
- **Don't compare runs with different judge models** without flagging the difference. The judge is part of the eval — change it and you've changed the measurement instrument. `config.json` records both for cross-checks.
- **Don't run against production endpoints** without explicit user confirmation. Adversarial prompts in input mode are harmless (mocked `mock_response`), but in baseline mode they hit a real model and may show up in upstream logs.
- **Don't commit `.env.local`** or rebuilt full corpora containing gated data (MHJ, AgentHarm). Those datasets require accepting a HuggingFace agreement and must not be redistributed.
- **Don't claim a CI-narrow difference is real.** At smoke tier the 95% CI on Recall is ±8 points. A 5-point gap between two vendors at smoke is noise. Push to `standard` or `comprehensive` before a vendor decision.
