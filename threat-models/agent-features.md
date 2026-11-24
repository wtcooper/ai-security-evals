# Threat model: Agent features (computer use, memory, connectors and extensions, code execution, retrieval, multi-agent, background agents)

| Field | Value |
|---|---|
| Asset class | Agent features: capabilities switched on for a model or product already in use, namely computer use and browser control, persistent memory, connectors, MCP servers, skills and plugins, code execution sandboxes, file search and retrieval, multi-agent systems and subagents, scheduled and background agents |
| Version | 1.1 |
| Date | 2026-11-24 |
| Evaluated by | `agent-feature-review` |
| Related threat models | AI coding agents; LLM applications; Vision-input models; General-purpose models; AI-assisted security tools |
| Status | Current. Ratings are rough and for the reference deployment below |

## 1. Executive summary

An agent feature is a capability switched on for a model or product the organisation already
uses. Each one moves a trust boundary that the original review assumed was fixed: it lets
others' content into the model's context, gives the agent a new way to act or send data out,
hands it a standing identity, lets state outlive the session, brings third-party code into the
loop, or removes the person who used to start and watch each run. The model may be unchanged;
what it can be made to do is not.

| Core risk | Why it matters | Inherent risk | Assessed by |
|---|---|---|---|
| Content the feature brings in takes over the agent | Screens, tool results, retrieved documents, memories, other agents' messages and event triggers are all written by someone other than the user, and published attacks turn each into actions | Critical | `agent-feature-review`; part-measured by public benchmarks |
| The feature acts with a standing identity and broad privileges | A signed-in browser, an OAuth token or a stored credential gives whoever steers the agent the user's or a service's reach | High | `agent-feature-review` (design review) |
| Data leaves through the feature's own actions | Typing into a form, calling a second connector or rendering an image link is an exfiltration channel; zero-click cases are documented | High | `agent-feature-review`; part-measured by public benchmarks |
| Third-party code and text in the loop | MCP servers, skills, plugins and remote agents are installed from registries and can be malicious from the start or change after approval; malicious ones have been found in public registries | High | `agent-feature-review`; `security-tool-benchmark` measures scanners |
| Persistence and absence | Memory and schedules make one injection last; unattended runs remove the person who would have noticed | High | `agent-feature-review` (design review) |
| The feature becomes someone's attack tool | Code execution, connectors and computer use give a misusing user or an intruder an operator that scans, runs code and acts across systems | Medium | `agent-feature-review`; `agent-misuse-benchmark` once completed |
| The agent goes beyond its task with no adversary | Agents with code execution, egress and credentials have left sandboxes, attacked third parties and switched off their own monitoring | Medium (High with egress and long unattended runs) | `agent-feature-review` (design review only) |

**Where risk concentrates.** Where a feature combines content others can write with an action
or egress channel and nobody watching: connectors to inboxes and trackers that can also send,
browser agents on a signed-in profile, and background agents started by outside events.
Retrieval and memory concentrate a second kind of risk: data the user never meant to share
becoming findable, or staying long after it should have gone.

**The record since 2025.** Zero-click and one-click hijacks were disclosed against browser
agents and connector-equipped assistants from several vendors; vendors fixed mostly the output
and egress side (image rendering, URL allowlists, confirmations), and two browser-agent vendors
state that prompt injection is not solved. Exploitation in the wild came mostly through the
supply chain and exposed services: an impersonating MCP package that copied every sent email,
malicious skills in a public registry, a tampered agent SDK, exploited MCP endpoints in an AI
gateway, a compromised AI tool's OAuth grant. The one content-borne case seen at scale was
promotional memory poisoning. In 2026 evaluation agents reached the internet through a package
proxy and compromised a third party, a failure with no adversary.

**What the evaluations tell you.** `agent-feature-review` is a guided review, not a benchmark:
one template per feature, recording for each threat the answers, vendor evidence, tests and
what was not assessed. Public benchmarks measure parts of a feature on a model in their own
environment (for example screen-borne injection, tool-result injection, memory poisoning); a
result there is evidence about a model, not about the vendor's product or the organisation's
data. Most of what matters here (privilege reach, tenant isolation, egress, change control)
has no standard test and is design review.

## 2. Scope and reference deployment

**Reference deployment.** An organisation already uses a vendor-hosted assistant or agent
platform, signed in through single sign-on, for knowledge workers and engineers, with internal
and confidential data. It is now switching on features at vendor defaults, one at a time:
connectors to email, documents and tickets with user-delegated OAuth, which any user may add
unless an administrator restricts it; MCP servers, skills and plugins added by users; a browser
agent working in the user's own signed-in profile; memory on; code execution in the vendor's
sandbox; file search over shared drives; subagents in a research or coding agent; scheduled
tasks with stored credentials. Logging is whatever the vendor's administrator console offers.

**What moves the ratings.** Administrator-only enablement and allowlists lower everything
involving extensions. A vendor-hosted, isolated browser or VM with no signed-in accounts lowers
computer-use impact sharply; the user's own desktop raises it. Read-only connectors and
narrowly scoped tokens lower impact; connectors that can send lower it least. Sandboxes with no
network lower code-execution risk; network on raises it, and package mirrors, proxies and caches
the sandbox can reach count as network. Memory scoped per project and visible to the user lowers
persistence risk. Triggers limited to insiders lower background-agent risk. Self-hosted MCP
servers, gateways and agent platforms reachable from the internet raise exposure risk sharply.

**In scope:** the trust boundary each feature moves and the threats that follow. **Out of
scope:** the model's general behaviour (General-purpose models), the coding-agent harness
itself (AI coding agents), the organisation's own application around a model (LLM
applications), and scanning any specific extension, which is outside this repository.

## 3. System model

**The shared core.** Every feature makes one or more of these seven changes; most threats below
follow from them.

1. **New content in context**, written by someone other than the user.
2. **New action or egress channel**: clicks, tool calls, code, sends.
3. **New standing identity**: a signed-in session, a token, a stored credential.
4. **New persistence**: memory, indexes, schedules, containers that outlive the session.
5. **Less human presence** per action, down to none.
6. **Third-party code and text in the loop**: servers, skills, plugins, remote agents.
7. **A new data store** at the vendor, with its own retention and access.

| Feature | Shared changes it makes |
|---|---|
| Computer use and browser control | 1, 2, 3, 5 |
| Persistent memory | 1, 4, 7 |
| Connectors, MCP servers, skills and plugins | 1, 2, 3, 6 |
| Code execution sandboxes | 2, 4, 7 |
| File search and retrieval | 1, 3, 4, 7 |
| Multi-agent systems and subagents | 1, 2, 3, 5, 6 |
| Scheduled and background agents | 1, 3, 4, 5 |

```mermaid
flowchart LR
  USER(["User"])
  subgraph ORG["Organisation's boundary"]
    SYS["Connected systems: mail, docs, tickets, code"]
    DESK["User's desktop or browser profile"]
  end
  subgraph VENDOR["Vendor-hosted agent platform"]
    AGENT["Model and orchestrator"]
    MEM[("Memory")]
    IDX[("Retrieval index")]
    SBX["Code sandbox"]
    SUB["Subagents"]
    SCHED["Scheduler and triggers"]
    CRED[("Stored tokens and credentials")]
  end
  subgraph THIRD["Third parties"]
    EXTN["MCP servers, skills, plugins, remote agents"]
    WEB["Web content, inbound email, outsiders' issues"]
  end
  USER --> AGENT
  WEB -->|"content"| AGENT
  WEB -->|"events"| SCHED
  SCHED --> AGENT
  AGENT <--> MEM
  SYS --> IDX --> AGENT
  AGENT --> SBX
  AGENT <--> SUB
  AGENT <-->|"tool descriptions and results"| EXTN
  CRED --> EXTN
  CRED --> SYS
  AGENT -->|"actions"| SYS
  AGENT -->|"clicks and keys"| DESK
```

The assets are the data in connected systems and memory, the credentials and sessions the
features hold, the integrity of what the agent changes or sends, the user's machine (for
computer use and local servers), other tenants' and users' data (for shared stores), and the
record of what happened.

| Threat actor | Capability and access | Motivation |
|---|---|---|
| Content author | Writes something the agent will read: a web page, an email, a shared document, a calendar invite, an issue, a post in a public channel, a web form | Hijack actions, steal data |
| Extension publisher or operator | Publishes or runs an MCP server, skill, plugin or remote agent; may act honestly first and change later | Data theft, persistence, reach into many organisations |
| Other user or tenant | Shares a memory, index or workspace | Curiosity or deliberate access to others' data |
| User misusing the feature | Legitimate access | Fraud, harassment, scanning or abuse from the vendor's or organisation's network |
| Intruder on a user's machine | Malware or an attacker with local access, able to drive an installed agent and its connectors | Reconnaissance and theft with the agent's own reach |
| The agent itself, no adversary | Misreads scope, repeats, loops, or pursues its goal past its brief | None; a failure source |
| Vendor and its suppliers | Hosts the feature, its stores and its sandbox; changes it behind flags; relies on its own providers | Product operation; trusted but outside control |

## 4. Core threats common to every feature

Each threat states its evidence status: *observed in deployed systems* (an incident),
*disclosed vulnerability* (a CVE or advisory, not known exploited), *demonstrated in research*,
or *theoretical*. Section 7 lists the incidents.

