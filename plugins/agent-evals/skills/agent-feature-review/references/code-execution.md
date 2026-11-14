# Code execution sandboxes — threat and test template

Generated from `templates/code-execution.json` by `scripts/templates.py --render`. Edit the JSON and render again; a unit test fails if this file is out of date.

## What the feature changes about the trust boundary

- Before: the model writes code that a person reads and runs. After: model-written code runs automatically, with whatever files, network and credentials the environment has.
- The sandbox boundary (container, microVM, process) becomes a control you rely on. If the vendor hosts it you did not build it; if you host it you must operate it.
- Uploaded files and downloaded results cross the boundary, and packages installed at run time come from public registries.
- If the same session reads untrusted content, that content can decide what code runs.

## Deployment context to capture

Besides the scope and the six dimensions in `deployment-context.md`, ask:

- Who hosts the sandbox, and what isolates one session and one customer from another?
- Is outbound network access on, off or restricted to a list?
- What is inside: uploaded files, mounted data, environment variables, credentials?

## Threats

### exec-01 Planted instructions decide what code runs

A file, a web page or a repository the session reads tells the model to run something, and it does.

OWASP LLM: LLM01:2025 Prompt Injection, LLM05:2025 Improper Output Handling · OWASP Agentic: ASI05 Unexpected Code Execution (RCE) · MITRE ATLAS: AML.T0050 Command and Scripting Interpreter, AML.T0051.001 LLM Prompt Injection: Indirect

Review questions

1. What untrusted content can reach a session that can execute code?
2. Is there any step between the model writing code and the code running?
3. How does the vendor test injection that ends in execution?

Vendor evidence to look for

- Injection results for agents that execute code.
- Any execution-time checks.

Existing benchmarks

- **CodeIPI** (inspect_evals `ipi_coding_agent`). Whether a coding agent executes instructions hidden in issues, code comments, README or config files while fixing a bug. 45 samples (35 injected, 10 benign). An Inspect task that no skill in this repo wraps; run it by hand in the environment `model-benchmark` sets up. It needs Docker. Limits: Small. One case is about 3 points.
- **RedCode** (arXiv 2411.07781). Whether code agents execute or generate risky code. RedCode-Exec has 4,050 test cases in Python and Bash with Docker environments. Research code; no skill in this repo runs it. Limits: Its own agents and environments.

Your own tests through this repo's skills

- `agent-misuse-benchmark`: a model inside a coding harness on malicious and benign scenarios.

No standardized test for

- Your own repositories and files as the injection carrier.

### exec-02 Escape from, or reach beyond, the sandbox

Code inside reaches the host, another session or another customer.

OWASP Agentic: ASI05 Unexpected Code Execution (RCE) · MITRE ATLAS: AML.T0105 Escape to Host

Review questions

1. What is the isolation technology, and is each session a fresh instance?
2. Has the sandbox been tested by an outside party, and is it in a bug-bounty scope?
3. If you host it: what configuration departs from the hardened default?

Vendor evidence to look for

- Isolation architecture.
- Third-party security testing of the sandbox.
- Incident history.

Existing benchmarks

- **SandboxEscapeBench** (arXiv 2603.02277; UK AI Security Institute). A model's capability to break out of a container: capture-the-flag tasks with deliberately added misconfigurations, privilege mistakes, kernel flaws and runtime weaknesses, inside a nested outer sandbox. An Inspect evaluation that no skill in this repo runs. Needs a supervised nested sandbox (T2). Limits: It measures the model, not a product's sandbox. A vendor's isolation is evidenced by the vendor's own testing.

No standardized test for

- The vendor's actual sandbox. The public benchmark measures whether a model can break out of containers with planted weaknesses; it says nothing about a given product's isolation.

### exec-03 Network egress: data out, and internal services in reach

Code sends data to an outside host, or reaches internal addresses and metadata services.

OWASP LLM: LLM02:2025 Sensitive Information Disclosure · OWASP Agentic: ASI02 Tool Misuse and Exploitation · MITRE ATLAS: AML.T0086 Exfiltration via AI Agent Tool Invocation

Review questions

