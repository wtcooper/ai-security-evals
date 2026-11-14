# Multi-agent systems and subagents — threat and test template

Generated from `templates/multi-agent.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: one model, one context, one set of permissions, one transcript. After: an orchestrator hands tasks, context and sometimes credentials to other agents and treats what they return as input to its next step.
- Messages between agents are model-written text. A subagent that read untrusted content can pass an injection upward or sideways.
- Agents can hold different tools and permissions, so delegation can widen what one request reaches.
- No single transcript shows the whole action, and errors compound across hops.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- Which agents exist, what tools and permissions does each hold, and who can add one?
- Are any agents run by another party or on another vendor's model?
- What does an orchestrator pass down: the whole context, or only the task?

## Threats

### ma-01 An injection spreads from agent to agent

One agent reads planted content and its output carries the instruction to the orchestrator or to peers, possibly copying itself onward.

OWASP LLM: LLM01:2025 Prompt Injection · OWASP Agentic: ASI07 Insecure Inter-Agent Communication, ASI01 Agent Goal Hijack · MITRE ATLAS: AML.T0143 LLM Prompt Propagation, AML.T0061 LLM Prompt Self-Replication, AML.T0051.001 LLM Prompt Injection: Indirect

Review questions

1. Which agents read untrusted content, and what do they return to others?
2. Does a receiving agent treat another agent's output as data or as instruction?

Vendor evidence to look for

- Testing of injection across agent boundaries.
- How inter-agent messages are framed to the model.

Existing benchmarks

- **TAMAS** (arXiv 2511.05269). Robustness of multi-agent LLM systems: five scenarios, 300 adversarial instances across six attack types, 100 harmless tasks, on AutoGen and CrewAI configurations. Research code; no skill in this repo runs it. Limits: Open frameworks, not a vendor's orchestration.

No standardized test for

- The vendor's own orchestration. Public work uses open frameworks, not a given product.

### ma-02 Delegation widens privileges

A low-privilege agent gets a higher-privilege one to act for it, or subagents inherit the orchestrator's credentials.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI03 Identity and Privilege Abuse

Review questions

1. Does each agent have its own identity and the narrowest permissions for its job?
2. Are credentials passed down, and are they scoped to the subtask?

Vendor evidence to look for

- The identity and permission model for subagents.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Design review. No benchmark of a product's delegation model.

### ma-03 A message or an agent is not who it claims to be

Messages between agents are not authenticated, or an unknown agent joins and is trusted.

OWASP Agentic: ASI07 Insecure Inter-Agent Communication · MITRE ATLAS: AML.T0073 Impersonation

Review questions

1. How does an agent know which agent sent a message?
2. Who can register an agent, and is there an allowlist?

Vendor evidence to look for

- Authentication between agents and of remote agents.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test.

### ma-04 One failure cascades

An error, a loop or a compromised agent is amplified through the chain: repeated actions, runaway cost, wide damage.

OWASP LLM: LLM10:2025 Unbounded Consumption · OWASP Agentic: ASI08 Cascading Failures · MITRE ATLAS: AML.T0034.002 Cost Harvesting: Agentic Resource Consumption

Review questions

1. What limits depth, fan-out, retries and spend?
2. What stops a chain when one agent misbehaves?

Vendor evidence to look for

- Documented limits and circuit breakers.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test.

### ma-05 Context is over-shared between agents

The orchestrator passes its whole context, including secrets and personal data, to a subagent that has outbound tools or runs elsewhere.

OWASP LLM: LLM02:2025 Sensitive Information Disclosure

Review questions

1. What context does each subagent receive?
2. Do any subagents run on another vendor's infrastructure?

Vendor evidence to look for

- How context is partitioned between agents.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Design review.

### ma-06 Nobody can say which agent did what

Logs are split per agent, approvals attach to the wrong step, and an agent acting outside its role goes unnoticed.

OWASP Agentic: ASI10 Rogue Agents

Review questions

1. Is there one trace across all agents for a request?
2. Where do human approvals sit, and what do they show?

Vendor evidence to look for

- Tracing and audit features across agents.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test. Record what is in place.

### ma-07 Agents supplied by others

An agent you call is built or operated by a third party, and can change.

OWASP LLM: LLM03:2025 Supply Chain · OWASP Agentic: ASI04 Agentic Supply Chain Vulnerabilities

Review questions

1. Which agents come from outside, and who vets them?
2. Are their versions pinned?

Vendor evidence to look for

- Provenance and review of third-party agents.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org/llm-top-10/ (read 2026-11-14); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
