# Promptfoo Quick-Start Guide

Promptfoo has two independent modes. Pick the one you need:

| Mode | Command | Purpose |
|------|---------|---------|
| **Eval** | `promptfoo eval` | Test model quality — correctness, tone, LLM-judged rubrics |
| **Red team** | `promptfoo redteam run/eval` | Adversarial security testing — jailbreaks, injection, policy violations |

Both point at whatever model you want — a local Ollama model, a gateway, a cloud API, or any HTTP endpoint. The examples here use a local LiteLLM gateway by default, but see [Connecting to your model](#connecting-to-your-model) to swap that out.

---

## Prerequisites

```bash
npx promptfoo@latest --version       # 0.120+ recommended
# Plus whatever serves your model, e.g. one of:
ollama list                          # local Ollama running + models pulled
bash targets/proxy/start_proxy.sh &  # (optional) LiteLLM gateway on :4000
```

---

## Connecting to your model

Promptfoo doesn't care *how* your model is served — you just set the provider/target
`id` and `config`. Three common ways (each template includes these as commented alternatives):

**1. Local Ollama, directly** (no gateway — simplest for local-only):

```yaml
# eval:   providers:    redteam: targets:
- id: ollama:chat:llama3.3      # ollama:chat:<model>  (or ollama:completion:<model>)
  # base URL defaults to http://localhost:11434; override with OLLAMA_BASE_URL env
```

**2. Through a gateway / any OpenAI-compatible API** (LiteLLM, vLLM, OpenAI, Together…):

```yaml
- id: openai:chat                # OpenAI-compatible wire format
  config:
    apiBaseUrl: http://localhost:4000/v1   # LiteLLM gateway here; swap for any OpenAI-style URL
    apiKey: sk-mock                         # real key for a cloud provider
    model: gemma4:e2b
```

**3. Any HTTP endpoint** (your own app/agent behind a REST API):

```yaml
- id: https
  config:
    url: https://your-app.example.com/chat
    method: POST
    headers: { 'Content-Type': 'application/json' }
    body: { message: '{{prompt}}' }
    transformResponse: 'json.reply'   # JS expression to pull the text out of the response
```

The gateway approach (#2) is handy when you want one place to manage keys, add
guardrails, or A/B local vs cloud — but it's optional.

---

## Docs in this folder

| File | What it covers |
|------|---------------|
| [01-evals.md](01-evals.md) | LLM-as-judge evals: rubric scoring, multi-model comparison, assertion types |
| [02-redteam.md](02-redteam.md) | Red teaming: cloud vs local vs cached-goals modes, the generate/run/eval phases, strategies |
| [templates/](templates/) | Copy-paste template configs, fully commented, one per mode |

---

## The three run modes (applies to red teaming)

| Mode | How | What touches the cloud |
|------|-----|------------------------|
| **Community** | default, logged in or anonymous | Attack generation + some grading use promptfoo's hosted service (free, ≤10k probes/mo) |
| **Local** | `PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true` | Nothing — generation, attacks, and grading all run on local Ollama models |
| **Enterprise** | self-hosted / managed cloud | Same API; adds SSO, audit logs, team dashboards, shared results |

Evals don't require the cloud at all unless you use promptfoo's hosted grader; with a
local `defaultTest.options.provider` they're fully offline.

---

## Glossary

**PASS** — model behaved safely (attack failed) or response was correct  
**FAIL** — model was vulnerable (attack succeeded) or response was wrong

**`redteam generate`** — generate attack objectives only → writes a `redteam.yaml` you can re-run  
**`redteam run`** — `generate` + `eval` in one step (always re-syncs tests to your config)  
**`redteam eval`** — evaluate only, from an existing `redteam.yaml` (no generation)

**Target** — the model under test  
**Attacker** — the LLM driving crescendo's multi-turn escalation (not the target)  
**Scorer / grader** — the LLM judging pass/fail (not the target)

**Crescendo** — multi-turn escalation attack; needs an attacker model + a `goal`  
**Basic** — single direct probe per objective; no attacker model needed
