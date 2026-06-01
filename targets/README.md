# targets — test apps + the shared AI gateway

Things to point the eval skills at. The **gateway** centralizes models and guardrails;
the **apps** are deliberately-vulnerable targets the team practices on (API + web UI).

| Directory | What it is | Use with |
|---|---|---|
| [`proxy/`](proxy/) | **Shared LiteLLM AI gateway** (:4000) — mock models + bundled content-safety guardrails (`content-filter`), real models/guardrails by config. The apps point their model `base_url` here. | all skills; the model/guardrail backend for the apps |
| [`aigoat/`](aigoat/) | **AIGoat** (adopt) — React UI + FastAPI, full OWASP LLM Top 10, **defense levels 0/1/2**. Rich realistic target with both surfaces. | `app-eval`, `app-redteam` (API + browser UI); A/B/C via defense levels |
| [`dvaa/`](dvaa/) | **DVAA** (adopt) — OpenAI-compatible + MCP, ships a mock LLM (zero keys). Strong agent/MCP attack surface. | `app-eval`, `app-redteam` (API); `control-bench` (MCP) |

The apps are **not vendored** (separate Apache-2.0 repos); each subdir has clone + run +
skill-wiring instructions. The proxy **is** in-repo.

## How the pieces fit
```
            ┌─────────────┐        ┌──────────────────────┐
 eval skill │ app-eval    │  HTTP  │ test app (AIGoat/DVAA)│  OpenAI   ┌───────────────┐
 (promptfoo)│ app-redteam │ ─────► │  web UI + backend API │ ────────► │ targets/proxy │ ──► model
            │ control-*   │        └──────────────────────┘  base_url  │ (LiteLLM)     │
            └─────────────┘              ▲                              │  + guardrails │
                  │ browser provider     │ Playwright                   └───────────────┘
                  └──────────────────────┘ (web UI)
```
- Skills hit the **app's API** (HTTP provider) or its **web UI** (browser provider).
- The app calls models through the **proxy**, where guardrails are toggled by name —
  so "control on/off" is one place, testable as A/B/C.

## Block detection
The skills classify each response **body-first** (block signals like `action:block` /
`guardrail_name` / "content blocked"), with the HTTP status only as a hint — so a new
vendor's block code (e.g. LiteLLM's **403** content-filter) is caught automatically with
no config. Operational failures (5xx/429/auth) are excluded; truly unmappable responses
are surfaced loudly. Every run prints a per-status histogram.

## Roadmap: a "house" target
A minimal **Next.js + FastAPI (OpenAI-compatible) + LangChain `create_agent` + FastMCP**
vulnerable agent — owned in-repo, exercising all four skills + the browser UI from one
app — is the planned canonical demo target (see `docs/skills-redesign-plan.md`).
