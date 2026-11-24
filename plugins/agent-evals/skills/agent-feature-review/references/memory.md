# Persistent memory — threat and test template

Generated from `templates/memory.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: each conversation starts from the system prompt and what the user types. After: content written in one session is loaded into later sessions as context the model trusts.
- Anything that can cause a write (a user message, a document, a tool result, a web page) can influence every later session that reads it.
- Memory may be shared: across a user's devices and projects, across members of a workspace, across agents.
- Stored memory is a new data store, with its own retention, access and deletion.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- What causes a memory write: an explicit request from the user, or the model's own judgement while reading content?
- Who shares a memory: one user, a project, a team, several agents?
- Can the organisation turn memory off, make it read-only, or inspect it?

## Threats

### mem-01 Memory poisoning: planted content is saved and steers later sessions

An instruction or false fact arrives in a document, a tool result or a message, is written to memory, and acts in sessions where the attacker is no longer present.

OWASP LLM: LLM01:2026 Prompt Injection · OWASP Agentic: ASI06 Memory & Context Poisoning · MITRE ATLAS: AML.T0080.000 AI Agent Context Poisoning: Memory, AML.T0051.001 LLM Prompt Injection: Indirect

Review questions

1. Can content from documents, tools or the web cause a write, or only the user's own words?
2. Is the user shown each write when it happens, with where it came from?
3. When memory is loaded, is it marked as stored data or presented like instructions?

Vendor evidence to look for

- How writes are triggered and surfaced.
- Injection testing that carries across sessions, not only within one.
- Whether memory can be disabled or restricted per deployment.

Existing benchmarks

- **AgentThreatBench** (inspect_evals 0.29.0, `agent_threat_bench_*`). Three small Inspect tasks built on the OWASP agentic list: memory poisoning, autonomy hijack and data exfiltration, each with a utility score. This repo: `model-benchmark`, checks `atb_memory_poison`, `atb_autonomy_hijack`, `atb_data_exfil`. Limits: 10, 6 and 8 cases respectively, so one case moves the result by 10 points or more.
- **Agent Security Bench (ASB)** (arXiv 2410.02644). A framework of attacks and defences on agents across 10 scenarios, including prompt injection, a memory-poisoning attack and a backdoor attack. Research code; no skill in this repo runs it. Limits: Its own agents and memory store.

No standardized test for

- The vendor's real memory implementation. Public benchmarks model memory as a store inside their own harness.

### mem-02 Something remembered in one context surfaces in another

A detail from a personal or confidential conversation appears in an unrelated one: another project, another audience, a shared screen.

OWASP LLM: LLM02:2026 Sensitive Information Disclosure · MITRE ATLAS: AML.T0085.002 Data from AI Services: Conversation Context and Memory

Review questions

1. Are memories scoped by project, workspace or topic, and who sets the scope?
2. Does the vendor measure inappropriate use of memory in unrelated conversations?

Vendor evidence to look for

- Scoping rules for memory.
- Results on cross-context leakage.

Existing benchmarks

- **PersistBench** (arXiv 2602.01146; inspect_evals `persistbench_*`). Long-term memory risks: cross-domain leakage (a memory used where it does not belong) and memory-induced sycophancy, plus a beneficial-use task. Judge-scored. An Inspect task that no skill in this repo wraps. Run `inspect_evals/persistbench_cross_domain` and `persistbench_sycophancy` by hand in the environment `model-benchmark` sets up, with a judge that is not the model under test. Limits: Memories are supplied to the model by the benchmark. It does not test an attacker writing to memory, nor a vendor's memory store.

No standardized test for

- Leakage across your own project and workspace boundaries.

### mem-03 Leakage between users or tenants of a shared memory

In a team workspace or a shared agent, one person's content reaches another through memory.

OWASP LLM: LLM02:2026 Sensitive Information Disclosure

Review questions

1. Is any memory shared between users? Between an end user and an administrator?
2. What isolates one customer's memory from another's on the vendor's side?

Vendor evidence to look for

- The isolation model for memory stores.
- Independent audit covering it.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No public benchmark tests a vendor's tenant isolation. Vendor evidence and a two-account test of your own.

### mem-04 Sensitive data is written to memory and kept

Secrets, personal data or regulated data end up in a store nobody planned for.

OWASP LLM: LLM02:2026 Sensitive Information Disclosure

Review questions

1. Where is memory stored, for how long, and who at the vendor and in your organisation can read it?
2. Does deletion by the user remove it everywhere, including backups and derived data?
3. Is memory content used for training?

Vendor evidence to look for

- Data-handling terms that name memory explicitly.
- Export and deletion features.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- A data-handling review. No benchmark.

### mem-05 Stored content degrades later answers

Remembered beliefs and preferences make the model agree with the user where it should not, or bias later work.

OWASP LLM: LLM07:2026 Misinformation

Review questions

1. Will users rely on answers where a remembered belief could mislead: advice, analysis, review?
2. Does the vendor measure the effect of memory on answer quality?

Vendor evidence to look for

- Results on memory-induced sycophancy or similar.

Existing benchmarks

- **PersistBench** (arXiv 2602.01146; inspect_evals `persistbench_*`). Long-term memory risks: cross-domain leakage (a memory used where it does not belong) and memory-induced sycophancy, plus a beneficial-use task. Judge-scored. An Inspect task that no skill in this repo wraps. Run `inspect_evals/persistbench_cross_domain` and `persistbench_sycophancy` by hand in the environment `model-benchmark` sets up, with a judge that is not the model under test. Limits: Memories are supplied to the model by the benchmark. It does not test an attacker writing to memory, nor a vendor's memory store.

No standardized test for

- The effect on your own tasks.

### mem-06 A planted memory persists unseen

The user cannot see or audit what is stored, so a planted entry stays until someone finds it; entries can be edited to hide what was done.

OWASP Agentic: ASI06 Memory & Context Poisoning · MITRE ATLAS: AML.T0080.000 AI Agent Context Poisoning: Memory, AML.T0092 Manipulate User LLM Chat History

Review questions

1. Can the user and an administrator list, search, edit and delete memories?
2. Is there a log of writes with the source of each?
3. Would anyone be alerted to a write caused by external content?

Vendor evidence to look for

- Memory management and audit features.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No public test. Record what is in place.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2026, https://genai.owasp.org/top-10-for-llm-applications-2026/ (read 2026-11-24); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
