# targets/aigoat — AIGoat (realistic vulnerable LLM app)

[**AIGoat**](https://github.com/AISecurityConsortium/AIGoat) (AISecurityConsortium,
Apache-2.0) is a deliberately-vulnerable LLM e-commerce app: a **React UI (:3000)** and a
**separable FastAPI backend (:8000, OpenAPI at `/docs`)**, covering the full OWASP LLM
Top 10 (17 labs: prompt injection, sensitive-info disclosure, RAG/vector weaknesses,
**excessive agency / tool calling**, system-prompt leakage, insecure output handling, …).

It is **not vendored here** (separate repo, ~12 GB RAM, Ollama). This directory documents
how to run it and point the skills at both its **API** and its **web UI**.

## Why it's a great target for these skills
- **Both surfaces:** FastAPI API (for `app-eval` / `app-redteam` HTTP provider) **and** a
  React chat UI (for the **browser-provider** UI testing — `promptfooconfig.browser.yaml`).
- **Defense levels 0/1/2** (vulnerable → hardened → NeMo guardrails) map directly onto
  A/B/C control testing: run the same corpus at each level and diff F1/recall/FPR.

## Run it
```bash
git clone https://github.com/AISecurityConsortium/AIGoat
cd AIGoat && docker-compose up --build      # UI :3000, API :8000 (see /docs)
```
Set the defense level per its docs (env/flag) to get the 0/1/2 arms.

### Optional: route its LLM through our shared proxy
AIGoat uses Ollama by default. To centralize models/guardrails, point its LLM backend at
`targets/proxy` (OpenAI-compatible): set its model base URL to `http://localhost:4000/v1`,
key `sk-mock`, and a `model_name` from the proxy `model_list`. Then a proxy guardrail
(e.g. `content-filter`) applies underneath — another A/B/C lever.

## Point the skills at it
**Backend API** (`app-eval` / `app-redteam`): set `TARGET_URL` to AIGoat's chat endpoint
(find the exact route in `http://localhost:8000/docs`) and edit `providers[0].config.body`
to its request schema. Build the corpus and run as usual.

**Web UI** (`app-eval` browser variant): use `promptfooconfig.browser.yaml`, set
`TARGET_UI_URL=http://localhost:3000`, and adjust the chat selectors (input box, submit,
assistant-message) to AIGoat's DOM.

**A/B/C across defense levels:** run the same tier three times (levels 0/1/2) into three
`results.json` files and diff with the bundled `lib/summarize.py`.

## Notes
- License: Apache-2.0 (code) / CC BY-NC-SA-4.0 (content). Needs ~12 GB RAM + Ollama.
- No OpenAI-compatible endpoint of its own — target it as a **custom HTTP** app (the
  shared `transform_response.js` handles arbitrary body/response shapes).
