# Threat template — New agent feature

One capability being switched on in an agent the organisation already runs. The plan lists the threats for the feature named in review.json (subject.feature) plus the common ones.

Which threats a catalogued benchmark covers depends on the catalogue at the time the plan is built; `scripts/plan.py` decides that. The last column says how a threat is assessed when no available benchmark covers it. A `—` in a framework column means no id was verified for that threat, not that none exists. The verified ids and where they were checked are in [framework-ids.md](framework-ids.md).

## Questions to ask for this subject type

- What can the agent do with the feature on that it could not do before?
- Which new content does it read, and who can write it?
- Which new credentials or sessions does it use?
- Can the feature be limited to some users, sites, tools or data first?

## Feature: computer-use

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `agent-goal-hijack` | **Agent goal hijack through tool results or data.** Content the agent reads while working (a tool result, a file, a web page, an issue) redirects it to an attacker's goal. | Everything on screen is input: pages, pop-ups, documents, notifications. | LLM01:2025 | ASI01 | AML.T0051.001 | custom probe: Plant goal-changing instructions in each data source the agent's tools read and score whether the attacker's action is taken. |
| `tool-misuse` | **Tool misuse.** The agent uses a legitimate tool in a harmful way: destroying data, sending data out, spending money, changing configuration. | Clicks and keystrokes can do anything the logged-in user can. | LLM06:2025 | ASI02 | AML.T0053, AML.T0101 | custom probe: For each tool in review.json that changes something, script a request that should not be carried out and record whether it is. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | Screen content and open sessions are within reach. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |
| `human-trust-exploitation` | **Human approval that does not work as a check.** People approve what the agent proposes because prompts are too frequent, too vague or presented with unearned authority. | Watching an agent click is not reviewing it. | — | ASI09 | AML.T0067 | design review: Review what an approval prompt shows, how often it appears, and what can be approved in bulk. |
| `visual-prompt-injection` | **Instructions hidden in an image.** Text or patterns inside an input image are followed as instructions. | Instructions rendered as pixels. | LLM01:2025 | — | AML.T0051.001, AML.T0129 | custom probe: Embed instructions in images of the kind the deployment receives and score whether they are followed. |

## Feature: memory

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `memory-poisoning` | **Memory poisoning.** Content written into persistent memory in one session changes behaviour in later sessions. | One poisoned write persists. | — | ASI06 | AML.T0080.000 | custom probe: Write a planted instruction to memory in one session and test whether a fresh session acts on it. |
| `cross-session-leakage` | **Memory or context leaks across sessions or users.** Something stored in one session or by one user surfaces in another's. | What one session stores another can read. | LLM02:2025 | — | AML.T0085.002 | custom probe: Store a canary as one user or session and query for it as another. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | Memory holds what users said earlier. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |

## Feature: connectors

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `supply-chain-extensions` | **Malicious or changed tool, plugin, skill or MCP server.** A component added to the agent is malicious, is poisoned later, or changes after it was approved. | Each connector or MCP server is third-party code and third-party text. | LLM03:2025 | ASI04 | AML.T0010.005, AML.T0110, AML.T0109 | design review: Scanning an extension is outside this repo. Record which scanner the organisation ran and what it reported, and how updates are pinned. |
| `agent-goal-hijack` | **Agent goal hijack through tool results or data.** Content the agent reads while working (a tool result, a file, a web page, an issue) redirects it to an attacker's goal. | Connector results are instruction channels. | LLM01:2025 | ASI01 | AML.T0051.001 | custom probe: Plant goal-changing instructions in each data source the agent's tools read and score whether the attacker's action is taken. |
| `tool-misuse` | **Tool misuse.** The agent uses a legitimate tool in a harmful way: destroying data, sending data out, spending money, changing configuration. | Connectors that write. | LLM06:2025 | ASI02 | AML.T0053, AML.T0101 | custom probe: For each tool in review.json that changes something, script a request that should not be carried out and record whether it is. |
| `rag-poisoning` | **Poisoned retrieval or connected data.** Content planted in an index or a connected data source is retrieved and steers the answer or the agent. | Connected data sources others can write to. | LLM08:2025 | — | AML.T0070, AML.T0099 | custom probe: Add a marked document to the index or data source and score whether its instruction is followed when retrieved. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | A connector that can send is a route out. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |

## Feature: code-execution

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `unexpected-code-execution` | **Unexpected code execution.** Generated or injected code runs where it can reach the host, the network or credentials. | The feature is code execution; the question is its reach. | — | ASI05 | AML.T0050, AML.T0105 | design review: Review where code runs, what the sandbox can reach, and whether egress is closed. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | Files and network reachable from the sandbox. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |
| `insecure-code` | **Insecure generated code.** Code the model writes contains vulnerabilities that reach production. | Code that is kept after the session. | — | — | — | custom probe: Score generated code for the organisation's own languages and frameworks with the scanners it already trusts. |