**K1. Content the feature brings in takes over the agent.** Whatever the feature adds to the
context (a screenshot, a tool result, a retrieved passage, a memory, another agent's message, a
trigger's payload) can carry instructions the model follows. *Critical* where the content is
outsider-writable and the agent can act; lowered by marking such content as data, fewer actions
in sessions that read it, confirmation for consequential steps, and injection classifiers.
Published cases span every channel: a connector email that made an assistant exfiltrate data
without the user opening it [R20, AML.CS0066], a calendar invitation steering an assistant's
connected tools [R20, AML.CS0063], and a zero-click retrieval exploit in a production assistant
[R25]. Injected content is often used first to learn what the agent holds, its tools and
knowledge sources, before it is used to act [R20, AML.CS0037]. One browser-agent vendor says
prompt injection is "unlikely to ever be fully 'solved'" [R39]. *Evidence: observed* (links
that wrote promotional memories at scale [R46]) and many *disclosed vulnerabilities* [R25].

**K2. The feature acts with a standing identity and broad privileges.** A browser profile, an
OAuth token or a stored service credential gives whoever steers the agent that identity's
reach. *High*; lowered by isolated sessions, narrow scopes requested progressively, and acting
as the asking user every time. The MCP specification forbids token passthrough and calls out
broad up-front scopes as a common mistake [R1]. A shared secret and email-only account linking
let an outsider drive a vendor's privileged built-in AI agent to create an administrator
(CVE-2025-12420) [R47], and the compromised Workspace OAuth app of a third-party AI tool led to
an employee account takeover at another company [R48]. *Evidence: observed* [R48] and
*disclosed vulnerability* [R47].

**K3. Data leaves through the feature's own actions.** A click, a typed form, a call to a
second connector, an outbound request from a sandbox or a rendered image link can carry private
data out. *High*; lowered by egress limits, separating tools that read private data from tools
that send, showing tool arguments before calls, and not rendering remote content. The MCP tools
specification says clients should show tool inputs to the user before calling a server "to
avoid malicious or accidental data exfiltration" [R2]. Vendors' egress checks have been
bypassed rather than removed (rag-05). *Evidence: disclosed vulnerability* in many products
[R25][R42][R44]; *observed* where the server itself was malicious [R45].

**K4. Third-party code and text in the loop.** MCP servers, skills, plugins and remote agents
are code and descriptions written by others, installed from registries, and able to change
after approval. *High*; lowered by administrator-only installation, allowlists, pinned versions
and change alerts. One coding-agent vendor states that it reviews connectors against listing
criteria but "does not security-audit or manage any MCP server" [R3]; another vendor's skills
documentation says to use skills only from trusted sources and warns that even trustworthy ones
can be compromised if their external dependencies change [R4]. A skill registry's operator
warned that a skill instructing an agent in natural language "won't trigger a virus signature"
[R52]. *Evidence: observed*: an impersonating MCP package [R45], malicious registry skills
[R52], a credential stealer in an agent SDK release [R65].

**K5. Persistence and absence make one failure last.** Memory, indexes and schedules keep a
planted instruction alive, and unattended runs remove the person who would have noticed it.
*High* for memory and background agents. *Evidence: observed* for memory writes from crafted
links [R46]; *demonstrated* for persistent exfiltration across sessions [R20, AML.CS0066]. See
the feature sections.

**K6. The feature changes, or spreads, beyond what was reviewed.** Features change behind
vendor flags without a version, users enable them or add extensions outside the reviewed
configuration, and configuration can arrive by routes a reviewer does not see. *High* (likely,
moderate impact); lowered by administrator control of enablement, pinned versions where
offered, and a re-review trigger. For example, in one coding agent plugins can add MCP servers,
so reviewing the project's MCP file does not show every server a session loads [R3]; a branch
named like a pinned commit hash defeated its plugin pinning (CVE-2026-86063), and in its agent
SDK an unvalidated session value could start an arbitrary MCP server (CVE-2026-96620) [R50].
Hundreds of a self-hosted agent's control interfaces were found exposed online, some without
authentication [R20, AML.CS0048]. The feature's own data store (memories, chunks, containers,
transcripts) also needs its own retention and access review: one vendor keeps code-execution
container data up to 30 days, and its skills are not eligible for zero data retention
[R5][R4]. In 2026 an inference provider retained a customer's AI chat transcripts despite a
zero-retention commitment, and stored coding-agent traces holding credentials were copied
through a key issued to that provider [R64]. *Evidence: observed* [R64]; *disclosed
vulnerability* [R50].

**K7. The feature becomes someone's attack tool.** Computer use, code execution and connectors
give a user who misuses them, or an intruder on the user's machine, an operator that can scan,
run code and act across systems. *Medium* for the reference deployment; raised by code
execution with open egress, connectors to security tools, and agents installed on desktops in
permissive modes; lowered by vendor misuse monitoring, egress limits and administrator control
of which tools can be connected. Anthropic reported an espionage campaign in which its coding
agent, connected through MCP to scanners and crackers, did 80–90% of the work, with the
operators splitting tasks into small, innocent-looking steps [R56, AML.CS0069]; an open-source
MCP server wiring models to more than 150 security tools was discussed on criminal forums for
exploitation within hours of release, though use was not confirmed [R57]; malicious npm
packages ran victims' installed AI command-line agents with permission checks disabled to
inventory secrets [R58]. *Evidence: observed* [R56][R58]. The template threats cu-05 and exec-08
record the part a feature review can see.

**K8. The agent goes beyond its task with no adversary.** An agent pursuing a goal can widen its
own reach: probe its environment, use credentials it finds, leave the sandbox, contact
outsiders or switch off oversight. *Medium* for the reference deployment; *High* where code
execution has egress, runs are long and unattended, and the agent holds credentials; lowered by
egress limits enforced outside the agent, scope enforced in tools rather than only in prompts,
and review of proposed actions as they happen. Evaluation agents used a package-proxy zero-day
to reach the internet, coordinated through a message board they built, and compromised a third
party's production systems [R61, AML.CS0068]; other evaluation agents reached real
organisations and people [R29][R62]. Outside evaluations, internal agents at one developer
turned off monitoring alerts and removed a monitoring integration, one then telling the user it
had not [R63]. *Evidence: observed*, so far in cyber evaluations run with safeguards reduced or
switched off and in a developer's internal agents, not in an agent feature at vendor defaults.
The template records its parts under exec-02, exec-03, bg-04, bg-06 and ma-06.

## 5. Threats by feature

Each subsection names the `agent-feature-review` template and its threat ids in brackets, so a
review record can be read against this document. Each threat ends with its evidence status.

### 5.1 Computer use and browser control (template `computer-use`, cu-01 to cu-07)

*Sketch.* The model reads a screen it does not control (screenshots, page structure) and issues
clicks, keystrokes and navigation as whoever the browser or desktop is signed in as. Everything
rendered is input; many actions cannot be undone.

- **Instructions on screen take over the task** [cu-01]. *Critical.* A page, email, document or
  advert tells the agent to do something else. A browser-agent vendor's own red-teaming found
  attack success of 23.6% across 123 cases before new mitigations and 11.2% after [R6], later
  about 1% for an adaptive attacker against one model with new safeguards, while saying "no
  browser agent is immune" [R67]; a hybrid VM-and-web benchmark measured 42.9% for one
  computer-use agent [R7], and adaptive visual injections about 92% against 21 defended agent
  configurations [R69]; a page caused a computer-use agent to open a terminal, paste a command
  and run it [R20, AML.CS0055]. Hidden page text, a crafted link and a calendar invite each
  hijacked the same AI browser in 2025–2026 [R35][R37][R38]. Vendor documentation says the model may
  follow instructions found in content even when they conflict with the user's, and that
  classifiers now scan screenshots for injection [R8]. *Evidence: disclosed vulnerability*
  [R35][R38]; *demonstrated* [R69].
- **Signed-in privileges and irreversible actions** [cu-02, cu-03]. *High.* The agent can reach
  whatever the profile can: internal apps, single sign-on, saved passwords, payment methods.
  Before mitigations, the red-teaming above included an agent deleting a user's emails on a
  phishing instruction [R6]; researchers since showed agents buying from a look-alike shop with
  the saved card [R36], reaching a password manager [R38], and carrying content across the
  browser's same-origin boundary [R40]. Vendor guidance: a dedicated VM or container with
  minimal privileges, no login details given to the model, an allowlist of domains, and a
  person confirming consequential actions [R8]; a fresh profile, credentials kept out of page
  text and screenshots, and "typing sensitive information into a form counts as transmission"
  [R9]. *Evidence: disclosed vulnerability* [R36][R38][R40].
- **Data leaves through the agent's actions** [cu-04]. *High.* Typing, pasting, uploading or
  navigating carries data out (K3). An injected issue led one browser agent to copy private
  details from signed-in pages into an attacker's page, and typing rarely triggered
  confirmation [R33]; encoding the data evaded another's exfiltration check [R37]. *Evidence:
  disclosed vulnerability* [R33][R37].
- **Downloads, installs and code run from the session** [cu-07]. *High on the user's own
  desktop*, lower in a disposable vendor VM. The terminal case above is this threat; text hidden
  in a fake CAPTCHA made an agent start a download [R36]. *Evidence: demonstrated* [R20][R36].
- **Deliberate misuse and oversight that is not a check** [cu-05, cu-06]. *Medium.* Agents
  attempt harmful tasks that the same model refuses in chat [R10] (see K7); watching an agent
  click is not reviewing it, and one vendor advises checking the actual outcome rather than the
  model's final answer [R9]. *Evidence: demonstrated* [R10]; the agent completed the look-alike shop
  purchase above in some runs [R36].

### 5.2 Persistent memory (template `memory`, mem-01 to mem-06)

*Sketch.* Content written in one session is loaded into later ones as trusted context. Anything
that can cause a write can influence every later session; memory may be shared across devices,
projects, team members or agents.

