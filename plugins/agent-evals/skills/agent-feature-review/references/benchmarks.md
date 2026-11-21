# Benchmarks named in the templates

Generated from `templates/_benchmarks.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

Surveyed 2026-11-14. Each entry says what the benchmark measures, how it can be run from this repo if at all, what it leaves out, and how the description was verified. "Paper abstract only" means exactly that: the code was not fetched or run, and licence and dataset details were not checked.

A benchmark result is evidence about a model or an agent in the benchmark's own environment. It is not evidence about a vendor's product unless the vendor ran it on that product and says so.

## AgentDojo

- Reference: arXiv 2406.13352
- Measures: Whether a tool-calling agent follows instructions planted in tool results while doing a user's task, with task utility reported beside security. The paper describes 97 tasks and 629 security test cases.
- Route: This repo: `model-benchmark`, check `agentdojo`.
- Limits: Simulated tools in its own environments (the paper gives email, e-banking and travel booking as examples). No screen, no real connector, no memory across sessions.
- Verified: Paper abstract; the check is present in model-benchmark's suite.
- Named under: cu-01, mcp-02, mcp-05

## AgentThreatBench

- Reference: inspect_evals 0.29.0, `agent_threat_bench_*`
- Measures: Three small Inspect tasks built on the OWASP agentic list: memory poisoning, autonomy hijack and data exfiltration, each with a utility score.
- Route: This repo: `model-benchmark`, checks `atb_memory_poison`, `atb_autonomy_hijack`, `atb_data_exfil`.
- Limits: 10, 6 and 8 cases respectively, so one case moves the result by 10 points or more.
- Verified: inspect_evals README; sizes from model-benchmark's suite.
- Named under: mcp-02, mcp-05, mem-01

## PersistBench

- Reference: arXiv 2602.01146; inspect_evals `persistbench_*`
- Measures: Long-term memory risks: cross-domain leakage (a memory used where it does not belong) and memory-induced sycophancy, plus a beneficial-use task. Judge-scored.
- Route: An Inspect task that no skill in this repo wraps. Run `inspect_evals/persistbench_cross_domain` and `persistbench_sycophancy` by hand in the environment `model-benchmark` sets up, with a judge that is not the model under test.
- Limits: Memories are supplied to the model by the benchmark. It does not test an attacker writing to memory, nor a vendor's memory store.
- Verified: Paper abstract and inspect_evals README. Not run here.
- Named under: mem-02, mem-05

## MCPTox

- Reference: arXiv 2508.14925
- Measures: Agent robustness to tool poisoning: malicious instructions in tool metadata. Built on 45 real MCP servers and 353 tools, 1,348 test cases in 10 risk categories.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own server set, not yours.
- Verified: Paper abstract only. Code location, licence and how it runs were not checked.
- Named under: mcp-01

## MCP Security Bench (MSB)

- Reference: arXiv 2510.15994
- Measures: Resistance to 12 MCP-specific attack types across planning, tool invocation and response handling, including name collision and preference manipulation; reports a combined security and performance figure.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own tools and domains.
- Verified: Paper abstract only.
- Named under: mcp-01, mcp-02, mcp-03

## InjecAgent

- Reference: arXiv 2403.02691
- Measures: Indirect prompt injection in tool-integrated agents: 1,054 test cases over 17 user tools and 62 attacker tools, covering direct harm and data theft.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own simulated tools.
- Verified: Paper abstract only.
- Named under: mcp-02, mcp-05

## Agent Security Bench (ASB)

- Reference: arXiv 2410.02644
- Measures: A framework of attacks and defences on agents across 10 scenarios, including prompt injection, a memory-poisoning attack and a backdoor attack.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own agents and memory store.
- Verified: Paper abstract only.
- Named under: mem-01

## OS-Harm

- Reference: arXiv 2506.14866
- Measures: Safety of computer-use agents in three categories: deliberate user misuse, prompt injection and model misbehaviour. 150 tasks on the OSWorld environment, scored by an automated judge.
- Route: No skill in this repo runs it. It needs OSWorld virtual machines (execution tier T2).
- Limits: A fixed desktop image and static injections.
- Verified: Paper abstract only. `inspect_evals/osworld` is the capability benchmark, not OS-Harm.
- Named under: cu-01, cu-03, cu-04, cu-05

## RedTeamCUA (RTC-Bench)

- Reference: arXiv 2505.21936
- Measures: Indirect prompt injection against computer-use agents in a hybrid sandbox: a VM desktop plus Docker-hosted web platforms. 864 examples.
- Route: No skill in this repo runs it. Needs VMs (T2).
- Limits: Its own web platforms.
- Verified: Paper abstract only.
- Named under: cu-01, cu-04

## WASP

- Reference: arXiv 2504.18575
- Measures: End-to-end prompt injection against web agents, distinguishing partial from full attacker success.
- Route: No skill in this repo runs it.
- Limits: Its own web environments.
- Verified: Paper abstract only.
- Named under: cu-01

## VPI-Bench

- Reference: arXiv 2506.02456
- Measures: Visual prompt injection: malicious instructions rendered in the interface, against computer-use and browser-use agents. 306 test cases on five platforms.
- Route: No skill in this repo runs it.
- Limits: Its own platform variants.
- Verified: Paper abstract only.
- Named under: cu-01

## CyberSecEval 3 visual prompt injection

- Reference: inspect_evals `cyse3_visual_prompt_injection`
- Measures: Whether a model that reads images follows instructions placed in an image. A model-level test with no agent and no actions.
- Route: An Inspect task. Run it through `vision-model-benchmark`, which runs a corrected version split by injection type, beside its own rendered core set.
- Limits: Says nothing about what an agent would then do.
- Verified: Task name present in inspect_evals 0.29.0. Not run here.
- Named under: cu-01

## SandboxEscapeBench

- Reference: arXiv 2603.02277; UK AI Security Institute
- Measures: A model's capability to break out of a container: capture-the-flag tasks with deliberately added misconfigurations, privilege mistakes, kernel flaws and runtime weaknesses, inside a nested outer sandbox.
- Route: An Inspect evaluation that no skill in this repo runs. Needs a supervised nested sandbox (T2).
- Limits: It measures the model, not a product's sandbox. A vendor's isolation is evidenced by the vendor's own testing.
- Verified: Paper abstract; AISI attribution from AISI's blog listing via search, not read in full.
- Named under: exec-02

## RedCode

- Reference: arXiv 2411.07781
- Measures: Whether code agents execute or generate risky code. RedCode-Exec has 4,050 test cases in Python and Bash with Docker environments.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own agents and environments.
- Verified: Paper abstract only.
- Named under: exec-01, exec-08

## CodeIPI

- Reference: inspect_evals `ipi_coding_agent`
- Measures: Whether a coding agent executes instructions hidden in issues, code comments, README or config files while fixing a bug. 45 samples (35 injected, 10 benign).
- Route: An Inspect task that no skill in this repo wraps; run it by hand in the environment `model-benchmark` sets up. It needs Docker.
- Limits: Small. One case is about 3 points.
- Verified: inspect_evals 0.29.0 README. Not run here.
- Named under: exec-01

## CyberSecEval 2 code interpreter abuse

- Reference: inspect_evals `cyse2_interpreter_abuse`
- Measures: Whether a model complies with prompts asking it to abuse a code interpreter, as decided by a judge model. No code is executed.
- Route: An Inspect task that no skill in this repo wraps; run it by hand with an explicit judge.
- Limits: Compliance in text, not behaviour in a real sandbox.
- Verified: inspect_evals 0.29.0 README. Not run here.
- Named under: exec-08

## SafeRAG

- Reference: arXiv 2501.18636
- Measures: RAG pipelines under four attack tasks the authors call silver noise, inter-context conflict, soft ad and white denial-of-service.
- Route: Research code; no skill in this repo runs it.
- Limits: Its own corpus; language and licence not checked.
- Verified: Paper abstract only.
- Named under: rag-01, rag-06

## TAMAS

- Reference: arXiv 2511.05269
- Measures: Robustness of multi-agent LLM systems: five scenarios, 300 adversarial instances across six attack types, 100 harmless tasks, on AutoGen and CrewAI configurations.
- Route: Research code; no skill in this repo runs it.
- Limits: Open frameworks, not a vendor's orchestration.
- Verified: Paper abstract only.
- Named under: ma-01

## AgentHarm

- Reference: arXiv 2410.09024; inspect_evals `agentharm`
- Measures: Whether an agent with tools carries out explicitly malicious multi-step tasks: 110 tasks in 11 harm categories, with a benign counterpart set.
- Route: An Inspect task that no skill in this repo wraps. `agent-misuse-benchmark` is the skill planned for misuse inside agent harnesses.
- Limits: Simulated tools; no screen.
- Verified: Paper abstract; task present in inspect_evals 0.29.0.
- Named under: cu-05

## OverEager-Bench

- Reference: arXiv 2605.18583
- Measures: How often coding agents take actions outside the scope of a benign request, across four agent products.
- Route: Research code; no skill in this repo runs it.
- Limits: Coding agents only.
- Verified: Paper abstract only.
- Named under: bg-03
