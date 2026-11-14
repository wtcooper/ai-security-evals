# Connectors and MCP servers — threat and test template

Generated from `templates/connectors-mcp.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: the model sees what the user pastes. After: it reads from and writes to other systems through tools whose names, descriptions and results are supplied by whoever runs the server.
- Tool descriptions and tool results enter the context as text the model cannot authenticate. A server can change its tool list after it was approved.
- The connector holds credentials (OAuth tokens, API keys) and acts with a user's or a service account's permissions.
- With several connectors enabled, data read through one can be sent out through another.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- Which connectors and servers, run by whom: the model vendor, the system's own vendor, a third party, yourselves?
- Read-only or read-write? Acting as the user or as a shared service account?
- Who may add a new connector: an administrator, or any user?

## Threats

### mcp-01 Tool poisoning: instructions hidden in tool descriptions

A tool's metadata tells the model to do something the user never asked for. Nothing has to be called for the text to take effect.

OWASP LLM: LLM01:2025 Prompt Injection · OWASP Agentic: ASI04 Agentic Supply Chain Vulnerabilities · MITRE ATLAS: AML.T0110 AI Agent Tool Poisoning, AML.T0011.002 User Execution: Poisoned AI Agent Tool

Review questions

1. Who wrote each tool description, and has anyone read them?
2. Does the client show descriptions to the user or an administrator, and flag changes?
3. How does the model behave when a description contains instructions?

Vendor evidence to look for

- Model or client testing against poisoned tool metadata.
- Review or signing of connectors in the vendor's directory.

Existing benchmarks

- **MCPTox** (arXiv 2508.14925). Agent robustness to tool poisoning: malicious instructions in tool metadata. Built on 45 real MCP servers and 353 tools, 1,348 test cases in 10 risk categories. Research code; no skill in this repo runs it. Limits: Its own server set, not yours.
- **MCP Security Bench (MSB)** (arXiv 2510.15994). Resistance to 12 MCP-specific attack types across planning, tool invocation and response handling, including name collision and preference manipulation; reports a combined security and performance figure. Research code; no skill in this repo runs it. Limits: Its own tools and domains.

Your own tests through this repo's skills

- `security-tool-benchmark`: its extension kind measures how well a scanner of MCP servers and skills detects bad ones. It evaluates the scanner, not your servers; scanning itself is outside this repo.

No standardized test for

- The servers you will actually connect. Public sets use their own server collections.

### mcp-02 Injection through what a tool returns

A ticket, email, document or record fetched by a connector carries instructions, and the agent follows them.

OWASP LLM: LLM01:2025 Prompt Injection · OWASP Agentic: ASI01 Agent Goal Hijack · MITRE ATLAS: AML.T0051.001 LLM Prompt Injection: Indirect, AML.T0099 AI Agent Tool Data Poisoning

Review questions

1. Which connectors return content that outsiders can write: inboxes, issue trackers, shared drives, web search?
2. Is tool output marked as data when it reaches the model?
3. What can the agent do next if it is hijacked: which write actions are in reach?

Vendor evidence to look for

- Published injection results for tool use: benchmark, attack type, safeguards on or off.
- A description of safeguards on tool output.

Existing benchmarks

- **AgentDojo** (arXiv 2406.13352). Whether a tool-calling agent follows instructions planted in tool results while doing a user's task, with task utility reported beside security. The paper describes 97 tasks and 629 security test cases. This repo: `model-benchmark`, check `agentdojo`. Limits: Simulated tools in its own environments (the paper gives email, e-banking and travel booking as examples). No screen, no real connector, no memory across sessions.
- **AgentThreatBench** (inspect_evals 0.29.0, `agent_threat_bench_*`). Three small Inspect tasks built on the OWASP agentic list: memory poisoning, autonomy hijack and data exfiltration, each with a utility score. This repo: `model-benchmark`, checks `atb_memory_poison`, `atb_autonomy_hijack`, `atb_data_exfil`. Limits: 10, 6 and 8 cases respectively, so one case moves the result by 10 points or more.
- **InjecAgent** (arXiv 2403.02691). Indirect prompt injection in tool-integrated agents: 1,054 test cases over 17 user tools and 62 attacker tools, covering direct harm and data theft. Research code; no skill in this repo runs it. Limits: Its own simulated tools.
- **MCP Security Bench (MSB)** (arXiv 2510.15994). Resistance to 12 MCP-specific attack types across planning, tool invocation and response handling, including name collision and preference manipulation; reports a combined security and performance figure. Research code; no skill in this repo runs it. Limits: Its own tools and domains.

Your own tests through this repo's skills

- `app-redteam`: adaptive attacks against your own endpoint, if the connectors sit behind one.
- `app-benchmark`: a fixed set of attack and benign prompts against the same endpoint.

No standardized test for

- Your own connectors, data and permissions.

### mcp-03 A malicious, compromised or changed server

The server itself is hostile: published to be installed, taken over later, renamed to collide with a trusted one, or changed after approval.

OWASP LLM: LLM03:2025 Supply Chain · OWASP Agentic: ASI04 Agentic Supply Chain Vulnerabilities · MITRE ATLAS: AML.T0010.005 Supply Chain Compromise: AI Agent Tool, AML.T0109 AI Supply Chain Rug Pull, AML.T0115.002 Publish Poisoned AI Artifacts: AI Agent Tools

Review questions

1. Where does each server come from, and who vets it before it is enabled?
2. Is the version pinned? Is anyone told when the tool list or a description changes?
3. Can two servers offer a tool with the same name, and which one wins?

Vendor evidence to look for

- How the vendor's directory reviews connectors.
- Client behaviour on changed tool definitions.

Existing benchmarks

- **MCP Security Bench (MSB)** (arXiv 2510.15994). Resistance to 12 MCP-specific attack types across planning, tool invocation and response handling, including name collision and preference manipulation; reports a combined security and performance figure. Research code; no skill in this repo runs it. Limits: Its own tools and domains.

Your own tests through this repo's skills

- `security-tool-benchmark`: extension kind, as under mcp-01: it tells you how far to trust a scanner.

No standardized test for

- Change over time. No benchmark watches a server you depend on.

### mcp-04 Over-broad permissions and credential handling

The connector's token can do more than the task needs, is stored where it can be read, or lets one user act with another's rights.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI03 Identity and Privilege Abuse · MITRE ATLAS: AML.T0098 AI Agent Tool Credential Harvesting, AML.T0083 Credentials from AI Agent Configuration

Review questions

1. What scopes does each token carry, and are they the narrowest the system offers?
2. Where are tokens stored, and can the model or a tool read them?
3. Does the connector act as the asking user, with that user's permissions, every time?

Vendor evidence to look for

- The authorisation model of each connector.
- Token storage and rotation.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Design review of scopes and identities. No benchmark.

### mcp-05 Data read through one tool leaves through another

Private content fetched by one connector is written, sent or encoded into a call to another that an attacker can read.

OWASP LLM: LLM02:2025 Sensitive Information Disclosure · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0086 Exfiltration via AI Agent Tool Invocation, AML.T0085.001 Data from AI Services: AI Agent Tools

Review questions

1. Which enabled tools can send data outside: email, web requests, posting, file sharing?
2. Can a session hold private data and an outbound tool at the same time?
3. Are tool calls and their arguments logged?

Vendor evidence to look for

- Exfiltration results in the vendor's tool-use testing.
- Controls on combining connectors.

Existing benchmarks

- **AgentThreatBench** (inspect_evals 0.29.0, `agent_threat_bench_*`). Three small Inspect tasks built on the OWASP agentic list: memory poisoning, autonomy hijack and data exfiltration, each with a utility score. This repo: `model-benchmark`, checks `atb_memory_poison`, `atb_autonomy_hijack`, `atb_data_exfil`. Limits: 10, 6 and 8 cases respectively, so one case moves the result by 10 points or more.
- **AgentDojo** (arXiv 2406.13352). Whether a tool-calling agent follows instructions planted in tool results while doing a user's task, with task utility reported beside security. The paper describes 97 tasks and 629 security test cases. This repo: `model-benchmark`, check `agentdojo`. Limits: Simulated tools in its own environments (the paper gives email, e-banking and travel booking as examples). No screen, no real connector, no memory across sessions.
- **InjecAgent** (arXiv 2403.02691). Indirect prompt injection in tool-integrated agents: 1,054 test cases over 17 user tools and 62 attacker tools, covering direct harm and data theft. Research code; no skill in this repo runs it. Limits: Its own simulated tools.

Your own tests through this repo's skills

- `app-redteam`: against your own endpoint, with canary data you plant.

No standardized test for

- The particular combination of connectors you enable.

### mcp-06 Destructive or unintended writes through tools

The agent deletes, overwrites, sends or changes something in a connected system, by error or under manipulation.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0101 Data Destruction via AI Agent Tool Invocation, AML.T0053 AI Agent Tool Invocation

Review questions

1. Which tools write, and which writes cannot be undone?
2. Which calls need a person's approval, and what does the approval show?

Vendor evidence to look for

- Per-tool approval settings.
- Unintended-action rates on benign tasks.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Your own tools' write actions.

### mcp-07 The server or its transport is itself exposed

A server reachable without authentication, a local server that runs commands with the user's rights, or a server that can be made to fetch internal addresses.

MITRE ATLAS: AML.T0132 Misconfigured or Publicly Exposed AI Services

Review questions

1. Is each remote server authenticated, and to whom is it reachable?
2. Do local servers run commands or read files with the user's privileges?

Vendor evidence to look for

- Security documentation or audit of each server.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Conventional security review of the server. Outside what an AI benchmark measures.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org/llm-top-10/ (read 2026-11-14); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