- **Poisoned memories steer later sessions and persist unseen** [mem-01, mem-06]. *High.*
  An injection in a shared document reached a consumer assistant through a connected app and
  wrote false memories that persisted across chats [R20, AML.CS0040]; in the ZombieAgent
  demonstration a connector email wrote memories that kept collecting and exfiltrating data in
  later sessions [R20, AML.CS0066]; in the wild, "Summarize with AI" links from 31 companies told
  assistants to remember them as a trusted source [R46, AML.CS0072]. Research shows memory can
  be poisoned through ordinary queries alone [R11]. Raised when the model writes memory on its
  own judgement while reading content or from a pre-filled prompt; lowered when the user sees
  each write and its source and can list and delete entries. *Evidence: observed* [R46];
  *demonstrated* [R20].
- **Memories surface in the wrong context or for the wrong person** [mem-02, mem-03]. *Medium.*
  Scope matters: one coding agent keeps one auto-memory per repository, shared across its
  worktrees and loaded into each session [R12]. Tenant isolation of a vendor's store has no
  public test. *Evidence: theoretical*; no public incident was found.
- **Sensitive data is written and kept** [mem-04]. *High.* One vendor's memory tool
  documentation says the model "usually refuses" to store sensitive information and leaves
  stronger guarantees, expiry and path validation to the implementer [R13]; the ZombieAgent
  memories were told to keep sensitive information. *Evidence: demonstrated* [R20].
- **Stored beliefs degrade later answers** [mem-05]. *Low* for most uses; *Medium* where answers
  feed purchasing, health or security decisions, which is what the promotional memories above
  aimed to bias [R46]. Memory-induced sycophancy is measured by PersistBench [R14]. *Evidence:
  observed* [R46].

### 5.3 Connectors, MCP servers, skills and plugins (template `connectors-mcp`, mcp-01 to mcp-07)

*Sketch.* The agent reads from and writes to other systems through tools whose names,
descriptions and results come from whoever runs the server, using credentials the connector
holds. With several enabled, data read through one can leave through another.

- **Instructions in tool descriptions and tool results** [mcp-01, mcp-02]. *Critical.* A tool
  description told an agent to read credential files and pass them to the tool, which sent them
  to the server [R20, AML.CS0054]; a skill on a public registry carried an injection that ran a
  shell command [R20, AML.CS0049]. A public issue read through a code-hosting MCP server made an
  agent leak private repositories, a flaw its finders place in the agent architecture rather
  than the server's code [R34]; calendar titles, support tickets and scraped pages did the same
  [R43][R20, AML.CS0039, AML.CS0045]. The MCP specification says clients must treat tool
  annotations as untrusted unless they come from trusted servers, and that there should always
  be a human able to deny tool invocations [R2]. *Evidence:* mcp-01 *demonstrated* [R20], with
  malicious skill text *observed* in a registry [R52]; mcp-02 *disclosed vulnerability* [R34].
- **A malicious, compromised or changed extension** [mcp-03]. *High.* A look-alike email MCP
  package on npm was published clean, gained users, then added a hidden copy of every sent email
  to the attacker [R45, AML.CS0053]; one vendor counted 341 malicious skills in a public skill
  registry, one of which evaded scanning by padding [R52]; agent SDK releases carried a
  credential stealer [R65], and a tampered agent extension sat in a marketplace cache [R64]; a
  package name hallucinated in LLM-written skills spread to 237 or more repositories [R53]. In
  one editor an approved MCP configuration could be swapped without a new prompt
  (CVE-2025-54136) [R15]. *Evidence: observed* [R45][R52][R65].
- **Over-broad tokens and confused deputies** [mcp-04]. *High.* The MCP security guidance
  describes confused-deputy flaws in proxy servers, forbids accepting tokens not issued to the
  server, and recommends progressive least-privilege scopes [R1]. The MCP TypeScript SDK let a
  server choose the authorisation server that received stored OAuth credentials
  (CVE-2026-104850), and an AI gateway's MCP authentication could be bypassed through an OAuth2
  passthrough fallback, a flaw listed as exploited (CVE-2026-59822) [R50][R51]. *Evidence:
  observed* [R51], and through an AI tool's OAuth grant (K2) [R48]; *disclosed vulnerability*
  [R50].
- **Data across connectors, and destructive writes** [mcp-05, mcp-06]. *High.* The email case
  above is cross-tool exfiltration, as were calendar data sent out by email through an
  auto-approving server [R41] and CRM data sent out through a support agent's email tool [R20,
  AML.CS0037]; calendar invitations made an assistant delete events [R43]. Writes that delete or
  send need per-tool approval that shows what will happen (K3). *Evidence: disclosed
  vulnerability* [R41][R43]; *demonstrated* [R20].
- **The server or its transport is exposed** [mcp-07]. *High*, higher for self-hosted servers
  reachable from the internet. The MCP Inspector's proxy lacked authentication and allowed
  remote command execution (CVE-2025-49596); an MCP proxy client ran OS commands from a
  malicious server's authorisation URL (CVE-2025-6514) [R15][R49]; reference filesystem and git
  servers had path and argument-injection flaws an injected agent could drive, and a server
  package could deliver one client's messages to another [R50]; a self-hosted agent's token
  leak let a web page run commands on the host (CVE-2026-25253) [R54]. An AI gateway's MCP test
  endpoints allowed command execution and are listed as exploited (CVE-2026-42271) [R51]. The
  specification covers local server compromise, server-side request forgery and session
  hijacking [R1]. *Evidence: observed* [R51]; *disclosed vulnerability* [R49][R50].

### 5.4 Code execution sandboxes (template `code-execution`, exec-01 to exec-08)

*Sketch.* Model-written code runs automatically with whatever files, network and credentials the
environment has. The sandbox becomes a control the organisation relies on but, if vendor-hosted,
did not build.

- **Planted instructions decide what runs** [exec-01]. *Medium* in a sandbox with no network
  and no secrets; *High* where the sandbox holds data and egress. An injection in a PDF led a
  computer-use agent to run a destructive shell command [R20, AML.CS0046]; one prompt reached
  host-level code execution through an agent framework plugin that evaluated a model-supplied
  filter [R20, AML.CS0062]. *Evidence: demonstrated* [R20].
- **Escape, and reach beyond the sandbox** [exec-02, exec-03]. *Medium* for escape, *High* for
  egress where network is on. Models exploit container weaknesses when they are present [R16].
  One vendor's sandbox has internet "completely disabled" and full isolation from other
  containers [R5], while its consumer app gives skills full, partial or no network depending on
  settings [R4]. In 2026 evaluation agents used a zero-day in the package proxy their sandbox
  could reach to obtain internet access and compromised a third party's production systems
  [R61, AML.CS0068], and a misconfiguration left other evaluation machines with live internet
  access [R29]; a model asked to escape a sandbox did so and then posted exploit details
  publicly unasked [R68]. A sandbox for user-supplied code in an AI gateway was escaped and is
  listed as exploited (CVE-2026-40217) [R51]. *Evidence: observed* [R61][R51] (K8).
- **What sits inside: credentials, leftover data, packages** [exec-04, exec-05]. *Medium.* One
  hosted coding service makes secrets available only during setup and removes them before the
  agent runs [R17]; an injected CI agent read its API key from the process environment through
  a file tool that ran outside the sandboxed shell [R60, AML.CS0067]. Installing packages at run
  time invites hallucinated or malicious names [R18]: a hallucinated name drew daily downloads
  the researchers attribute to agents [R53], and an evaluation agent published a malicious
  package under an unregistered dependency name that ran on 15 real systems [R29]. *Evidence:
  disclosed vulnerability* [R60]; *observed* (failure) [R29].
- **Output handed on, cost abuse, the sandbox used as attack infrastructure** [exec-06,
  exec-07, exec-08]. *Low to Medium.* Files produced in the sandbox may be opened or rendered by
  people or systems that trust them; model-written HTML escaped one assistant's preview sandbox
  [R66]. Loops consume budget. A user may run scanners or abuse from the vendor's address space
  (K7); evaluation agents used an exposed workload's short-lived cloud sandboxes as a launchpad
  [R20, AML.CS0068]. *Evidence:* exec-06 *theoretical* (ATLAS rates it feasible); exec-07
  *disclosed vulnerability* [R66]; exec-08 *observed* [R20].

### 5.5 File search and retrieval (template `file-search-rag`, rag-01 to rag-07)

*Sketch.* Passages retrieved from an index are placed in the prompt and treated as knowledge.
Whoever can add or edit a document can put text in the model's context; retrieval runs as some
identity; copies of documents and embeddings live in a new store.

- **Planted documents steer answers or carry instructions** [rag-01]. *High.* A few injected
  texts can make a retrieval system give an attacker-chosen answer [R19]; a post in a public
  channel, once retrieved, made an assistant leak a secret from a private channel through a link
  [R20, AML.CS0035]; one-pixel text in a shared document and a public web form's free-text field
  carried instructions into connected assistants [R42][R44]. *Evidence: disclosed
  vulnerability* [R25][R42][R44].
- **Retrieval crosses permission boundaries, and secrets become searchable** [rag-02, rag-03,
  rag-04]. *High.* One vendor states that its assistant surfaces only data the user can at least
  view [R21]: correct, and it means existing oversharing becomes findable in plain language.
  Indexes built with an indexer's wider rights, or stale permissions, cross boundaries directly.
  *Evidence:* rag-03 *disclosed vulnerability* (an injected search of a drive for API keys
  [R42]); rag-02 and rag-04 *theoretical*.
- **Private content leaves through the rendered answer** [rag-05]. *High.* EchoLeak, a single
  crafted email to a production assistant, bypassed its injection classifier and link redaction
  and used auto-fetched images through a proxy its content-security policy allowed, with no user
  interaction (CVE-2025-32711) [R25]. The channel recurred: image URLs carrying keys [R42], an
  expired domain still on an allowlist [R44], a dictionary of static URLs [R20, AML.CS0066].
  *Evidence: disclosed vulnerability* [R25][R44].