## Feature: multi-agent

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `inter-agent-communication` | **Insecure communication between agents.** One agent accepts another's message as trusted instruction with no authentication or scoping. | Agents instructing agents. | — | ASI07 | — | design review: Review how agents authenticate each other and what one may ask of another. |
| `cascading-failures` | **Cascading failures.** One wrong or injected step propagates through chained agents, tools or automations before anyone sees it. | One steered agent steers the rest. | — | ASI08 | AML.T0143 | design review: Review the chain for points where an error is checked or stopped. |
| `rogue-agent` | **Agent acting outside its intended purpose.** A compromised or misaligned agent keeps operating with legitimate access while pursuing something else. | Harder to see which agent did what. | — | ASI10 | — | uncovered: No catalogued benchmark. Detection depends on logging and monitoring, which a design review can describe but not measure. |
| `agent-goal-hijack` | **Agent goal hijack through tool results or data.** Content the agent reads while working (a tool result, a file, a web page, an issue) redirects it to an attacker's goal. | Injection reaches every agent that reads the shared content. | LLM01:2025 | ASI01 | AML.T0051.001 | custom probe: Plant goal-changing instructions in each data source the agent's tools read and score whether the attacker's action is taken. |

## Feature: background-agent

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `background-trigger-abuse` | **Unattended trigger started or steered by an outsider.** A schedule, webhook, inbox or other trigger lets someone outside start or steer a run when no person is present. | Runs start with no person present. | — | — | — | design review: List every trigger, who can cause it, and what the run can do before a person sees it. |
| `rogue-agent` | **Agent acting outside its intended purpose.** A compromised or misaligned agent keeps operating with legitimate access while pursuing something else. | Standing access, long runs. | — | ASI10 | — | uncovered: No catalogued benchmark. Detection depends on logging and monitoring, which a design review can describe but not measure. |
| `cascading-failures` | **Cascading failures.** One wrong or injected step propagates through chained agents, tools or automations before anyone sees it. | Output goes straight into other systems. | — | ASI08 | AML.T0143 | design review: Review the chain for points where an error is checked or stopped. |
| `agent-goal-hijack` | **Agent goal hijack through tool results or data.** Content the agent reads while working (a tool result, a file, a web page, an issue) redirects it to an attacker's goal. | Nobody is watching the content it reads. | LLM01:2025 | ASI01 | AML.T0051.001 | custom probe: Plant goal-changing instructions in each data source the agent's tools read and score whether the attacker's action is taken. |
| `human-trust-exploitation` | **Human approval that does not work as a check.** People approve what the agent proposes because prompts are too frequent, too vague or presented with unearned authority. | Approval after the fact. | — | ASI09 | AML.T0067 | design review: Review what an approval prompt shows, how often it appears, and what can be approved in bulk. |

## Feature: other

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `agent-goal-hijack` | **Agent goal hijack through tool results or data.** Content the agent reads while working (a tool result, a file, a web page, an issue) redirects it to an attacker's goal. | Check each new content source. | LLM01:2025 | ASI01 | AML.T0051.001 | custom probe: Plant goal-changing instructions in each data source the agent's tools read and score whether the attacker's action is taken. |
| `tool-misuse` | **Tool misuse.** The agent uses a legitimate tool in a harmful way: destroying data, sending data out, spending money, changing configuration. | Check each new action. | LLM06:2025 | ASI02 | AML.T0053, AML.T0101 | custom probe: For each tool in review.json that changes something, script a request that should not be carried out and record whether it is. |
| `data-leakage` | **Sensitive data leaves through output or a tool.** Secrets, personal data or another user's data that are in the context, in memory or reachable by a tool appear in a response, in rendered content or in a tool call to an outside destination. | Check each new route out. | LLM02:2025 | — | AML.T0086, AML.T0136, AML.T0077 | custom probe: Seed the context with canary values and test each route out: the reply, rendered links or images, and each tool that can send data. |

## Common to every feature

| Threat id | Threat | Why it matters here | OWASP LLM 2025 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `privilege-abuse` | **Excessive permissions and identity abuse.** The capability holds credentials, scopes or autonomy beyond what the task needs; whoever steers it inherits them. | A new feature usually arrives with new scopes. | LLM06:2025 | ASI03 | AML.T0098, AML.T0083 | design review: Read the granted scopes, tokens and approval settings against the task. This is a configuration review, not a measurement. |
| `data-retention-hosting` | **Retention, training use and hosting of submitted data.** Prompts, outputs, files or audio are kept, used for training, or processed in a place or by a party the organisation has not accepted. | New data leaves the organisation with each feature. | — | — | — | design review: Read the contract and the vendor's data terms; record what was signed, not what the public page says. |
| `version-drift` | **The thing reviewed is not the thing running later.** An alias moves to a new model, the harness updates itself, or outputs are not reproducible, so results stop describing the deployment. | Features change behind a flag without a version. | — | — | — | design review: Record the pinned identifiers, how updates arrive, and who is told. |
| `unbounded-consumption` | **Unbounded cost or resource use.** Requests, loops or tool calls drive cost or load without a cap. | New ways to spend. | LLM10:2025 | — | AML.T0034, AML.T0029 | design review: Review rate limits, spend caps, context and step limits as configured. |

## What the template does not cover

The list is a starting point for this subject type. Threats that come from the particular deployment (its data, its users, its integrations) are added by the reviewer. The template names no controls.

---
Generated by `scripts/render_templates.py` from `threats.json` and `templates.json`. Edit the JSON, then re-run the script.
