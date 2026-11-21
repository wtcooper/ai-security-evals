# Computer use and browser control — threat and test template

Generated from `templates/computer-use.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: the model returns text and a person or your code decides what happens next. After: the model reads a screen it does not control (screenshots, page structure, accessibility tree) and issues clicks, keystrokes and navigation itself.
- Everything rendered is input: web pages, emails, adverts, documents, pop-ups, other people's content. None of it is authenticated as coming from the user.
- The agent acts as whoever the browser profile or desktop session is logged in as: cookies, single sign-on, saved passwords, local files, the clipboard.
- Actions are real, and many cannot be undone: send, buy, delete, submit, grant access.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- Where does it run: a vendor-hosted browser or VM, an isolated profile of yours, or the user's own desktop and browser?
- Which sites and applications can it reach, and which accounts are signed in there?
- Does a person watch each session, approve some steps, or neither?

## Threats

### cu-01 Instructions on screen take over the task

Text or images on a page, in an email or in a document tell the agent to do something else, and it complies. The attacker needs only to put content where the agent will look.

OWASP LLM: LLM01:2025 Prompt Injection · OWASP Agentic: ASI01 Agent Goal Hijack · MITRE ATLAS: AML.T0051.001 LLM Prompt Injection: Indirect, AML.T0100 AI Agent Clickbait, AML.T0129 Triggers in Multimodal Inputs

Review questions

1. Which of the places the agent looks can an outsider write to: the open web, an inbox, shared documents, adverts, comments?
2. What does the vendor do with instructions found on screen, and how was that tested: a fixed attack set, or attacks adapted to the defence?
3. What happens when on-screen text asks for an action outside the user's task?

Vendor evidence to look for

- Injection results for computer use specifically: which benchmark or attack set, static or adaptive, safeguards on or off, and the attack success rate that remains.
- A description of the safeguards: injection classifiers, confirmation prompts, blocked site categories.
- The vendor's own statement of residual risk for this feature.

Existing benchmarks

- **OS-Harm** (arXiv 2506.14866). Safety of computer-use agents in three categories: deliberate user misuse, prompt injection and model misbehaviour. 150 tasks on the OSWorld environment, scored by an automated judge. No skill in this repo runs it. It needs OSWorld virtual machines (execution tier T2). Limits: A fixed desktop image and static injections.
- **RedTeamCUA (RTC-Bench)** (arXiv 2505.21936). Indirect prompt injection against computer-use agents in a hybrid sandbox: a VM desktop plus Docker-hosted web platforms. 864 examples. No skill in this repo runs it. Needs VMs (T2). Limits: Its own web platforms.
- **WASP** (arXiv 2504.18575). End-to-end prompt injection against web agents, distinguishing partial from full attacker success. No skill in this repo runs it. Limits: Its own web environments.
- **VPI-Bench** (arXiv 2506.02456). Visual prompt injection: malicious instructions rendered in the interface, against computer-use and browser-use agents. 306 test cases on five platforms. No skill in this repo runs it. Limits: Its own platform variants.
- **CyberSecEval 3 visual prompt injection** (inspect_evals `cyse3_visual_prompt_injection`). Whether a model that reads images follows instructions placed in an image. A model-level test with no agent and no actions. An Inspect task. Run it through `vision-model-benchmark`, which runs a corrected version split by injection type, beside its own rendered core set. Limits: Says nothing about what an agent would then do.
- **AgentDojo** (arXiv 2406.13352). Whether a tool-calling agent follows instructions planted in tool results while doing a user's task, with task utility reported beside security. The paper describes 97 tasks and 629 security test cases. This repo: `model-benchmark`, check `agentdojo`. Limits: Simulated tools in its own environments (the paper gives email, e-banking and travel booking as examples). No screen, no real connector, no memory across sessions.

Your own tests through this repo's skills

- `app-redteam`: only if the feature sits behind an endpoint of yours that the skill can drive; it attacks through the prompt, not through the screen.

No standardized test for

- Your own sites, your own signed-in session and your own page content.
- Attacks adapted to the vendor's specific defence. Public suites are mostly static.

### cu-02 The agent acts with the session's signed-in privileges

Whatever the profile can reach, the agent can reach: internal applications, single sign-on, a password manager, payment methods.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI03 Identity and Privilege Abuse · MITRE ATLAS: AML.T0112.000 Machine Compromise: Local AI Agent

Review questions

1. Is the session a clean, isolated profile or the user's everyday one? What is signed in?
2. Can the agent enter credentials, approve a sign-in prompt, or grant an application access on the user's behalf?
3. Which steps hand control back to the person, and can the agent click through them?

Vendor evidence to look for

- Documentation of the execution environment and its isolation.
- What the agent is prevented from doing: credential entry, payments, consent screens.
- How take-over and confirmation modes work, and whether they can be turned off.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Privilege reach in your environment. This is a design review of your profile, accounts and network, not a benchmark.

### cu-03 Irreversible actions taken by mistake or under manipulation

The agent sends, buys, deletes, posts or submits something the user did not intend, through an ordinary interface used in an unintended way.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0053 AI Agent Tool Invocation

Review questions

1. Which actions in reach cannot be undone, and which of them need a person's confirmation?
2. Does the confirmation show what will actually happen, or the agent's description of it?
3. How often does the vendor report unintended actions on benign tasks?

Vendor evidence to look for

- Results on model misbehaviour or unintended actions for this feature, with benign-task completion beside them.
- The list of action types that always need confirmation.

Existing benchmarks

- **OS-Harm** (arXiv 2506.14866). Safety of computer-use agents in three categories: deliberate user misuse, prompt injection and model misbehaviour. 150 tasks on the OSWorld environment, scored by an automated judge. No skill in this repo runs it. It needs OSWorld virtual machines (execution tier T2). Limits: A fixed desktop image and static injections.

No standardized test for

- The applications your users will actually point it at.

### cu-04 Data leaves through the agent's own actions

The agent types, pastes, uploads or navigates in a way that carries private data to a place an attacker can read.

OWASP LLM: LLM02:2025 Sensitive Information Disclosure · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0086 Exfiltration via AI Agent Tool Invocation

Review questions

1. What sensitive data is visible to the session: open tabs, files, clipboard, earlier pages?
2. Can the agent reach arbitrary external sites while that data is in view?
3. Is outbound navigation or form submission restricted or logged?

Vendor evidence to look for

- Exfiltration scenarios in the vendor's testing and their results.
- Network or site restrictions available to a deploying organisation.

Existing benchmarks

- **OS-Harm** (arXiv 2506.14866). Safety of computer-use agents in three categories: deliberate user misuse, prompt injection and model misbehaviour. 150 tasks on the OSWorld environment, scored by an automated judge. No skill in this repo runs it. It needs OSWorld virtual machines (execution tier T2). Limits: A fixed desktop image and static injections.
- **RedTeamCUA (RTC-Bench)** (arXiv 2505.21936). Indirect prompt injection against computer-use agents in a hybrid sandbox: a VM desktop plus Docker-hosted web platforms. 864 examples. No skill in this repo runs it. Needs VMs (T2). Limits: Its own web platforms.

No standardized test for

- Exfiltration paths specific to your data and your network.

### cu-05 The feature is used deliberately for harm

A user points the agent at harassment, fraud, bulk account creation or bypassing checks meant for people.

Framework ids: none. No entry was verified to fit, so none is given.

Review questions

1. What does the usage policy prohibit for this feature, and what is enforced technically?
2. Does the vendor report refusal on harmful computer-use tasks next to completion of legitimate ones?

Vendor evidence to look for

- Misuse evaluations for this feature with both figures.
- Abuse monitoring and enforcement that applies to your accounts.

Existing benchmarks

- **OS-Harm** (arXiv 2506.14866). Safety of computer-use agents in three categories: deliberate user misuse, prompt injection and model misbehaviour. 150 tasks on the OSWorld environment, scored by an automated judge. No skill in this repo runs it. It needs OSWorld virtual machines (execution tier T2). Limits: A fixed desktop image and static injections.
- **AgentHarm** (arXiv 2410.09024; inspect_evals `agentharm`). Whether an agent with tools carries out explicitly malicious multi-step tasks: 110 tasks in 11 harm categories, with a benign counterpart set. An Inspect task that no skill in this repo wraps. `agent-misuse-benchmark` is the skill planned for misuse inside agent harnesses. Limits: Simulated tools; no screen.

Your own tests through this repo's skills

- `agent-misuse-benchmark`: measures a model inside an agent harness on malicious and matched benign scenarios; check whether it supports a computer-use harness before planning on it.

No standardized test for

- Misuse specific to your systems.

### cu-06 Oversight that does not work as a check

Nobody can reconstruct what the agent did, approvals are too frequent to read, or the agent's account of its actions differs from the actions.

OWASP Agentic: ASI09 Human-Agent Trust Exploitation

Review questions

1. What is recorded: screenshots, an action log, the pages visited? Where, for how long, and who can read it?
2. Can a reviewer replay a session after the fact?
3. How many approvals does a typical task ask for, and what do they show?

Vendor evidence to look for

- Logging and audit features for this feature.
- Any study by the vendor of approval fatigue or of agent summaries against actual actions.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No public test measures whether approvals are read or logs are sufficient. Record what is in place.

### cu-07 Downloads, installs and code run from the agent's session

The agent downloads and opens a file, installs an extension or runs a command, and the machine it runs on is compromised.

OWASP Agentic: ASI05 Unexpected Code Execution (RCE) · MITRE ATLAS: AML.T0112.000 Machine Compromise: Local AI Agent, AML.T0011.003 User Execution: Malicious Link

Review questions

1. Can the agent download, open or execute files, install extensions, or open a terminal?
2. What separates the agent's environment from the user's machine and from your network?

Vendor evidence to look for

- The isolation of the hosted environment and what persists between sessions.
- Restrictions on downloads and execution.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Isolation of your own desktop or VM image. Design review.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org/llm-top-10/ (read 2026-11-14); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