- **Trusted-looking wrong answers, and the store itself** [rag-06, rag-07]. *Medium.* Citations
  make passages look checked; hidden text in an email made a summary carry a fabricated security
  warning [R70]. Chunks and embeddings may outlive deletion of the source. *Evidence:* rag-06
  *demonstrated* [R70]; rag-07 *theoretical* for indexes (see K6 for a vendor store) [R64].

### 5.6 Multi-agent systems and subagents (template `multi-agent`, ma-01 to ma-07)

*Sketch.* An orchestrator hands tasks, context and sometimes credentials to other agents and
treats what they return as input. Messages between agents are model-written text; no single
transcript shows the whole action.

- **An injection spreads from agent to agent** [ma-01]. *High.* Research shows prompts that
  self-replicate across connected agents [R22], and adversarial web content making multi-agent
  frameworks run arbitrary code in 58–90% of trials even when individual agents refuse harmful
  requests [R23]. A hijacked assistant mailed its injection to the victim's contacts' agents
  [R20, AML.CS0066]; evaluation agents planted injections for other AI systems [R62]. *Evidence:
  demonstrated* [R22][R20]; *observed* in an evaluation [R62].
- **Delegation widens privileges, and context is over-shared** [ma-02, ma-05]. *High.* In one
  coding agent subagents inherit the parent's built-in and MCP tools by default, and when the
  parent runs in bypass or auto mode the subagent runs in that mode whatever its own setting
  [R24]. *Evidence: theoretical*; the nearest disclosed case is an MCP server package that could
  deliver one client's messages to another [R50].
- **Who sent this, and who did that** [ma-03, ma-06, ma-07]. *Medium to High.* The same agent
  marks subagent reports as carrying no authority from the user, but says that marking is not a
  substitute for restricting what a subagent can reach [R24]. Third-party agents can change
  without notice. An agent social network exposed agent API tokens and private agent-to-agent
  conversations [R55]; an espionage operator split work so that no single step looked harmful
  [R56]; an internal agent removed its monitor and denied it [R63], and about 10% of one
  developer's eligible internal agent traffic went unmonitored from May to July 2026 [R61].
  *Evidence: disclosed vulnerability* [R55]; *observed* [R56][R63].
- **One failure cascades** [ma-04]. *Medium.* In the 2026 evaluation incident above, about 1,200
  agent runs exchanged more than 70,000 messages through a shared board they built themselves
  [R20, AML.CS0068]. *Evidence: observed* (failure) [R20].

### 5.7 Scheduled and background agents (template `background-agents`, bg-01 to bg-07)

*Sketch.* Runs start from a clock, an event or another system, with nobody watching, using
credentials stored for the purpose. Whatever fires the trigger may also supply the instructions.

- **A trigger an outsider can fire or shape** [bg-01]. *Critical* where outsiders can cause
  the event. CI agents given issue and pull request text with privileged tokens were exploitable
  this way [R26], and one such workflow led to an unauthorised package release [R59]; agents
  watching an inbox, a ticket queue and web-form leads were steered by what outsiders sent [R20,
  AML.CS0037, AML.CS0039][R44]. One hosted agent ignores events from users without write access
  by default and lets automations be limited to the triggering issue [R27]. *Evidence:
  observed* [R59]; *disclosed vulnerability* [R26][R44].
- **Standing credentials** [bg-02]. *High.* Tokens for unattended runs are long-lived (one coding
  agent issues a one-year token for scripts and CI [R28]) and can outlive the person who set the
  task up; an over-scoped CI token let an outsider commit a destructive agent prompt into a
  shipped extension [R20, AML.CS0047]. *Evidence: observed* [R20][R59].
- **Nobody present, nobody notices, nobody can stop it quickly** [bg-03, bg-06, bg-07].
  *High.* A vendor found evaluation incidents dating from April only through a retrospective
  transcript review in July [R29]; an evaluator with security monitoring but no review that
  could block agent actions as they happened stopped runs within an hour of an alert [R62].
  Designs that help: agents that cannot approve or merge their own pull requests, and workflows
  that wait for a person [R27]. *Evidence: observed* [R29][R62].
- **A changed task or a delayed instruction keeps running** [bg-04]. *Medium.* An instruction
  planted for the next turn bypassed a control that only checked the turn in which untrusted data
  arrived [R20, AML.CS0038]; a web page made a self-hosted agent write instructions into its
  future system prompts [R20, AML.CS0051]. *Evidence: demonstrated* [R20].
- **Runaway runs** [bg-05]. *Low* with caps on time, frequency, retries and spend. *Evidence:
  theoretical* for scheduled features; one project reported millions of API requests it
  attributes to another developer's agents [R63].

## 6. Framework mapping

Framework ids are from the OWASP Top 10 for LLM Applications 2026 [R30], the OWASP Top 10 for
Agentic Applications for 2026 [R31], the OWASP MCP Top 10, which is a beta (v0.1) [R32], and
MITRE ATLAS release 2026.10 [R20]; [frameworks.md](frameworks.md) lists them, with the
2025-to-2026 OWASP LLM crosswalk. The template's ATLAS ids are kept; ids in *italics* were added
here after checking them against the ATLAS 2026.10 data and are not in the
`agent-feature-review` templates, nor are the MCP ids. `—` means no listed item fits.

### 6.1 Per threat

| Threat | OWASP LLM 2026 | OWASP Agentic | OWASP MCP | MITRE ATLAS |
|---|---|---|---|---|
| K1 | LLM01:2026, LLM08:2026 | ASI01 | MCP06:2025 | AML.T0051.001, AML.T0051.002, AML.T0084.001 |
| K2 | LLM03:2026 | ASI03 | MCP01:2025, MCP07:2025 | AML.T0083, AML.T0091.000, AML.T0098 |
| K3 | LLM02:2026, LLM10:2026 | ASI02 | — | AML.T0086, AML.T0077, AML.T0136 |
| K4 | LLM04:2026 | ASI04 | MCP03:2025, MCP04:2025 | AML.T0010.005, AML.T0109, AML.T0115.002 |
| K5 | LLM01:2026 | ASI06 | — | AML.T0080.000, AML.T0142 |
| K6 | LLM02:2026 | ASI04 | MCP02:2025, MCP08:2025, MCP09:2025 | AML.T0081, AML.T0109, AML.T0132 |
| K7 | LLM01:2026 | ASI02 | — | AML.T0053, AML.T0054, AML.T0116, AML.T0124 |
| K8 | LLM03:2026 | ASI10 | — | AML.T0105, AML.T0118.000, AML.T0138 |
| cu-01 | LLM01:2026 | ASI01 | — | AML.T0051.001, AML.T0100, AML.T0129, *AML.T0131* |
| cu-02 | LLM03:2026 | ASI03 | — | AML.T0112.000, *AML.T0098* |
| cu-03 | LLM03:2026 | ASI02 | — | AML.T0053 |
| cu-04 | LLM02:2026 | ASI02 | — | AML.T0086 |
| cu-05 | — | — | — | — (see K7) |
| cu-06 | — | ASI09 | — | — |
| cu-07 | — | ASI05 | — | AML.T0112.000, AML.T0011.003 |
| mem-01 | LLM01:2026, *LLM05:2026* | ASI06 | — | AML.T0080.000, AML.T0051.001, *AML.T0131* |
| mem-02 | LLM02:2026 | — | MCP10:2025 | AML.T0085.002 |
| mem-03 | LLM02:2026, *LLM09:2026* | — | MCP10:2025 | — |
| mem-04 | LLM02:2026 | — | MCP01:2025 | — |
| mem-05 | LLM07:2026 | — | — | *AML.T0130* |
| mem-06 | — | ASI06 | — | AML.T0080.000, AML.T0092 |
| mcp-01 | LLM01:2026 | ASI04 | MCP03:2025 | AML.T0110, AML.T0011.002, *AML.T0110.000* |
| mcp-02 | LLM01:2026 | ASI01 | MCP06:2025 | AML.T0051.001, AML.T0099, *AML.T0110.002* |
| mcp-03 | LLM04:2026 | ASI04 | MCP03:2025, MCP04:2025 | AML.T0010.005, AML.T0109, AML.T0115.002, *AML.T0111* |
| mcp-04 | LLM03:2026 | ASI03 | MCP01:2025, MCP02:2025, MCP07:2025 | AML.T0098, AML.T0083, *AML.T0091.000* |
| mcp-05 | LLM02:2026 | ASI02 | — | AML.T0086, AML.T0085.001 |
| mcp-06 | LLM03:2026 | ASI02 | — | AML.T0101, AML.T0053 |
| mcp-07 | *LLM10:2026* | — | MCP05:2025, MCP07:2025, MCP09:2025 | AML.T0132, *AML.T0049*, *AML.T0078* |
| exec-01 | LLM01:2026, LLM10:2026 | ASI05 | MCP05:2025 | AML.T0050, AML.T0051.001 |
| exec-02 | — | ASI05 | — | AML.T0105 |
| exec-03 | LLM02:2026 | ASI02 | — | AML.T0086 |
| exec-04 | LLM02:2026 | ASI03 | MCP01:2025 | AML.T0055, AML.T0037 |
| exec-05 | LLM04:2026 | ASI04 | MCP04:2025 | AML.T0011.001, AML.T0060 |
| exec-06 | LLM06:2026 | — | — | AML.T0034.002 |
| exec-07 | LLM10:2026 | — | — | — |
| exec-08 | — | — | — | — (see K7) |
| rag-01 | LLM01:2026, LLM09:2026, *LLM05:2026* | ASI06 | — | AML.T0070, AML.T0071, AML.T0066, AML.T0051.001 |
| rag-02 | LLM09:2026, LLM02:2026 | — | — | AML.T0085.000 |
| rag-03 | LLM02:2026 | — | — | AML.T0082, AML.T0085.000 |
| rag-04 | LLM09:2026 | — | MCP10:2025 | — |
| rag-05 | LLM10:2026, LLM02:2026 | — | — | AML.T0077, AML.T0136 |
| rag-06 | LLM07:2026 | ASI09 | — | AML.T0067.000 |
| rag-07 | LLM09:2026 | — | — | — |
| ma-01 | LLM01:2026 | ASI07, ASI01 | — | AML.T0143, AML.T0061, AML.T0051.001 |
| ma-02 | LLM03:2026 | ASI03 | — | — |
| ma-03 | — | ASI07 | MCP07:2025 | AML.T0073 |
| ma-04 | LLM06:2026 | ASI08 | — | AML.T0034.002 |
| ma-05 | LLM02:2026 | — | MCP10:2025 | — |
| ma-06 | — | ASI10 | MCP08:2025 | — |
| ma-07 | LLM04:2026 | ASI04 | MCP04:2025 | — |
| bg-01 | LLM01:2026 | ASI01 | — | AML.T0051.002, AML.T0093, *AML.T0006.003* |
| bg-02 | LLM03:2026 | ASI03 | MCP01:2025 | AML.T0083, AML.T0055 |
| bg-03 | LLM03:2026 | ASI02 | — | AML.T0053 |
| bg-04 | — | ASI10 | — | AML.T0081, AML.T0094, AML.T0142, *AML.T0108* |
| bg-05 | LLM06:2026 | ASI08 | — | AML.T0034.002 |
| bg-06 | — | ASI10 | MCP08:2025 | — |
| bg-07 | — | — | — | — |

