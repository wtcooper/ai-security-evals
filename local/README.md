# local/ — local LiteLLM proxy for harness testing

This directory holds the local LiteLLM gateway the `ai-guardrail-eval` skill (and any future skill) talks to during development. LiteLLM is installed as a Python dependency (`litellm[proxy]` in `pyproject.toml`) and runs as a local process on port 4000 — **there is no remote service to deploy**.

## Files

| File | What it does |
|---|---|
| `litellm_config.yaml` | Proxy config: mock model_list, mock guardrail, custom provider map. Edit to add real upstreams. |
| `mock_handlers.py` | Python: `MockTargetLLM`, `MockJudgeLLM`, `MockBlockGuardrail`. Registered in the config above. |
| `start_proxy.sh` | One-liner that starts the proxy with the config and handler module path resolved correctly. |

## Quick start

From the repo root:

```bash
# 1. Install deps (once)
uv sync

# 2. Start the proxy
bash local/start_proxy.sh
# or run in the background: bash local/start_proxy.sh &

# 3. Sanity check
curl -s http://localhost:4000/health | jq

# 4. Hit a mock model directly
curl -s http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer sk-mock" \
    -H "Content-Type: application/json" \
    -d '{"model": "mock-target-refusal", "messages":[{"role":"user","content":"test"}]}' | jq
```

## What each mock does

| Mock | What it simulates |
|---|---|
| `mock-target-compliant` | An LLM that returns substantive text answering any prompt → judge should classify as **COMPLIANCE**. |
| `mock-target-refusal` | An LLM that refuses every prompt → judge should classify as **REFUSAL**. |
| `mock-target-policy-block` | A foundation model that returns HTTP 400 with `content_policy_violation`-style envelope → judge should classify as **CONTROL_BLOCK**. |
| `mock-judge` | Deterministic classifier that reads the response envelope embedded in the judge prompt and emits a `{"outcome": ..., "reasoning": ...}` JSON. Stand-in for a real well-calibrated judge. |
| `mock-guardrail` | Pre-call `CustomGuardrail` that blocks prompts containing obvious adversarial substrings ("how to make a bomb", etc.). Just enough to produce CONTROL_BLOCK outcomes in the verification matrix. |

These mocks are NOT meant to substitute for real defenses in actual evaluation. They prove the harness wiring: HTTP flow, provider parsing, judge invocation, outcome → metrics mapping, per-experiment output write.

## Adding real upstream models

Edit `litellm_config.yaml`:

```yaml
model_list:
  - model_name: gpt-4o-mini
    litellm_params:
      model: openai/gpt-4o-mini
      api_key: os.environ/OPENAI_API_KEY
```

Then put your real API keys in **`.env.local`** at the repo root (gitignored). The `start_proxy.sh` script sources it automatically.

## Adding real guardrails

Same pattern — edit the `guardrails:` block. See LiteLLM's docs for the exact syntax for each provider (Lakera, Aporia, Bedrock, Prisma AIRS, Presidio, etc.):

```yaml
guardrails:
  - guardrail_name: lakera-pre
    litellm_params:
      guardrail: lakera_v2
      mode: pre_call
      api_key: os.environ/LAKERA_API_KEY
```

The harness sees these names via `--guardrail lakera-pre`.

## Security notes

- **Never commit real API keys** to `litellm_config.yaml` or `.env.local`. Use `os.environ/...` references and let `.env.local` (gitignored) hold the actual secrets.
- The default master key is `sk-mock` for ease of local use. Change it before exposing the proxy on a non-loopback address.
- The mock judge does deterministic pattern inspection of the response envelope as a stand-in for an LLM. Do not use it for real evaluation — its decisions cannot represent a real judge's calibration.
