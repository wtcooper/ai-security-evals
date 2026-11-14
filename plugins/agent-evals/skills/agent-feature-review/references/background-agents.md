# Scheduled and background agents — threat and test template

Generated from `templates/background-agents.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: a person starts each run, watches it and reads the result. After: runs start from a clock, an event or another system, with nobody watching, using credentials stored for the purpose.
- Whatever fires the trigger (an incoming email, a webhook, a new issue, a dropped file) is input an outsider may be able to send.
- Stored credentials outlive the session and sometimes the person who set the task up.
- Results land somewhere and may be acted on later by people or automations that never saw the run.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- What starts a run: a schedule, an event, another agent? Who can cause that event?
- Whose credentials does it run with, and when do they expire?
- Who is told when a run fails or does something unusual, and who can stop it?

## Threats

### bg-01 A trigger an outsider can fire or shape

An email, an issue, a webhook or a file starts a run and also supplies its instructions.

OWASP LLM: LLM01:2025 Prompt Injection · OWASP Agentic: ASI01 Agent Goal Hijack · MITRE ATLAS: AML.T0051.002 LLM Prompt Injection: Triggered, AML.T0093 Prompt Infiltration via Public-Facing Application

Review questions

1. Can someone outside the organisation cause the triggering event?
2. Is the triggering content treated as data, or as the task?

Vendor evidence to look for

- Injection testing with event-triggered runs.
- Controls on who or what may trigger.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Event-triggered runs. The public injection benchmarks start from a user's request, not from an event.

### bg-02 Standing credentials and permissions

Long-lived tokens with broad scope sit in a task definition, and keep working after their owner has moved on.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI03 Identity and Privilege Abuse · MITRE ATLAS: AML.T0083 Credentials from AI Agent Configuration, AML.T0055 Unsecured Credentials

Review questions

1. What can the stored credential do, and is that the least the task needs?
2. What happens to the task when its owner leaves or loses access?

Vendor evidence to look for

- How credentials for unattended runs are stored, scoped and rotated.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Design review.

### bg-03 Actions with nobody present to approve

Approvals are granted in advance or skipped, so the agent's first mistake or manipulation takes effect.

OWASP LLM: LLM06:2025 Excessive Agency · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0053 AI Agent Tool Invocation

Review questions

1. Which actions can an unattended run take, and which are held for a person?
2. How often does the agent do more than it was asked on ordinary tasks?

Vendor evidence to look for

- Permission modes for unattended runs.
- Rates of out-of-scope actions on benign tasks.

Existing benchmarks

- **OverEager-Bench** (arXiv 2605.18583). How often coding agents take actions outside the scope of a benign request, across four agent products. Research code; no skill in this repo runs it. Limits: Coding agents only.

No standardized test for

- Unattended operation of a given product. The one benchmark found covers coding agents on benign tasks.

### bg-04 A changed task or a delayed instruction keeps running

A schedule, a task definition or the agent's configuration is altered once and the change executes every time after.

OWASP Agentic: ASI10 Rogue Agents · MITRE ATLAS: AML.T0081 Modify AI Agent Configuration, AML.T0094 Delay Execution of LLM Instructions, AML.T0142 Event Triggered Execution

Review questions

1. Who can edit a task or the agent's configuration, and is every change logged and reviewed?
2. Can a run modify its own schedule, prompt or configuration?

Vendor evidence to look for

- Change control and audit for task definitions.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test.

### bg-05 Runaway runs

Loops, retries and fan-out consume budget or repeat an action many times.

OWASP LLM: LLM10:2025 Unbounded Consumption · OWASP Agentic: ASI08 Cascading Failures · MITRE ATLAS: AML.T0034.002 Cost Harvesting: Agentic Resource Consumption

Review questions

1. What caps run time, frequency, retries and spend?
2. Does an alert reach a person?

Vendor evidence to look for

- Documented limits.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Read the configuration.

### bg-06 Nobody notices

Failures, drift after a model update and misbehaviour go unseen because no one reads the output of a job that usually works.

OWASP Agentic: ASI10 Rogue Agents

Review questions

1. Who reviews run results, and how often?
2. Is the model version pinned, and who is told when it changes?

Vendor evidence to look for

- Monitoring, alerting and version-pinning features.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test.

### bg-07 Stopping it

No clear way, or no clear owner, to pause or remove a task quickly.

Framework ids: none. No entry was verified to fit, so none is given.

Review questions

1. Who can pause, edit and delete a task? Is there one place that lists them all?
2. How fast does a stop take effect on a run in progress?

Vendor evidence to look for

- Administrative controls over scheduled tasks.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test. Record what is in place.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org/llm-top-10/ (read 2026-11-14); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