### 6.2 Coverage of each list

All three lists apply: the features are LLM-based, they act and drive tools, and MCP servers and
similar extensions are in scope.

| OWASP LLM 2026 | Covered by |
|---|---|
| LLM01:2026 Prompt Injection | K1, cu-01, mcp-01, mcp-02, mem-01, rag-01, ma-01, bg-01, exec-01 |
| LLM02:2026 Sensitive Information Disclosure | K3, cu-04, mcp-05, mem-02 to mem-04, rag-02, rag-03, rag-05, exec-03, exec-04, ma-05 |
| LLM03:2026 Excessive Agency | K2, K8, cu-02, cu-03, mcp-04, mcp-06, ma-02, bg-02, bg-03 |
| LLM04:2026 Supply Chain | K4, mcp-03, exec-05, ma-07 (the entry centres on models and platforms; extensions fit ASI04 and MCP04 more closely) |
| LLM05:2026 Data and Model Poisoning | rag-01, mem-01 (poisoning at retrieval and memory ingestion); training-time poisoning is in General-purpose models |
| LLM06:2026 Unbounded Consumption | exec-06, bg-05, ma-04 |
| LLM07:2026 Misinformation | rag-06, mem-05 |
| LLM08:2026 Hidden Context Exposure | K1, as reconnaissance of tool definitions and knowledge sources before an injection; extraction of a system prompt itself is in LLM applications |
| LLM09:2026 Vector and Embedding Weaknesses | rag-01, rag-02, rag-04, rag-07; mem-03 where memory is vector-backed |
| LLM10:2026 Improper Output Handling | exec-01, exec-07, rag-05, mcp-07 (tool arguments passed into commands and paths) |

| OWASP Agentic | Covered by |
|---|---|
| ASI01 Agent Goal Hijack | K1, cu-01, mcp-02, ma-01, bg-01 |
| ASI02 Tool Misuse and Exploitation | K3, K7, cu-03, cu-04, mcp-05, mcp-06, exec-03, bg-03 |
| ASI03 Identity and Privilege Abuse | K2, cu-02, mcp-04, exec-04, ma-02, bg-02 |
| ASI04 Agentic Supply Chain Vulnerabilities | K4, K6, mcp-01, mcp-03, exec-05, ma-07 |
| ASI05 Unexpected Code Execution (RCE) | cu-07, exec-01, exec-02 |
| ASI06 Memory & Context Poisoning | K5, mem-01, mem-06, rag-01 |
| ASI07 Insecure Inter-Agent Communication | ma-01, ma-03 |
| ASI08 Cascading Failures | ma-04, bg-05 |
| ASI09 Human-Agent Trust Exploitation | cu-06, rag-06 |
| ASI10 Rogue Agents | K8, bg-04, bg-06, ma-06 |

| OWASP MCP Top 10 | Covered by |
|---|---|
| MCP01:2025 Token Mismanagement & Secret Exposure | K2, mcp-04, bg-02, exec-04, mem-04 |
| MCP02:2025 Privilege Escalation via Scope Creep | mcp-04, K6 |
| MCP03:2025 Tool Poisoning (including rug pulls, schema poisoning and tool shadowing) | mcp-01, mcp-03, K4 |
| MCP04:2025 Software Supply Chain Attacks & Dependency Tampering | K4, mcp-03, exec-05, ma-07 |
| MCP05:2025 Command Injection & Execution | mcp-07, exec-01 |
| MCP06:2025 Intent Flow Subversion (titled "Prompt Injection via Contextual Payloads" before January 2026; some OWASP pages still show that title) | mcp-02, K1 |
| MCP07:2025 Insufficient Authentication & Authorization | K2, mcp-04, mcp-07, ma-03 |
| MCP08:2025 Lack of Audit and Telemetry | K6, ma-06, bg-06 |
| MCP09:2025 Shadow MCP Servers | K6, mcp-07 |
| MCP10:2025 Context Injection & Over-Sharing | mem-02, mem-03, rag-04, ma-05 |

No item of the three lists is left without a threat here.

### 6.3 ATLAS tactics and case studies

The threats use fifteen of the sixteen ATLAS tactics; only AI Model Access is unused. Execution
(prompt injection, tool invocation, user execution of poisoned tools) runs through K1, cu-01,
mcp-01, mcp-02, exec-01 and bg-01; Persistence (memory, tool and RAG poisoning, configuration
changes, event-triggered execution) through K5, mem-01, mcp-01, rag-01 and bg-04; Initial Access
(supply chain, public-facing applications, crafted links, exposed services) through K4, K6,
mcp-03, mcp-07 and bg-01; Credential Access and Lateral Movement through K2, mcp-04, exec-04,
bg-02 and ma-01; Collection and Exfiltration through K3, cu-04, mem-02, mcp-05 and rag-02 to
rag-05; Defense Evasion through mcp-03 (rug pull), bg-04 (delayed instructions), mem-06
(history manipulation), rag-06 and K8 (indicator removal); Privilege Escalation through exec-02
(escape to host), K7 (jailbreak) and the tool-invocation threats; Impact through cu-02, cu-07,
mcp-06, mem-05 and the cost threats; Reconnaissance through K7 and bg-01; Resource Development
through K4, mcp-03 and exec-05; AI Attack Adaptation through K7, K8 and rag-01; Discovery
through K1; Command and Control through bg-04.

Matching case studies in ATLAS 2026.10 (Exercise unless marked Incident): AML.CS0035 Slack AI
exfiltration (rag-01, rag-05); AML.CS0036 AIKatz (K2, mem-06); AML.CS0037 Copilot Studio agent
tools (K1, bg-01, mcp-05); AML.CS0038 delayed tool invocation (bg-04); AML.CS0039 Jira Service
Management (bg-01, mcp-02); AML.CS0040 ChatGPT memories (mem-01, mem-06); AML.CS0045 MCP server
used by Cursor (mcp-02, exec-04); AML.CS0046 computer-use data destruction (exec-01, cu-07);
AML.CS0047 Amazon Q extension, Incident (bg-02, K4); AML.CS0048 exposed ClawdBot interfaces
(mcp-07, K6); AML.CS0049 poisoned ClawdBot skill (mcp-01, mcp-03); AML.CS0050 OpenClaw one-click
RCE (mcp-07, exec-02); AML.CS0051 OpenClaw command and control (bg-04, mem-06); AML.CS0053
Postmark MCP server, Incident (mcp-03, mcp-05); AML.CS0054 remote poisoned MCP tool (mcp-01);
AML.CS0055 AI ClickFix (cu-01, cu-07); AML.CS0059 EchoLeak (rag-01, rag-05); AML.CS0062 Semantic
Kernel search plugin (exec-01); AML.CS0063 Gemini calendar invitations (mcp-02, mcp-06, bg-04);
AML.CS0066 ZombieAgent (mem-01, mem-06, ma-01, rag-05); AML.CS0067 Claude Code GitHub Action
(bg-01, exec-04); AML.CS0068 OpenAI evaluation agents and Hugging Face, Incident (K8, exec-02,
exec-03, exec-08, ma-04); AML.CS0069 GTG-1002, Incident (K7, ma-03); AML.CS0071 multi-agent
framework against government systems, Incident (K7); AML.CS0072 AI recommendation poisoning,
Incident (mem-01, mem-05); AML.CS0073 Claude agents in cyber evaluations, Incident (K8, exec-03,
exec-05); AML.CS0074 AISI evaluation agents, Incident (K8, ma-01, bg-03).

## 7. Recent incidents

2025 to November 2026, from primary sources (the references list each one). "Disclosed
vulnerability" means one reported publicly with no known exploitation.

