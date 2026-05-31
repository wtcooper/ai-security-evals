# e2e — real-model end-to-end tests for all four skills

Unit tests use mocks; these prove each skill works **end-to-end against real models**
through the local LiteLLM gateway, with no mocking:

- **target** = `gemini-3-flash-preview` (flash)
- **judge / attacker / grader** = `gemini-3.1-flash-lite` (flash-lite)

Both run on Google AI Studio's free tier. Set `GCP_AI_STUDIO_API_KEY` in `.env`.

```bash
bash e2e/run_e2e.sh all              # all four (a few min; free-tier rate limits)
bash e2e/run_e2e.sh app-eval         # or one at a time
```
The runner starts the gateway, runs each skill tiny (to stay under rate limits),
summarizes, and reports PASS/FAIL.

## What each test proves (verified)

| Test | What it exercises | Result |
|---|---|---|
| `app-eval.e2e.yaml` | real target + real llm-rubric judge, full transform + metrics | F1 ≈ 0.67, 0 errors, classes all `answer`/200 |
| `control-isolate.e2e.yaml` | the **real LiteLLM content-filter** (403 blocks) | F1 1.0; histogram `block 3` / `403×3` — **403 auto-classified, no env** |
| `control-bench` (`inspect_e2e_task.py`) | shim → gateway → real model, A/B baseline vs content-filter | baseline 1.0 → guarded **0.0** (Δ −1.0) |
| `app-redteam.e2e.yaml` | real attacker + grader, redteam engine (`basic` strategy) | runs clean; target refuses, grader confirms |

## Findings these tests surfaced (and fixes applied)

1. **The llm-rubric judge must be an OpenAI-compatible provider.** A raw `https`
   provider sends `null` content to a strict gateway → 500. The app-eval config now
   uses `openai:chat:{{JUDGE_MODEL}}` with `JUDGE_BASE_URL` (matches app-redteam's grader).
2. **Adaptive redteam CAN run on your own attacker model — for the right strategies.**
   Verified against promptfoo source: with `PROMPTFOO_DISABLE_REMOTE_GENERATION=true`
   and `redteam.provider` set, **`crescendo` / `custom` / `jailbreak:tree` / classic
   iterative `jailbreak` / `basic`** fall back to your attacker model and run fully
   local. **`goat` / `mischievous-user` / plain `jailbreak` (→ `jailbreak:meta`) are
   remote-only** and throw under air-gap. (The earlier failure was using plain
   `jailbreak`.) The e2e uses `crescendo` with the local Gemini attacker. Also: the
   "unaligned" harmful/bias/medical/financial *plugins* are remote-only — use `intent`
   seeds locally.
3. **The control-bench shim is now body-aware** (uses the shared classifier
   `_shared/status_policy.py`), so it converts a 403 content-filter block to a refusal
   with **no `GUARDRAIL_BLOCK_STATUSES` config** — matching the JS skills.

## Notes
- Free-tier rate limits (429) are retried transiently by the harness; keep runs tiny.
- `control-bench` needs `inspect_ai` in `.venv` (`uv pip install inspect_ai`).
- These are real external calls to Google AI Studio — your prompts leave the machine.
