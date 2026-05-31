# targets/dvaa — Damn Vulnerable AI Agent (zero-key MCP target)

[**DVAA**](https://github.com/opena2a-org/damn-vulnerable-ai-agent) (opena2a, Apache-2.0)
is "DVWA for AI agents": 15 agents with varying security postures exposing
**OpenAI-compatible chat endpoints (:7001–7008)**, **MCP JSON-RPC (:7010–7013)**, A2A
(:7020–7021), and a dashboard (:9000). It **ships a simulated LLM backend — zero API keys
required** — so promptfoo can target it out of the box. Strongest **agent / MCP /
tool-poisoning** surface (prompt injection, jailbreak, data exfil, MCP exploitation, tool
registry poisoning, memory injection, …).

Best as the **fast, zero-dependency CI/demo target**, especially for MCP attack surface.
Not vendored here (separate repo, Node-centric).

## Run it
```bash
git clone https://github.com/opena2a-org/damn-vulnerable-ai-agent
cd damn-vulnerable-ai-agent && docker compose up    # dashboard :9000, agents :7001+
```

## Point the skills at it
**Backend API** (`app-eval` / `app-redteam`): the agents speak OpenAI — point
`TARGET_URL` at an agent's chat-completions endpoint (e.g. `http://localhost:7001/v1/chat/completions`)
and use the OpenAI body shape (the default `messages` body works). No judge mock needed;
use a real judge or the shared proxy's `mock-judge` for wiring.

**MCP / tool calling** (`control-bench`): point an Inspect agentic task or the injection
shim at DVAA's MCP endpoints (:7010+) to measure indirect-PI / tool-poisoning defense.

## Notes
- License: Apache-2.0. Ships a mock LLM → responses are scripted unless you wire a real
  model (you can route it through `targets/proxy` for real models + guardrails).
- Node-centric (not the Next.js + FastAPI house stack), and broader than you may need —
  but the most "drop-in" of the targets.