| Date | What happened | Category | Threat ids | Source |
|---|---|---|---|---|
| 2025-02, 2026-04 | An injected issue led a browser agent to copy private data from signed-in sites into an attacker page; researchers later used another browser agent as a cross-origin bridge | Disclosed vulnerability | cu-01, cu-02, cu-04 | [Embrace The Red](https://embracethered.com/blog/posts/2025/chatgpt-operator-prompt-injection-exploits/); [UW](https://agent-security.cs.washington.edu/agentic_browsers_sop.html) |
| 2025-05 | A public issue read through a code-hosting MCP server made an agent leak private repositories into a public pull request | Disclosed vulnerability | mcp-02, mcp-04, mcp-05 | [Invariant Labs](https://invariantlabs.ai/blog/mcp-github-vulnerability) |
| 2025-06 | EchoLeak: one email made a production assistant exfiltrate data through auto-fetched images, no click (CVE-2025-32711) | Disclosed vulnerability | K1, rag-01, rag-05 | [CVE record](https://www.cve.org/CVERecord?id=CVE-2025-32711); [arXiv](https://arxiv.org/abs/2509.10540) |
| 2025-06 to 2026-11 | MCP tooling CVEs: Inspector proxy RCE, proxy client command injection from OAuth metadata, reference servers' path and argument flaws, SDK sending OAuth credentials to a server-chosen authorisation server, cross-client message delivery | Disclosed vulnerability | mcp-04, mcp-07, ma-05 | [Oligo](https://www.oligo.security/blog/critical-rce-vulnerability-in-anthropic-mcp-inspector-cve-2025-49596); [JFrog](https://jfrog.com/blog/2025-6514-critical-mcp-remote-rce-vulnerability); [CVE-2026-104850](https://www.cve.org/CVERecord?id=CVE-2026-104850); [CVE-2026-111770](https://www.cve.org/CVERecord?id=CVE-2026-111770) |
| 2025-08 | An editor's agent could write a new MCP configuration from an injection, or have an approved one swapped without a prompt (CVE-2025-54135, CVE-2025-54136) | Disclosed vulnerability | mcp-03, K6 | [CVE-2025-54135](https://www.cve.org/CVERecord?id=CVE-2025-54135); [CVE-2025-54136](https://www.cve.org/CVERecord?id=CVE-2025-54136) |
| 2025-08 to 2026-03 | One AI browser, repeatedly: hidden text drove an account takeover, a fake shop got a purchase, a crafted link exfiltrated mail (reported as not applicable by the vendor), a calendar invite led to local file theft and password-manager access | Disclosed vulnerability | cu-01 to cu-04, cu-06, cu-07 | [Brave](https://brave.com/blog/comet-prompt-injection/); [Guardio](https://guard.io/labs/scamlexity-we-put-agentic-ai-browsers-to-the-test-they-clicked-they-paid-they-failed); [LayerX](https://www.akamai.com/blog/security/2025/oct/cometjacking-how-one-click-can-turn-perplexitys-comet-ai-browser-against-you); [Zenity](https://www.zenity.io/company-overview/newsroom/company-news/zenity-labs-discloses-pleasefix-perplexedagent-vulnerability) |
| 2025-08 | Text revealed only by image downscaling made a CLI agent with an auto-approving MCP server email calendar data out | Disclosed vulnerability | cu-01, mcp-05 | [Trail of Bits](https://blog.trailofbits.com/2025/08/21/weaponizing-image-scaling-against-production-ai-systems/) |
| 2025-08 | One-pixel text in a shared document made an assistant search a connected drive for API keys and leak them in an image URL | Disclosed vulnerability | rag-01, rag-03, rag-05 | [Zenity](https://labs.zenity.io/p/agentflayer-chatgpt-connectors-0click-attack-5b41) |
| 2025-08 | Calendar invitations and email subjects made an assistant control home devices, start video and delete events (AML.CS0063) | Disclosed vulnerability | mcp-02, mcp-06, bg-04 | [SafeBreach](https://www.safebreach.com/blog/invitation-is-all-you-need-hacking-gemini/) |
| 2025-09 | A CRM agent processing a public web-form lead exfiltrated data through an image on an expired allowlisted domain | Disclosed vulnerability | bg-01, rag-01, rag-05 | [Noma](https://noma.security/blog/forcedleak-agent-risks-exposed-in-salesforce-agentforce/) |
| 2025-09 | An impersonating email MCP package, after 15 clean releases, copied every sent email to an outside address (AML.CS0053) | Attack on an AI system | mcp-03, mcp-05, K4 | [Postmark](https://postmarkapp.com/blog/information-regarding-malicious-postmark-mcp-package/) |
| 2025-09 | ZombieAgent: a connector email led an assistant to exfiltrate data, write persistent memories and mail the prompt onward (AML.CS0066) | Disclosed vulnerability (research demonstration) | mem-01, mem-06, ma-01, rag-05 | [ATLAS 2026.10](https://github.com/mitre-atlas/atlas-data/blob/main/dist/v6/ATLAS-2026.10.yaml) |
| 2025-11 | A coding agent connected through MCP to offensive tools ran 80–90% of an espionage campaign against about 30 targets (AML.CS0069) | AI used against other systems | K7, ma-03 | [Anthropic](https://www.anthropic.com/news/disrupting-AI-espionage) |
| 2025-12 to 2026-06 | CI agents steered by issue and pull request text: privileged tokens within reach; one triage workflow led to an unauthorised package release; one agent read its API key from the process environment (AML.CS0067) | Disclosed vulnerability; attack on an AI system (the release) | bg-01, bg-02, exec-04 | [Aikido](https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents); [Cline](https://cline.bot/blog/post-mortem-unauthorized-cline-cli-npm); [Microsoft](https://www.microsoft.com/en-us/security/blog/2026/06/05/securing-ci-cd-in-agentic-world-claude-code-github-action-case/) |
| 2026-01 | A shared secret and email-only account linking let an outsider drive a privileged built-in AI agent to create an administrator (CVE-2025-12420) | Disclosed vulnerability | K2, mcp-04 | [AppOmni](https://appomni.com/ao-labs/bodysnatcher-agentic-ai-security-vulnerability-in-servicenow/) |
| 2026-01 to 2026-06 | Malicious skills in a public skill registry (341 counted by one vendor); one evaded scanning by padding | Attack on an AI system | mcp-01, mcp-03, K4 | [OpenClaw](https://www.openclaw.ai/blog/virustotal-partnership); [Unit 42](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain/) |
| 2026-01 | A package name hallucinated in LLM-written agent skills spread to 237 or more repositories; registered defensively, agents then fetched it daily | Disclosed vulnerability | exec-05, mcp-03 | [Aikido](https://aikido.dev/blog/agent-skills-spreading-hallucinated-npx-commands) |
| 2026-02 | A self-hosted agent sent its gateway token to a URL from a link, letting a page disable confirmation and run commands on the host (CVE-2026-25253) | Disclosed vulnerability | mcp-07, exec-02, K2 | [depthfirst](https://depthfirst.com/post/1-click-rce-to-steal-your-moltbot-data-and-keys) |
| 2026-02 | An agent social network's database exposed about 1.5 million agent API tokens and 4,060 private agent-to-agent conversations | Disclosed vulnerability | ma-03, mcp-04, K6 | [Wiz](https://www.wiz.io/blog/exposed-moltbook-database-reveals-millions-of-api-keys) |
| 2026-02 | "Summarize with AI" links from 31 companies wrote "trusted source" memories into assistants (AML.CS0072) | Attack on an AI system | mem-01, mem-05, K1 | [Microsoft](https://www.microsoft.com/en-us/security/blog/2026/02/10/ai-recommendation-poisoning/) |
| 2026-04 | A third-party AI tool's compromised Workspace OAuth app led to an employee account takeover and access to internal systems | Attack on an AI system | K2, mcp-04 | [Vercel](https://vercel.com/kb/bulletin/vercel-april-2026-security-incident) |
| 2026-04 to 2026-07 | Evaluation agents with internet access reached real organisations and people, including a malicious package that ran on 15 systems and prompt injections planted for other AI systems (AML.CS0073, AML.CS0074) | Failure or accident | K8, exec-03, exec-05, ma-01 | [Anthropic](https://www.anthropic.com/news/investigating-incidents-cybersecurity-evals); [AISI](https://www.aisi.gov.uk/blog/incident-report-unsanctioned-agent-behaviour-during-cyber-testing) |
| 2026-06 to 2026-11 | An AI gateway's MCP test endpoints, MCP OAuth fallback and custom-code sandbox were exploited in the wild (CVE-2026-42271, CVE-2026-59822, CVE-2026-40217) | Attack on an AI system | mcp-04, mcp-07, exec-02 | [CISA KEV](https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json); [CVE-2026-42271](https://www.cve.org/CVERecord?id=CVE-2026-42271) |
| 2026-07 | Evaluation agents used a package-proxy zero-day for internet access, coordinated through a self-built message board and compromised a third party's production systems (AML.CS0068) | Failure or accident | K8, exec-02, exec-03, ma-04 | [OpenAI](https://openai.com/index/hugging-face-model-evaluation-security-incident/); [Hugging Face](https://huggingface.co/blog/security-incident-july-2026) |
| 2026-10 | A developer's internal agents turned off monitoring alerts and removed a monitoring integration; one then denied it | Failure or accident | K8, bg-06, ma-06 | [OpenAI](https://openai.com/safety-alignment/misalignment-reports/suppressing-misalignment-monitoring-alerts-and-disabling-misalignment-monitoring/) |
| 2026-10 | A breached inference provider: stored coding-agent traces with credentials copied, a tampered agent extension placed in a marketplace cache, AI chat transcripts retained contrary to contract | Attack on an AI system | K6, mcp-03 | [Cursor](https://cursor.com/blog/security-incident-update); [Notion](https://notion.com/help/security-incident-involving-a-third-party-ai-vendor) |
| 2026-11 | Two releases of an agent SDK on PyPI carried a credential stealer | Attack on an AI system | K4, mcp-03 | [Wiz](https://www.wiz.io/blog/malicious-version-of-microsofts-agent-framework-published-to-pypi) |
| 2026-11 | A nested frame escaped an assistant's HTML-preview sandbox and could exfiltrate chats with its protective mode on | Disclosed vulnerability | exec-07, exec-02, rag-05 | [Check Point](https://research.checkpoint.com/2026/chatgpt-lockdown-mode-bypass-phishing-malware-delivery-and-silent-data-exfiltration/) |

**Patterns.** Content-borne hijacks reached every feature that reads outsiders' content, and
the fixes vendors shipped were mostly on the output and egress side (image rendering, URL
allowlists, confirmations) rather than in the model. Apart from promotional memory poisoning,
the incidents exploited in the wild came through the supply chain, exposed self-hosted servers
and stolen grants; MCP vulnerabilities cluster in client tooling, SDK OAuth handling and tool
argument parsing. The new class in 2026 is agents exceeding their brief with no adversary, where
egress that nobody intended (a package proxy, a misconfiguration) turned an evaluation into an
incident at a third party.

## 8. How this repository's evaluations relate

| Threat area | Skill | What it gives | What it does not give |
|---|---|---|---|
| Every feature, every template threat above | `agent-feature-review` (guided) | One record per feature: each template threat marked evidence recorded, answers only, not applicable or not assessed; vendor evidence and its absence; tests cited; benchmarks available and not run; the deployment context in the vocabulary of a published agentic-AI scoping matrix | A rating or a decision; a measurement of anything |
| Screen-borne injection (5.1) | `vision-model-benchmark` | Whether a model follows instructions in images and makes unrequested tool calls from them, with mock tools | What a real agent clicks or runs in a real session |
| Tool-result injection, exfiltration, memory poisoning (5.2, 5.3) | `model-benchmark` (AgentDojo, AgentThreatBench checks) | Bare-model baselines in simulated environments | The vendor's product, real connectors, memory across sessions |
| Extensions (5.3, K4) | `security-tool-benchmark`, extension kind | How well a scanner of skills, plugins and MCP servers separates labelled malicious from benign samples | Whether a particular extension is safe; scanning one is outside this repository |
| Features behind the organisation's own endpoint | `app-redteam`, `app-benchmark` | Attacks through the prompt against that endpoint, with planted documents or canaries | Attacks through screens or real connectors the skills cannot drive |
| Misuse inside an agent harness (K7, 5.1, 5.4) | `agent-misuse-benchmark` | Declines of restricted tasks beside completion of legitimate twins, once completed with a harness module for the feature | Anything until completed; it ships no scenarios |

**Why the guided review.** No benchmark answers "can we switch this on here?": the answer
depends on what the feature can touch, whose identity it uses, who starts a run and where a
person must act, none of which a public test set knows. `agent-feature-review` exists so that
every threat is either backed by evidence or recorded as not assessed, rather than dropped
because no benchmark covers it. Its templates name the public benchmarks that measure part of
each threat (for computer use OS-Harm and RTC-Bench, for code execution SandboxEscapeBench, for
retrieval SafeRAG, for multi-agent systems TAMAS, among others) and say how each description was
verified; most are research code no skill here runs, and several need supervised virtual
machines. The templates carry OWASP LLM 2026, Agentic and ATLAS ids; section 6 adds the MCP
ids for the same threats.

**Left to design review, and why.** Privilege reach (K2), tenant and project isolation, egress
policy, credential storage, change control (K6), audit and stopping a task have no public test,
because they are properties of the organisation's configuration and the vendor's
infrastructure. The review records what is in place; a vendor's isolation is evidenced by the
vendor's own testing and audits. K8 has no template threat of its own and nothing here measures
it; a review records its parts under exec-02, exec-03, bg-04, bg-06 and ma-06, and the questions
below ask the rest. The offensive-tooling part of K7 (which tools and egress a feature makes
available to a misusing user or an intruder) is likewise design review.

**Open.** Public injection suites are mostly static; adaptive attacks against a vendor's
specific defences are not covered. Vendor figures (such as the browser-agent rates above) are
for the vendor's own attack set. Features change without versions, so a record describes the
feature on the day it was made.

## 9. Design review questions

- **All features.** What can the agent touch and change; who starts a run and where must a
  person act; whose identity does it use; who may enable the feature or add extensions; how will
  you learn that it changed?
- **Misuse and overreach (K7, K8).** Which enabled features give a user, or malware on a user's
  machine, a terminal, open egress or connected security tools? Is the agent's scope enforced in
  its tools and network policy, or only stated in its instructions? Does anything review
  proposed actions as they happen, and could the agent switch that review off?
- **Computer use.** Vendor-hosted VM, isolated profile, or the user's own desktop? Which
  accounts are signed in, and is a password manager reachable? Can the agent carry content
  between sites it was not asked to combine? Which actions need a person, and does the
  confirmation show what will actually happen?
- **Memory.** What causes a write, including a pre-filled prompt from a link or content the
  agent reads; does the user see it and its source; who shares the memory; can users and
  administrators list, edit and delete entries; how long are they kept?
- **Connectors and extensions.** Who runs each server; read-only or read-write; which scopes;
  acting as the asking user or a service account; to which authorisation server does the client
  send tokens, and are tokens bound to it; pinned versions, and does pinning survive a renamed
  branch or tag; alerts on changed descriptions; does any scanner in use read natural-language
  instructions in skills; how would you find servers users run outside the reviewed set; which
  enabled tools can send data out?
- **Code execution.** Who hosts the sandbox; is each session fresh; is egress off or allowlisted,
  and which package mirrors, proxies or caches can it reach; what credentials and data are
  inside, including in the process environment; can it install packages, and from where?
- **Retrieval.** Which sources are indexed and who can write to them, including public web
  forms and inboxes; whose permissions apply at query time and how fast do changes propagate;
  was the corpus checked for secrets; does the client render remote images and links?
- **Multi-agent.** What tools and credentials does each agent hold; what context does a subagent
  receive; are messages between agents tied to an agent identity; are any agents third-party;
  is there one trace across all agents, and could tasks split across agents add up to something
  no single agent would be allowed to do?
- **Background agents.** Can an outsider cause the triggering event (an issue, a ticket, an
  email, a form); what can the stored credential do and when does it expire; which actions are
  held for a person; who reviews results; is any agent activity left unlogged (for example
  during context compaction); who can pause it, and how fast?

## References

R1 to R29 were read on 2026-11-21; R30 onwards on 2026-11-24. Case studies are cited from the
MITRE ATLAS release [R20], which names the original reports. Section 6 uses the framework ids
listed in [R20] and [R30] to [R32].

- [R1] Model Context Protocol specification 2025-11-25, Security Best Practices. https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices
- [R2] Model Context Protocol specification 2025-11-25, Tools (trust and safety, security considerations). https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- [R3] Claude Code documentation, Security (MCP security). https://code.claude.com/docs/en/security
- [R4] Claude API documentation, Agent Skills (security considerations, runtime constraints, data retention). https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- [R5] Claude API documentation, Code execution tool (networking and security, data retention). https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
- [R6] Claude for Chrome announcement, 25 August 2025 (prompt-injection red-teaming figures). https://claude.com/blog/claude-for-chrome
- [R7] RedTeamCUA: Realistic Adversarial Testing of Computer-Use Agents in Hybrid Web-OS Environments, arXiv 2505.21936 (abstract). https://arxiv.org/abs/2505.21936
- [R8] Claude API documentation, Computer use tool (security considerations, prompt injection). https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
- [R9] OpenAI API documentation, Computer use guide (risks and safety). https://developers.openai.com/api/docs/guides/tools-computer-use
- [R10] Refusal-Trained LLMs Are Easily Jailbroken As Browser Agents, arXiv 2410.13886 (abstract). https://arxiv.org/abs/2410.13886
- [R11] Memory Injection Attacks on LLM Agents via Query-Only Interaction, arXiv 2503.03704 (abstract). https://arxiv.org/abs/2503.03704
- [R12] Claude Code documentation, How Claude remembers your project (auto memory). https://code.claude.com/docs/en/memory
- [R13] Claude API documentation, Memory tool (security considerations). https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- [R14] Inspect Evals listing (PersistBench). https://ukgovernmentbeis.github.io/inspect_evals/
- [R15] CVE records (read through the CVE Services API): CVE-2025-54136 https://www.cve.org/CVERecord?id=CVE-2025-54136 ; CVE-2025-49596 https://www.cve.org/CVERecord?id=CVE-2025-49596 ; CVE-2025-6514 https://www.cve.org/CVERecord?id=CVE-2025-6514
- [R16] Quantifying Frontier LLM Capabilities for Container Sandbox Escape (SandboxEscapeBench), arXiv 2603.02277 (abstract). https://arxiv.org/abs/2603.02277
- [R17] Codex documentation, Agent approvals & security (cloud internet access and secrets). https://learn.chatgpt.com/docs/agent-approvals-security.md
- [R18] We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs, arXiv 2406.10279 (abstract). https://arxiv.org/abs/2406.10279
- [R19] PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models, arXiv 2402.07867 (abstract). https://arxiv.org/abs/2402.07867
- [R20] MITRE ATLAS data release 2026.10 (modified 2026-10-28): techniques, tactics and case studies AML.CS0035 to AML.CS0040, AML.CS0045 to AML.CS0051, AML.CS0053 to AML.CS0055, AML.CS0059, AML.CS0062, AML.CS0063, AML.CS0066 to AML.CS0069, AML.CS0071 to AML.CS0074 (re-read 2026-11-24). https://github.com/mitre-atlas/atlas-data/blob/main/dist/v6/ATLAS-2026.10.yaml
- [R21] Microsoft Learn, Data, Privacy, and Security for Microsoft Copilot. https://learn.microsoft.com/en-us/copilot/plan/microsoft-365-copilot-privacy
- [R22] Prompt Infection: LLM-to-LLM Prompt Injection within Multi-Agent Systems, arXiv 2410.07283 (abstract). https://arxiv.org/abs/2410.07283
- [R23] Multi-Agent Systems Execute Arbitrary Malicious Code, arXiv 2503.12188 (abstract). https://arxiv.org/abs/2503.12188
- [R24] Claude Code documentation, Subagents. https://code.claude.com/docs/en/sub-agents
- [R25] EchoLeak: The First Real-World Zero-Click Prompt Injection Exploit in a Production LLM System, arXiv 2509.10540 (abstract); CVE-2025-32711, https://www.cve.org/CVERecord?id=CVE-2025-32711 . https://arxiv.org/abs/2509.10540
- [R26] PromptPwnd: prompt injection in GitHub Actions using AI agents, 4 December 2025. https://www.aikido.dev/blog/promptpwnd-github-actions-ai-agents
- [R27] GitHub Docs, Risks and mitigations for GitHub Copilot cloud agent (including automations). https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations
- [R28] Claude Code documentation, Authentication (long-lived tokens). https://code.claude.com/docs/en/iam
- [R29] Investigating incidents in cybersecurity evaluations, 30 July 2026. https://www.anthropic.com/news/investigating-incidents-cybersecurity-evals
- [R30] OWASP Top 10 for LLM Applications 2026 (resource page and v1.0 PDF). https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
- [R31] OWASP Top 10 for Agentic Applications for 2026 (December 2025). https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- [R32] OWASP MCP Top 10, beta (Top10 tab "version [v0.1]"); source repository at HEAD 165fe0f. https://owasp.org/www-project-mcp-top-10/ ; https://github.com/OWASP/www-project-mcp-top-10
- [R33] Embrace The Red, ChatGPT Operator prompt-injection exploits (blog post). https://embracethered.com/blog/posts/2025/chatgpt-operator-prompt-injection-exploits/
- [R34] Invariant Labs, GitHub MCP server vulnerability (blog post). https://invariantlabs.ai/blog/mcp-github-vulnerability
- [R35] Brave, blog posts on prompt injection in Perplexity Comet and on "unseeable" screenshot injections (21 October 2025). https://brave.com/blog/comet-prompt-injection/ ; https://brave.com/blog/unseeable-prompt-injections/
- [R36] Guardio Labs, Scamlexity (agentic AI browser tests). https://guard.io/labs/scamlexity-we-put-agentic-ai-browsers-to-the-test-they-clicked-they-paid-they-failed
- [R37] LayerX research, republished by Akamai, CometJacking. https://www.akamai.com/blog/security/2025/oct/cometjacking-how-one-click-can-turn-perplexitys-comet-ai-browser-against-you
- [R38] Zenity Labs, PleaseFix / PerplexedAgent disclosure. https://www.zenity.io/company-overview/newsroom/company-news/zenity-labs-discloses-pleasefix-perplexedagent-vulnerability
- [R39] OpenAI, Hardening Atlas against prompt injection, 22 December 2025. https://openai.com/index/hardening-atlas-against-prompt-injection/
- [R40] University of Washington, agentic browsers and the same-origin policy (research page). https://agent-security.cs.washington.edu/agentic_browsers_sop.html
- [R41] Trail of Bits, Weaponizing image scaling against production AI systems, 21 August 2025. https://blog.trailofbits.com/2025/08/21/weaponizing-image-scaling-against-production-ai-systems/
- [R42] Zenity Labs, AgentFlayer: ChatGPT Connectors zero-click attack. https://labs.zenity.io/p/agentflayer-chatgpt-connectors-0click-attack-5b41
- [R43] SafeBreach, Invitation Is All You Need (Gemini research). https://www.safebreach.com/blog/invitation-is-all-you-need-hacking-gemini/
- [R44] Noma Security, ForcedLeak (Salesforce Agentforce). https://noma.security/blog/forcedleak-agent-risks-exposed-in-salesforce-agentforce/
- [R45] Postmark, statement on the malicious postmark-mcp package, 25 September 2025. https://postmarkapp.com/blog/information-regarding-malicious-postmark-mcp-package/
- [R46] Microsoft Security blog, AI Recommendation Poisoning, 10 February 2026. https://www.microsoft.com/en-us/security/blog/2026/02/10/ai-recommendation-poisoning/
- [R47] AppOmni, BodySnatcher (ServiceNow AI agents), 13 January 2026; CVE-2025-12420 https://www.cve.org/CVERecord?id=CVE-2025-12420 . https://appomni.com/ao-labs/bodysnatcher-agentic-ai-security-vulnerability-in-servicenow/
- [R48] Vercel, April 2026 security incident bulletin. https://vercel.com/kb/bulletin/vercel-april-2026-security-incident
- [R49] Oligo Security, Critical RCE in MCP Inspector (CVE-2025-49596); JFrog, CVE-2025-6514 in mcp-remote. https://www.oligo.security/blog/critical-rce-vulnerability-in-anthropic-mcp-inspector-cve-2025-49596 ; https://jfrog.com/blog/2025-6514-critical-mcp-remote-rce-vulnerability
- [R50] CVE records (CVE.org API): CVE-2025-54135, CVE-2025-53109, CVE-2025-53110, CVE-2025-68143, CVE-2025-68144, CVE-2025-68145, CVE-2026-104850, CVE-2026-111770, CVE-2026-86063, CVE-2026-96620, CVE-2026-42271, CVE-2026-59822, CVE-2026-40217; each at https://www.cve.org/CVERecord?id=<id>
- [R51] CISA Known Exploited Vulnerabilities catalog (feed version 2026.11.23). https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json
- [R52] OpenClaw, VirusTotal partnership announcement, 7 February 2026; Unit 42, OpenClaw skill supply-chain research, 23 June 2026. https://www.openclaw.ai/blog/virustotal-partnership ; https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain/
- [R53] Aikido, agent skills spreading hallucinated npx commands (blog post). https://aikido.dev/blog/agent-skills-spreading-hallucinated-npx-commands
- [R54] depthfirst, one-click RCE in Moltbot / OpenClaw (CVE-2026-25253). https://depthfirst.com/post/1-click-rce-to-steal-your-moltbot-data-and-keys
- [R55] Wiz, exposed Moltbook database (blog post). https://www.wiz.io/blog/exposed-moltbook-database-reveals-millions-of-api-keys
- [R56] Anthropic, report on an AI-orchestrated cyber-espionage campaign, 13 November 2025; misuse report, August 2025. https://www.anthropic.com/news/disrupting-AI-espionage ; https://www.anthropic.com/news/detecting-countering-misuse-aug-2025
- [R57] Check Point, HexStrike AI and zero-day exploitation, 2 September 2025. https://blog.checkpoint.com/executive-insights/hexstrike-ai-when-llms-meet-zero-day-exploitation/
- [R58] Nx, s1ngularity postmortem; advisory GHSA-cxm3-wv7p-598c. https://nx.dev/blog/s1ngularity-postmortem ; https://github.com/nrwl/nx/security/advisories/GHSA-cxm3-wv7p-598c
- [R59] Cline, post-mortem of the unauthorised Cline CLI npm release. https://cline.bot/blog/post-mortem-unauthorized-cline-cli-npm
- [R60] Microsoft Security blog, CI/CD in an agentic world: the Claude Code GitHub Action case, 5 June 2026. https://www.microsoft.com/en-us/security/blog/2026/06/05/securing-ci-cd-in-agentic-world-claude-code-github-action-case/
- [R61] OpenAI, two posts on the Hugging Face evaluation incident; Hugging Face, July 2026 security incident; METR, review of OpenAI agent monitoring, 22 October 2026. https://openai.com/index/hugging-face-model-evaluation-security-incident/ ; https://openai.com/index/hugging-face-incident-and-the-road-ahead/ ; https://huggingface.co/blog/security-incident-july-2026 ; https://metr.org/blog/2026-10-22-red-teaming-openai-agent-monitoring/
- [R62] UK AI Security Institute, incident report on unsanctioned agent behaviour during cyber testing, 4 August 2026. https://www.aisi.gov.uk/blog/incident-report-unsanctioned-agent-behaviour-during-cyber-testing
- [R63] OpenAI, misalignment report on suppressed and disabled monitoring (October 2026 incidents); Wikimedia Foundation, statement of 5 October 2026. https://openai.com/safety-alignment/misalignment-reports/suppressing-misalignment-monitoring-alerts-and-disabling-misalignment-monitoring/ ; https://wikimediafoundation.org/news/2026/10/05/openai-rogue-agent-activities-found-on-wikimedia-projects/
- [R64] Cursor, security incident update, 13 November 2026; Notion, help-centre notice on a third-party AI vendor incident; Fireworks AI, security bulletins. https://cursor.com/blog/security-incident-update ; https://notion.com/help/security-incident-involving-a-third-party-ai-vendor ; https://fireworks.ai/security/bulletins
- [R65] Wiz, malicious versions of Microsoft Agent Framework on PyPI. https://www.wiz.io/blog/malicious-version-of-microsofts-agent-framework-published-to-pypi
- [R66] Check Point Research, ChatGPT Lockdown Mode bypass, 5 November 2026. https://research.checkpoint.com/2026/chatgpt-lockdown-mode-bypass-phishing-malware-delivery-and-silent-data-exfiltration/
- [R67] Anthropic, research post on prompt-injection defences for browser agents, 24 November 2025. https://www.anthropic.com/research/prompt-injection-defenses
- [R68] Anthropic, Claude Mythos Preview system card, 7 April 2026 (pp. 54–56). https://www.anthropic.com/claude-mythos-preview-system-card
- [R69] VPI-Bench, arXiv 2506.02456; AdaptiveVPI, arXiv 2611.29268 (abstracts). https://arxiv.org/abs/2506.02456 ; https://arxiv.org/abs/2611.29268
- [R70] 0DIN, Phishing for Gemini (blog post). https://0din.ai/blog/phishing-for-gemini
