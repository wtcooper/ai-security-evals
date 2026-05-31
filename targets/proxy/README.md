# targets/proxy — shared LiteLLM AI gateway

The LiteLLM proxy is the **shared AI gateway** for this repo: the test apps in
`targets/` point their OpenAI `base_url` at it, and the eval skills can target it
directly. It centralizes model routing and guardrails in one place, so you can A/B/C
controls by name without touching the apps. It runs as a local process on port 4000 —
**no remote service to deploy**.

> **Security:** pin a safe LiteLLM version. Versions **1.82.7 / 1.82.8** were malicious
> (March 2026 supply-chain incident); safe ranges are **≤1.82.6** or **≥1.83.0**. This
> repo pins `litellm[proxy]>=1.85.1,<2` (safe). Never commit real keys — use
> `os.environ/...` refs and put secrets in `.env.local` (gitignored).

## Files
| File | What it does |
|---|---|
| `litellm_config.yaml` | model_list (mocks + real examples), guardrails, custom provider map |
| `mock_handlers.py` | `MockTargetLLM`, `MockJudgeLLM`, `MockResponseHandler`, `MockBlockGuardrail` |
| `start_proxy.sh` | starts the proxy with the config + handler module path resolved |

## Quick start
```bash
uv sync                              # once
bash targets/proxy/start_proxy.sh &  # gateway on :4000
curl -s http://localhost:4000/health/readiness
```

## Guardrails (LiteLLM-bundled, no vendor account)
| Name | Type | Block signal | Notes |
|---|---|---|---|
| `content-filter` | `litellm_content_filter` (bundled, local) | **HTTP 403** | Regex PII (SSN/email → MASK) + banned keywords (`confidential` → BLOCK). Toggle per request. |
| `mock-guardrail` | custom (`MockBlockGuardrail`) | HTTP 400 | Blocks obvious adversarial substrings; for wiring/demo. |
| `presidio-pii` _(commented)_ | `presidio` | — | Local, but needs analyzer + anonymizer sidecar containers. |
| `detect_prompt_injection` _(commented)_ | global callback | — | Local similarity check; **global, not per-request** — breaks A/B/C toggling, so off by default. |
| Lakera / Bedrock / Azure _(commented)_ | SaaS | varies | Need a vendor account; examples in the config. |

Guardrails are **named, not `default_on`**, so the skills toggle them per request:
```bash
curl -s http://localhost:4000/v1/chat/completions -H 'Authorization: Bearer sk-mock' \
  -H 'Content-Type: application/json' \
  -d '{"model":"mock-target-compliant","guardrails":["content-filter"],
       "messages":[{"role":"user","content":"this is confidential"}]}'   # -> HTTP 403 block
```
Set `default_on: true` on a guardrail to enforce it on every request (apps can't opt out).

> **Block status note:** LiteLLM's `content-filter` blocks with **HTTP 403** (the mock
> guardrail uses 400). The skills classify **body-first**, so the 403 block is detected
> automatically from its body (`guardrail_name` + "Content blocked" message) — **no
> `GUARDRAIL_BLOCK_STATUSES` needed.** Each run prints a per-status histogram so you can
> see exactly what came back and how it was bucketed.

## Using the gateway from a test app
Point the app's OpenAI client at the proxy and use a `model_name` from `model_list`:
```
OPENAI_BASE_URL=http://localhost:4000/v1
OPENAI_API_KEY=sk-mock
# model: mock-target-compliant   (or a real model you add below)
```
Bind a guardrail to a model so any app using it is covered automatically:
```yaml
model_list:
  - model_name: gpt-4o-mini
    litellm_params: { model: openai/gpt-4o-mini, api_key: os.environ/OPENAI_API_KEY }
      # guardrails: ["content-filter"]   # per-model binding
```

## Mock models (zero keys)
| Mock | Simulates |
|---|---|
| `mock-target-compliant` | answers anything (COMPLIANCE) |
| `mock-target-refusal` | refuses everything (REFUSAL) |
| `mock-target-policy-block` | HTTP 400 policy-block envelope (CONTROL_BLOCK) |
| `mock-judge` | deterministic judge stand-in (do not use for real evals) |

Mocks prove wiring only — swap in real models (and a real judge) for real evaluation.