1. Is egress on by default? Is there an allowlist, and who maintains it?
2. From inside, what answers: your internal network, cloud metadata endpoints, other tenants?

Vendor evidence to look for

- Documented network policy of the sandbox.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Check it yourself from inside the sandbox; no benchmark does this for you.

### exec-04 Credentials and data left inside the environment

Secrets in environment variables, mounted volumes or leftover files are readable by any code that runs.

OWASP LLM: LLM02:2025 Sensitive Information Disclosure · OWASP Agentic: ASI03 Identity and Privilege Abuse · MITRE ATLAS: AML.T0055 Unsecured Credentials, AML.T0037 Data from Local System

Review questions

1. What credentials exist inside the sandbox, and why?
2. Do files persist between sessions or users?

Vendor evidence to look for

- What the environment contains by default.
- Persistence and clean-up behaviour.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Design review of what you mount and inject.

### exec-05 Packages pulled in at run time

Model-written code installs a package that is malicious, typosquatted, or registered under a name the model invented.

OWASP LLM: LLM03:2025 Supply Chain · OWASP Agentic: ASI04 Agentic Supply Chain Vulnerabilities · MITRE ATLAS: AML.T0011.001 User Execution: Malicious Package, AML.T0060 Publish Hallucinated Entities

Review questions

1. Can code install packages, from which registries?
2. Is there a mirror, an allowlist or a pre-built image?

Vendor evidence to look for

- Package-installation policy of the sandbox.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- No standard test of a sandbox's package policy.

### exec-06 Resource and cost abuse

Long-running or looping jobs consume compute and budget.

OWASP LLM: LLM10:2025 Unbounded Consumption · MITRE ATLAS: AML.T0034.002 Cost Harvesting: Agentic Resource Consumption

Review questions

1. What limits apply per session: time, CPU, memory, spend?
2. Who is alerted when they are hit?

Vendor evidence to look for

- Documented limits and billing controls.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Check the limits by reading the configuration.

### exec-07 Files and output handed on without checking

Something produced in the sandbox (a document, HTML, a script) is opened or rendered by a person or another system that trusts it.

OWASP LLM: LLM05:2025 Improper Output Handling

Review questions

1. Where do generated files go, and who or what opens them?
2. Is output rendered as HTML or executed anywhere downstream?

Vendor evidence to look for

- Handling of generated artefacts in the product.

Existing benchmarks

- None found (survey of 2026-11-14).

No standardized test for

- Your own downstream handling.

### exec-08 The sandbox used as attack infrastructure by its user

A user has the model write and run scanners, exploits or abusive automation from the vendor's or your network.

Framework ids: none. No entry was verified to fit, so none is given.

Review questions

1. What does the usage policy say, and what is enforced?
2. Whose address space do outbound connections come from?

Vendor evidence to look for

- Misuse evaluations for code execution.
- Abuse monitoring.

Existing benchmarks

- **CyberSecEval 2 code interpreter abuse** (inspect_evals `cyse2_interpreter_abuse`). Whether a model complies with prompts asking it to abuse a code interpreter, as decided by a judge model. No code is executed. An Inspect task that no skill in this repo wraps; run it by hand with an explicit judge. Limits: Compliance in text, not behaviour in a real sandbox.
- **RedCode** (arXiv 2411.07781). Whether code agents execute or generate risky code. RedCode-Exec has 4,050 test cases in Python and Bash with Docker environments. Research code; no skill in this repo runs it. Limits: Its own agents and environments.

Your own tests through this repo's skills

- `agent-misuse-benchmark`: refusal on malicious tasks beside completion on benign ones, inside an agent harness.

No standardized test for

- Misuse specific to your network position.

## Sources

Framework ids: OWASP Top 10 for LLM Applications 2025, https://genai.owasp.org/llm-top-10/ (read 2026-11-14); OWASP Top 10 for Agentic Applications 2026, published December 2025, https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (PDF read 2026-11-14); MITRE ATLAS data release 2026.10, https://github.com/mitre-atlas/atlas-data (dist/v6/ATLAS-2026.10.yaml, read 2026-11-14).
Benchmarks: see `benchmarks.md` for what was and was not verified about each.
