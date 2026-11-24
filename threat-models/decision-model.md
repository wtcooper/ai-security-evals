# Threat model: Decision and classification models

| | |
|---|---|
| Asset class | Models that take a state and typed questions with a closed answer set and return a probability per option, with no generated text (for example TypeSafe Jev, OpenAI Decisions, Microsoft-Decision-1.1, Gemini Decision 1, Cloudflare Clef) |
| Version | 1.1 |
| Date | 2026-11-24 |
| Evaluated by | `decision-model-benchmark` |
| Related threat models | Guardrails and safety classifiers; LLM applications; Agent features; AI coding agents; Image-generation models |

## Executive summary

A decision model answers typed questions about a `state` (text or JSON, and for some vendors
images, PDF, audio or video): yes/no, one choice among labelled options, or a score on an ordered
scale. It returns a probability for every option and writes no text and no reason. The policy is
not trained in: it arrives in every request as the question's instructions and each option's label
and criteria. These models are cheap (a few US cents per million input tokens) and fast, so they are
being placed directly in the path of automated actions: approving an agent's tool calls, screening
documents for prompt injection, routing alerts, grading model output.

| Core risk | Why it matters | Inherent risk* |
|---|---|---|
| The judged content argues its way to "allow" | The state is one input. Text an outside party wrote, including plain arguments with no command in them or a counterfeit policy, moves the decision | Critical |
| The gate is a confused deputy for an agent | A gate approving an agent's tool call reads context the attacker wrote; in the one published study a simple deterministic rule beat every model | Critical |
| Wrong on plain cases, in the direction that hurts | With no attack at all, the gate allows what the policy blocks; one accuracy figure hides which way it fails | Critical |
| The policy text is attackable | Labels and criteria are prompt. A reassuring name on the permissive option pushed published gates close to total fail-open | High |
| Confidence and refusals are not a safety net | Flipped decisions are as confident as kept ones, and a refusal, error or forced choice treated as allow is a bypass | High |
| The model you reviewed is not the one answering | Aliases move by design, no vendor offers a seed, and a vendor's model version changed in the week version 1.0 of this document was written | High |
| The gated agent goes around the gate | An agent that can edit the policy, the cut-off or its own monitoring, or reach the system another way, makes the gate irrelevant; agents have disabled their own monitoring | High |
| Forged evidence passes as fact | Generative tools make receipts, identity documents, screenshots and faces cheap; automated expense and identity screening already meets them at scale | Medium (High where the gate judges documents or people) |

\*For the reference deployment below, using the Likelihood × Impact matrix in this folder's
README. Ratings order attention; they are not acceptance thresholds.

**Where risk concentrates.** Wherever an outside party writes part of the state while the decisive
facts are judged by the model instead of checked by code; wherever the model's "allow" is the only
thing between an automated system and a consequential action; wherever the agent being gated can
reach the gate's own configuration; and in the caller's code, which decides what a refusal, an
error, a forced choice or a borderline probability means. The vendors' own guidance points the same
way: keep deterministic rules and side effects in code and treat the state as untrusted [1][5][9].

**What the public evidence shows (to November 2026).** Every published attack on a typed decision
model is research or a disclosed weakness (option-label renames, fact-free persuasion, counterfeit
policy text, image manipulation); no exploitation of a deployed decision gate has been reported.
Other automated gates doing the same jobs were attacked in deployed systems, mostly with forged
inputs (AI-generated receipts against expense screening, AI-altered identity documents and
deepfakes against identity and hiring checks) and with hidden prompts aimed at LLM reviewers and
LLM malware triage (see Recent incidents).

**What the evaluations can and cannot tell you.** `decision-model-benchmark` ranks candidate models
on the same seeded cases: errors on clean labelled cases in each direction, decisions flipped by
fixed public injections and edits (against the flip rate of identical re-sends), calibration, and
refusals. That finds models that fail cheaply. It cannot show resistance to an attacker who adapts
to the model or uses its returned probabilities, and it does not test agents in the loop, images or
documents (so no forged evidence), whether the gate can be bypassed, most languages, drift between
runs or bias.

## Scope and reference deployment

**Reference deployment (what the ratings assume).** A hosted, closed-weight decision model used as
an automated gate in two places: approving or blocking an internal operations agent's proposed tool
calls, and screening retrieved documents and inbound messages for prompt injection before they reach
an LLM assistant. The deploying team writes the policy in code; some option lists are filled from
configuration. The state mixes trusted fields (call arguments, environment, ticket status) with
text an outside party can write (documents, tool output, email, alert descriptions). The caller acts
on the top answer or a probability cut-off with no person in the loop for allowed decisions; low
confidence goes to a review queue. Allowed actions can change production data or send data out.
Anyone can open an account with the same vendor and query the same public model.

**Variants that move the ratings.**
- *Routing and triage*: a wrong answer delays handling rather than running an action, so impact
  falls; reviewer flooding matters more.
- *Grading model output*: the graded model writes the state, so injection stays likely.
- *Decisions about people* (applicants, customers, claims): bias and auditability become High.
- *Documents, images or receipts in the state* (expenses, claims, identity, hiring): forged
  evidence (threat 11) becomes High.
- *Self-hosted open weights* (Clef, Strands Decider) [14]: vendor data handling drops away; anyone
  can run the same weights offline, so tuned attacks get easier; artefact provenance matters.
- *Aggregators* (OpenRouter): another party in the data path, and routing decides who answers [13].
- *Probabilities shown to requesters* (a screening API offered to tenants): search and leakage rise.

**Out of scope here:** the agent being gated and the assistant behind a screen (covered by the Agent
features, AI coding agents and LLM applications threat models), the vendor's infrastructure, and
training-data poisoning. A decision model writes no text, so it gives an attacker little direct
uplift; the reverse direction, generative tools used to make the gate's inputs, is in scope
(threat 11).

## System model and threat actors

```mermaid
flowchart LR
  subgraph OUT["Untrusted: outside parties"]
    EXT["Documents, email, web pages,<br/>tool output, alert text"]
  end
  subgraph ORG["Deploying organisation"]
    AG["Agent proposing<br/>an action"]
    POL["Policy: instructions,<br/>labels, criteria<br/>(some from config)"]
    RB["Request builder"]
    MAP["Caller code: cut-off;<br/>refusal, error, timeout"]
    ACT["Gated action"]
    LOG["Logs, review queue"]
  end
  subgraph VEND["Vendor or aggregator"]
    API["Decision API and model<br/>(id or alias)"]
  end
  EXT -->|untrusted state| RB
  EXT -.->|read by| AG
  AG -->|proposed call| RB
  POL --> RB
  RB -->|state + questions| API
  API -->|probabilities, refusal, error| MAP
  MAP -->|allow| ACT
  MAP --> LOG
```

Four trust boundaries matter. Inside the state, attacker-written fields sit beside trusted ones, and
only OpenAI's format separates user, developer and tool-output positions [9]. The question is the
policy, so whoever writes labels or criteria (directly or through a template) writes the policy. The
model behind an id belongs to the vendor and can change without notice. The caller's code turns
probabilities into an action and decides what an unanswered request means. A fifth line is easy to
miss: the gate constrains only the paths that pass through it, and the agent it gates may hold
permissions on the configuration in the middle box.

| Threat actor | Capability and access | Motivation |
|---|---|---|
| External content author | Writes text that reaches the state; can test variants offline against the same public model with a guessed policy | Get a harmful call approved, slip injected content to an assistant, hide an incident |
| Hijacked or misaligned agent, or whoever controls it | Shapes both the proposed action and the context the gate reads; may hold permissions near the gate's configuration | Approval of its action, or no gate in its way |
| Requester who can query the gate | Many queries; sees allow/block, or full probabilities where exposed | Find an input that passes; learn the policy boundary |
| Fraudster with generative tools | Makes receipts, identity documents, screenshots, deepfaked faces and voices; resubmits variants | Money, an account, a job, an approval |
| Insider or integration author | Edits labels, criteria, templates, cut-offs, error handling | Weaken the policy, by intent or by mistake |
| Vendor or aggregator (not malicious) | Changes the model behind an alias, routes requests, retains data | Product change, abuse monitoring |

## Core threats

Ratings are Likelihood / Impact → inherent risk for the reference deployment. Ids in backticks
are the ones `decision-model-benchmark` uses where it measures the threat. Each *Evidence* line
opens with the strongest evidence status found: observed in deployed systems (an incident),
disclosed vulnerability (an advisory or vendor-acknowledged weakness, not known exploited),
demonstrated in research, or theoretical. Framework ids are in the Framework mapping section.

**1. Injection in the judged content** (`dm-injection`). Commands, claimed approvals, fake
validation results, unverified opinions, flawed arguments or a counterfeit policy (text that
redefines the task) in an untrusted field change the decision. TypeSafe: "State is data, and Jev
does not treat it as hostile by default" [1]; Google: "Treat input as untrusted. User-supplied text
can argue for its own classification" [11].
- *Evidence* (disclosed weakness; demonstrated in research; observed against LLM reviewers and LLM
  malware triage in the same role): black-box attacks flipped 46.3% of Jev's correct decisions
  against 0.17% for identical re-runs, an argument with no command 77.2% [16], and comments adding
  no fact about a third [27]; a prepended counterfeit policy cut Jev's `has_prompt_injection`
  recall from 82.90% to 3.88% [29]; as a detector Jev reached AUROC 0.871 against 0.897 for an LLM
  judge [18]. Hidden prompts aimed at LLM peer review appeared in 18 arXiv manuscripts [30] and
  flipped LLM reviewers from reject to accept in up to 86.26% of cases on open models [31];
  malware samples from 2025–2026 carry text aimed at LLM triage [32][33]. Rates are on
  attack-selected hard sets, not everyday traffic.
- *Rating*: High / High → **Critical**. Lower when the decisive facts sit in typed trusted fields
  that code checks, and when the state carries only the fields a question needs; the one defence
  reported against fact-free persuasion accepts a changed decision only if it recurs without the
  outside text [27].

**2. The gate as a confused deputy for an agent.** A model approving an agent's tool calls reads the
proposed call and the context the agent worked from. If the agent was hijacked, the attacker wrote
both the action and its justification. Vendors promote this use: Microsoft's example yes/no is
"whether a tool call touches production data" [8], and Google says Search uses its API as a safety
layer for MCP tools [12]. One model behind many gates also means one universal attack, or one
error class, repeats across all of them.
- *Evidence* (demonstrated in research; disclosed vulnerability in one integration): as agent
  guardrails, allow/block accuracy was 36–72% against a 50% chance level, while a deterministic rule
  over parsed typed values "reaches 100% accuracy on all six policies"; the authors conclude these
  models "should not be the component that decides" [15]. A decision-model guardrail rejected a
  jailbreak and accepted it with an inserted argument [16]. In LangChain's tool-risk gating, which
  blocks at 0.5, a counterfeit policy in a user-editable profile field lowered the mean risk score
  of an unauthorised edit from 0.893 to 0.290 over 40 runs [29]. No incident in which a decision
  gate approved a harmful agent action has been reported.
- *Rating*: High / High → **Critical**, resting on research, one disclosed integration weakness and
  the exposure of the reference deployment rather than on an incident. Falls sharply when
  authorisation is a deterministic rule over call fields and the model only reduces review load.

**3. Fail-open on clean cases** (`dm-fail-open`). With no attack, the gate allows what the policy
blocks. Fail-open and fail-closed cost different things, and a model that defaults to "allow" can
look accurate. TypeSafe documents weak spots: arithmetic, counting, dates, double negatives, literal
reading, and accuracy that "falls as the state grows with content unrelated to the decision" [1].
Microsoft: as a safety filter it "might miss subtle harmful content or flag benign content" [8].
- *Evidence* (demonstrated in research; documented by vendors): the 36–72% clean accuracy of seven
  open-weight models used as agent guardrails [15], and the vendor limitations above [1][8].
- *Rating*: High / High → **Critical**. Moves with how much of the policy needs arithmetic or dates,
  and with whether the cut-off was set from the organisation's own labelled cases.

**4. Attackable policy text** (`dm-option-channel`). Labels and criteria are part of the prompt. A
reassuring label on the permissive option (`compliant`, `already_contained`) pulls decisions toward
it even with its criteria unchanged; if option text is templated from data or edited outside the
policy owners, the policy itself is attacker-reachable. Policy-like text placed in the state
(threat 1) reaches a similar effect without touching the options [29].
- *Evidence* (demonstrated in research; documented by vendors): renaming the permissive option
  raised fail-open to 93–100% on four models, and every defence tested was defeated [15];
  Microsoft: "Scores can change based on how you phrase or order questions and options" [8].
- *Rating*: Medium / High → **High**. Low when policy text is reviewed code with no data-derived
  labels.

**5. Searchable brittleness** (`dm-perturbation`, `dm-nondeterminism`). Padding, rewording, option
order, encodings, extra fields and, for image input, small visual edits move decisions without
changing the right answer, and every response returns a fine-grained score. Score-based and
label-only black-box attacks optimise against exactly that, often in under 1,000 queries against
classifiers [22]; for a public API the attacker can search offline against the same model for a few
cents per thousand trials [3][9]. Identical requests can also get different answers, which gives
free retries near the boundary.
- *Evidence* (demonstrated in research; repeated evasion observed against a moderation gate): six
  lines of irrelevant log text raised fail-open from 0% to 63% [15]; "Jev leans toward the option
  that comes first" [1]; one open model scored 21% instead of 72% with yes/no options reversed
  [20]; score feedback doubled the attacker-target probability found during optimisation, though
  success on fresh calls rose only from 1.8% to 3.5% [17]; perturbation robustness did not predict
  injection robustness [19]; image manipulations found with typed-output feedback alone reached up
  to 69.6% success on Jev's image input, and universal ones 33.15% on unseen images [28]. Outside
  decision models, an advertiser made "multiple attempts" to get around Meta's automated ad review
  to keep placing removed ads [34].
- *Rating*: Medium / High → **High**; High likelihood for open weights or exposed probabilities.

**6. Confidence and unanswered requests are not a safety net.** "Send low-confidence decisions to a
person" works only if wrong decisions are less confident. Vendor `confidence` also means different
things: TypeSafe's "measures how concentrated the answer's probabilities are, which is different
from the probability that the selected answer is correct" [2], while Gemini defines it as the
estimated probability the top answer is right [11]. A choice question always picks an option, even
when none applies [4]. When the model does not answer (a per-question refusal at OpenAI and
OpenRouter, an HTTP 400 safety block at Gemini, a context or overload error at TypeSafe [6][9][11]
[13]) the caller decides, and a fall-through to allow is a bypass an attacker can provoke.
Reviewers see only what the gate escalates, so confident wrong allows never reach a person, and a
flood of borderline cases wears the queue down.
- *Evidence* (demonstrated in research): "a decision an attack has reversed is no less confident
  than the one it replaced" [15]; at a 0.8 threshold 23.5% of executed decisions were wrong [16]; a
  1% false-negative target needed over 91.8% escalation [18].
- *Rating*: High / Medium → **High** (for misleading confidence); unanswered handling is High impact
  wherever it defaults to allow.

**7. The model reviewed is not the model answering** (`dm-nondeterminism` covers the within-run
part). TypeSafe: "An alias moves when a new release ships, so its answers can change without any
change to your code" [3]. Microsoft's request names a deployment, not a model; its page described
Microsoft-Decision-1 in preview when `decision-model-benchmark` was written on 2026-11-14 and
Microsoft-Decision-1.1, generally available, on 2026-11-21 [8]. No seed or determinism setting
appears in the vendor pages read [3][8][9][11]. Every gate on the same alias moves at once.
- *Evidence* (documented vendor behaviour; no incident found): the alias and version changes
  above. Evaluations can drift from production on the vendor's side too: OpenAI corrected a voice
  model's system card after finding its safety evaluations had run on "a backend configuration that
  did not match the final model release" [45].
- *Rating*: High / Medium → **High**. Lower with pinned versioned ids, a per-response check of the
  reported model id, and labelled cases re-run on every change.

**8. Data handling and leakage through the API.** The judged content is usually the sensitive part
and goes to the vendor on every request. OpenAI's Decisions API supports zero data retention for
eligible customers, with 30-day abuse-monitoring logs by default across the API [9][10]; TypeSafe
offers a DPA, no training on user data, and zero retention for enterprise customers [7];
Microsoft's `DataZoneStandard` keeps processing in a data zone while `GlobalStandard` may use any
region [8]; Google's launch post says nothing on storage [12]. Separately, probabilities let a prober
map the policy boundary (the limit, what counts as internal), and prompt caching (on by default for
OpenAI Decisions [9]) makes timing data-dependent.
- *Evidence* (theoretical for decision models; demonstrated in research for other APIs): an audit
  found caches shared across users at seven providers in 2025 [25]; no study of policy extraction
  from decision models was found.
- *Rating*: Medium / Medium → **Medium**; Low for retention with self-hosted weights.

**9. Cost and context abuse.** Billing is per input token and limits are large: 64k tokens by
default at TypeSafe and 262k with a long-context switch that is slower and less accurate [3], up to
400 questions per request at OpenAI [9], up to 1,000 within 262,144 tokens at Gemini [11]. An
attacker who writes to the state can inflate it to spend money, add latency, dilute decisive facts,
or push the request past a limit so it errors (which joins threat 6).
- *Evidence* (theoretical; the limits are vendor-documented): no incident or study found.
- *Rating*: Medium / Medium → **Medium**.

**10. Decisions about people: bias and no rationale.** Microsoft: the model "might reflect biases
from its base model and training data. Don't use its scores as the sole basis for decisions about
individuals", and it "doesn't generate a free-form response or written rationale" [8]. LLM judges
show position and verbosity biases [24]. Without a rationale, a disputed or harmful decision can be
reconstructed only from what the caller logged (state, distribution, model id, policy version).
- *Evidence* (alleged in litigation, for automated applicant screening): a US federal court
  preliminarily certified an age-discrimination collective over the alleged use of an AI
  recommendation system "to score, sort, rank, or screen applicants"; the allegations are not
  findings, and the system is not a typed decision model [35].
- *Rating*: Low / High → **Medium** in the reference deployment, which decides about calls and
  documents; **High** for any deployment that decides about people.

**11. Forged evidence passes as fact.** Where the state carries a receipt, an invoice, an identity
document, a screenshot, a selfie or a recording, the gate is asked to judge facts that generative
tools now fabricate cheaply. Unlike threat 1, the forgery neither instructs nor argues; it shows.
A decision model judges what an artefact says and how plausible it looks, not whether it is
genuine, and the vendors that accept images, PDF, audio or video [8][11] describe no authenticity
check. In the reference deployment the same pattern is a fabricated approval, ticket or test
result in the context an agent hands the gate.
- *Evidence* (observed in deployed systems against other automated and human screening;
  demonstrated in research against a decision model): in one expense-audit vendor's data,
  AI-generated receipts rose from none in March 2025 to 70.8% of flagged fraudulent receipts by
  May 2026, mostly below review thresholds [36]; threat reports describe AI-generated or altered
  identity documents and deepfakes aimed at identity, liveness and hiring checks [37][38][39][40]
  [41][43], and a vendor passed Sora 2's cameo liveness check with real-time deepfakes [42].
  VisualJevBench tested "visual evidence spoofing" against Jev's image input [28]. None of the
  incidents involved a typed decision model.
- *Rating*: Low / High → **Medium** in the reference deployment, which judges calls and text;
  **High** for any gate that judges submitted documents, images or people. Lower where authenticity
  is established outside the model (issuer lookups, signed provenance, capture from a trusted
  device) and the model judges only what passed.

**12. The gated agent goes around the gate.** A gate constrains only the actions that pass through
it. An operations agent with permissions near the gate can edit the option lists filled from
configuration, change a cut-off or the error handling, switch off the logging that feeds review, or
reach the same system through another tool or credential. A hijacked agent can be steered to do
this; a misaligned one can do it while pursuing its task. An allow is also not authorisation: one
the agent can replay, or that unlocks more than the call judged, widens what it may do.
- *Evidence* (observed in deployed systems, for monitoring controls rather than decision gates):
  OpenAI reported that in October 2026 one internal agent repairing an evaluation pipeline disabled
  automatic alerts to its security team, and another removed its monitoring integration and then
  "falsely claimed to the user that it had not removed the monitor" [44]. No case involving a
  decision gate was found.
- *Rating*: Medium / High → **High**. Lower when the policy, cut-off and error handling sit where
  the gated agent cannot write, every path to the gated systems passes through the gate, and an
  allow covers exactly the call judged.

## Framework mapping

Versions: OWASP Top 10 for LLM Applications 2026 [26]; OWASP Top 10 for Agentic Applications for
2026 [46], applied only where the gate approves an agent's actions; MITRE ATLAS data release
2026.10 [23]. LLM ids use the 2026 numbering; the 2025 to 2026 crosswalk is in
[frameworks.md](frameworks.md).

**(a) Per threat.**

| Threat | OWASP LLM | OWASP Agentic | OWASP MCP | MITRE ATLAS |
|---|---|---|---|---|
| 1 Injection in the judged content | LLM01:2026 | — | — | AML.T0051.001, AML.T0015, AML.T0068 |
| 2 Confused deputy for an agent | LLM01:2026, LLM03:2026, LLM10:2026 | ASI01, ASI02, ASI03, ASI08 | — | AML.T0051.001, AML.T0053, AML.T0015 |
| 3 Fail-open on clean cases | LLM07:2026 | ASI08 | — | — (no adversary) |
| 4 Attackable policy text | LLM01:2026 | — | — | AML.T0051.001 (option text from data), AML.T0015 |
| 5 Searchable brittleness | LLM01:2026 | — | — | AML.T0040, AML.T0043.001, AML.T0043.002, AML.T0005.001, AML.T0015, AML.T0068 |
| 6 Confidence and unanswered requests | LLM10:2026, LLM07:2026 | ASI09 | — | AML.T0029, AML.T0046 |
| 7 Model reviewed is not the one answering | LLM04:2026 (partly) | ASI04 (partly), ASI08 | — | — |
| 8 Data handling and leakage | LLM02:2026, LLM08:2026 | — | — | AML.T0013, AML.T0024 |
| 9 Cost and context abuse | LLM06:2026 | — | — | AML.T0034.001, AML.T0029 |
| 10 Decisions about people | LLM07:2026 | — | — | — |
| 11 Forged evidence | LLM07:2026 (partly) | — | — | AML.T0088, AML.T0043.003, AML.T0015, AML.T0016.002, AML.T0048.000 |
| 12 Gated agent goes around the gate | LLM03:2026 | ASI03, ASI10 | — | AML.T0081, AML.T0138 |

**(b) Coverage check.** OWASP Top 10 for LLM Applications 2026 (a decision model is LLM-based, so
every item is checked):

| Item | Covered by | Note |
|---|---|---|
| LLM01:2026 Prompt Injection | 1, 2, 4, 5 | The state, the option text and the form of the input are all prompt |
| LLM02:2026 Sensitive Information Disclosure | 8 | The item names observable inference properties, which includes cache timing |
| LLM03:2026 Excessive Agency | 2, 12 | The decision model has no tools; the agency is the gated agent's, and the gate is a control on it |
| LLM04:2026 Supply Chain | 7 (partly) | An unannounced model change behind an alias; self-hosted weights and aggregators are variants in Scope |
| LLM05:2026 Data and Model Poisoning | Not applicable here | Hosted model, no fine-tuning, vendor training out of scope; a deployment that fine-tunes a decision model on its own labels takes this item on |
| LLM06:2026 Unbounded Consumption | 9 | |
| LLM07:2026 Misinformation | 3, 6, 10, 11 | A wrong but confident probability is output "credible enough to drive ... an automated workflow" |
| LLM08:2026 Hidden Context Exposure | 8 | The policy is hidden context in every request; probabilities can map its boundary. No extraction study found |
| LLM09:2026 Vector and Embedding Weaknesses | Not applicable here | Decision APIs as documented have no retrieval or embedding layer; a state built by retrieval belongs to the LLM applications threat model |
| LLM10:2026 Improper Output Handling | 2, 6 | The caller's code turns a distribution, a refusal or an error into an action |

OWASP Top 10 for Agentic Applications, for the gate on an agent's actions (the decision model is
not itself an agent):

| Item | Covered by | Note |
|---|---|---|
| ASI01 Agent Goal Hijack | 2 | The hijack is the gated agent's (Agent features threat model); threat 2 is the gate failing to catch it |
| ASI02 Tool Misuse and Exploitation | 2 | |
| ASI03 Identity and Privilege Abuse | 2, 12 | An allow used as authorisation, or covering more than the call judged |
| ASI04 Agentic Supply Chain Vulnerabilities | 7 (partly) | The gate's model is a third-party component that can change without notice |
| ASI05 Unexpected Code Execution (RCE) | Not applicable | The model returns probabilities, never code or text |
| ASI06 Memory & Context Poisoning | Not applicable to the gate | Each request is stateless; poisoned agent context reaching the gate is threat 2 |
| ASI07 Insecure Inter-Agent Communication | Not applicable | The gate is called over a vendor API, not an agent-to-agent channel |
| ASI08 Cascading Failures | 2, 3, 7 | One model behind many gates: an error class, an alias move or one universal attack shifts all of them |
| ASI09 Human-Agent Trust Exploitation | 6 | Reviewers lean on a probability and see only what the gate escalates |
| ASI10 Rogue Agents | 12 | |

OWASP MCP Top 10 (beta) [47]: not applied. A decision model is neither an MCP server nor a client;
where it gates MCP tool calls, as Google describes [12], the MCP risks belong to the Agent features
threat model.

**(c) MITRE ATLAS.** Tactics, with the techniques above that fall under each: AI Model Access
(AML.TA0000: AML.T0040); AI Attack Adaptation (AML.TA0001: AML.T0043.001–.003, AML.T0005.001,
AML.T0088); Resource Development (AML.TA0003: AML.T0005.001, AML.T0016.002); Initial Access
(AML.TA0004: AML.T0015); Execution (AML.TA0005: AML.T0051.001, AML.T0053); Persistence (AML.TA0006:
AML.T0081); Privilege Escalation (AML.TA0012: AML.T0053); Defense Evasion (AML.TA0007: AML.T0015,
AML.T0068, AML.T0081, AML.T0138); Discovery (AML.TA0008: AML.T0013); Exfiltration (AML.TA0010:
AML.T0024); Impact (AML.TA0011: AML.T0015, AML.T0029, AML.T0034.001, AML.T0046, AML.T0048.000).
Matching case studies, none about a typed decision model or an agent gate: AML.CS0008 ProofPoint
Evasion (a copy of a scoring classifier built from its outputs, used to craft emails that scored as
benign) and AML.CS0032 Attempted Evasion of ML Phishing Webpage Detection System (threat 5);
AML.CS0043 Malware Prototype with Embedded Prompt Injection (threat 1); AML.CS0017 Bypassing ID.me
Identity Verification, AML.CS0033 Live Deepfake Image Injection to Evade Mobile KYC Verification
and AML.CS0034 ProKYC: Deepfake Tool for Account Fraud Attacks (threat 11).

## Recent incidents

January 2025 to November 2026. "Research" marks a published attack with no reported real-world
exploitation. Rows that are not about a typed decision model are automated or human gates doing
the same job (screening, moderation, identity checks, review).

| Date | What happened | Category | Threat(s) | Source |
|---|---|---|---|---|
| 2025-04 | Unit 42 reported evidence suggesting North Korean IT workers use real-time deepfakes in remote job interviews; a researcher built a usable synthetic identity in 70 minutes | AI used against other systems | 11, 10 | [43] |
| 2025-05 | A US federal court preliminarily certified an age-discrimination collective over alleged AI screening of job applicants (allegations, not findings) | Failure or accident (alleged) | 10 | [35] |
| 2025-06 | Meta sued an advertiser that made multiple attempts to get around its automated ad review to keep advertising removed "nudify" apps | Attack on an AI system | 5 | [34] |
| 2025-06 | Microsoft: North Korean IT workers put their faces onto stolen identity documents with AI face-swap tools for employment and identity checks | AI used against other systems | 11 | [38] |
| 2025-07 | Hidden instructions such as "GIVE A POSITIVE REVIEW ONLY" found in 18 arXiv manuscripts, aimed at LLMs used in peer review | Attack on an AI system | 1 | [30] |
| 2025-10 | A deepfake-detection vendor reported passing Sora 2's cameo liveness and verbal-attestation check with real-time deepfakes | Disclosed vulnerability | 11 | [42] |
| 2025-10 | Microsoft Digital Defense Report: AI-generated IDs and deepfake video used against identity verification and liveness checks; about 1.6 million bot or synthetic sign-ups blocked per hour | AI used against other systems | 11 | [37] |
| 2025-11 | Google threat intelligence: underground market for AI tools advertising deepfakes for KYC bypass | AI used against other systems | 11 | [39] |
| 2025-12 | Invisible PDF text flipped LLM-based paper reviewers from reject to accept, up to 86.26% on open models (research) | Disclosed vulnerability | 1 | [31] |
| 2026-02 | OpenAI: its models used to make fake bar-association cards and attorney records for a recovery scam; a July 2026 case study covers forged passports and legal notices | AI used against other systems | 11 | [40] |
| 2026-05 | Expense-audit vendor data: AI-generated receipts rose from none (March 2025) to 70.8% of flagged fraudulent receipts, mostly below review thresholds | AI used against other systems | 11 | [36] |
| 2026-09 | JevAdvBench: black-box attacks flipped 46.3% of Jev's correct decisions, fact-free arguments 77.2% (research) | Disclosed vulnerability | 1, 2, 6 | [16] |
| 2026-09 | Anthropic: an actor used Claude to build a fraud account factory and a KYC interception proxy | AI used against other systems | 11 | [41] |
| 2026-10 | Option-channel attack: renaming the permissive option drove fail-open to 93–100% on four open-weight decision models used as agent guardrails (research) | Disclosed vulnerability | 2, 3, 4, 5, 6 | [15] |
| 2026-10 | Datadog: a counterfeit policy cut Jev's prompt-injection recall from 82.90% to 3.88% and moved LangChain's tool-risk gate from block to allow on an unauthorised edit | Disclosed vulnerability | 1, 2, 4 | [29] |
| 2026-10 | Cisco Talos: four malware families (84 samples, January 2025 to July 2026) carry text aimed at LLM triage; Check Point found a first sample in June 2025 | Attack on an AI system | 1 | [32][33] |
| 2026-10 | OpenAI: internal agents disabled monitoring alerts and removed a monitoring integration while doing requested work | Failure or accident | 12 | [44] |
| 2026-11 | LEVER: comments that add no fact flipped about a third of Jev's correct decisions; re-asking without the comments blocked them (research) | Disclosed vulnerability | 1 | [27] |
| 2026-11 | VisualJevBench: image manipulations, including spoofed visual evidence, reached up to 69.6% success against Jev's image input (research) | Disclosed vulnerability | 5, 11 | [28] |

Attacks on typed decision models are, so far, research and disclosed weaknesses; the incidents in
deployed systems concern neighbouring gates, and most used forged inputs rather than attacking a
model. Text that argues, redefines the task or poses as policy is the common thread
across decision models, LLM reviewers and LLM malware triage, and the defences reported to work
take the untrusted text out of the decision (re-asking without it, or a deterministic rule)
instead of trying to detect it. Guardrail classifiers show the same patterns (see the Guardrails
threat model); the record on decisions about people is in litigation, not advisories.

## How this repository's evaluations relate

`decision-model-benchmark` (T0, pure API, no judge) measures five threats in two lanes and builds a
per-threat scorecard with intervals and an ordering of models:

| Threat area | Known lane (published, pinned) | Custom lane (`dmb-seed`, 54 synthetic cases, five gate policies) |
|---|---|---|
| Injection (1) | none imported: DecisionRobust's data states no licence; JevAdvBench's is non-commercial | five fixed injection templates in the untrusted field, with benign twins |
| Attackable policy text (4) | none published | one misleading rename of the permissive label, with twins |
| Fail-open on clean cases (3) | `deepset-prompt-injections` [21], recast as a yes/no screen | clean seed cases; fail-open and fail-closed reported separately |
| Brittleness (5) | `jevbench-original` paraphrase pairs | padding, option order, paraphrase, three encodings, extra fields |
| Re-run variation (5, 7) | re-sends of known cases | re-sends of clean cases; the noise floor for every flip rate |

It also reports, outside the scorecard: calibration and whether flipped decisions are less confident
(threat 6), refusals and errors clean and under attack (threat 6), input tokens and cost (threat 9),
and validity flags when the reported model id moves, is never reported or looks like an alias
(threat 7). The `tool_gate` seed policy judges static tool-call records with attacker text in their
context, which covers the gate's judgement in threat 2 but not an agent in the loop. The five
injection templates are a command, an authority claim, a fake validation result, an unverified
opinion and a flawed argument; a counterfeit policy of the kind reported in [29] and optimised
fact-free comments [27] are not among them. `review-evidence` harvests vendors' published data
terms for threat 8.

**Why these, and what is left to design review.** The measured threats are the ones a fixed,
labelled test can answer comparably across models: does the model flip under cheap, public attacks,
and is it right on plain cases. A low flip rate is a floor, not resistance. Left to design review:
adaptive attacks that use the returned probabilities (the largest gap; a red-team method, per
release, on shortlisted models), the end-to-end agent gate, what the caller does with non-answers,
drift between runs, data terms, leakage, bias, images and other languages, forged evidence (threat
11; the adapter sends text and JSON only) and whether the gate can be routed around (threat 12, a
property of the deployment). For these, "no standardised benchmark exists" is the state to report.
Numbers compare models; the synthetic corpus does not predict a deployment's failure rate, and the
skill sets no threshold.

## Design-review questions

- Which conditions in each policy could be deterministic rules over typed fields instead of model
  judgements? Is the model's allow ever the only approval for a consequential action?
- Which state fields can an outside party write? Does the gate read content an agent read or
  justification an agent wrote? Is the state trimmed, size-capped and normalised before the call?
- Can text in the state look like policy (a counterfeit set of criteria), and would anything
  notice? Is a changed decision ever re-checked without the untrusted text?
- Who writes instructions, labels and criteria? Is any of it built from data or configuration?
- What happens on a refusal, an HTTP error, a timeout, or an option none of which fits? Is there an
  abstain option?
- How was the cut-off chosen, from which labelled cases, for which action? Is vendor `confidence`
  compared across vendors anywhere? Is the review queue's size monitored?
- Can requesters see probabilities or resubmit near-boundary inputs freely?
- Is a versioned model id pinned and checked per response? Who is told when the vendor ships a new
  version, and are labelled cases re-run? How many gates share one model or alias?
- Which signed terms govern retention, training use and region? Is each decision logged with state,
  distribution, model id and policy version, and who can read those logs?
- Does any decision concern people? If so, where is the human review and outcome monitoring?
- Does any state carry a document, image, screenshot, receipt or recording an outside party
  supplied? What establishes that it is genuine before the model judges what it says?
- Can the gated agent, or any credential it holds, write the policy, option lists, cut-off, error
  handling or decision logs? Is there any path to the gated systems that does not pass through the
  gate? Does an allow cover exactly the call judged, or can it be replayed?

## References

Read 2026-11-21 unless marked otherwise.

1. TypeSafe, "Model jaggedness". https://docs.typesafe.ai/model-jaggedness.md
2. TypeSafe, "Confidence". https://docs.typesafe.ai/confidence.md
3. TypeSafe, "Models" (aliases, context limits, price). https://docs.typesafe.ai/models.md
4. TypeSafe, "Companion Noul". https://docs.typesafe.ai/patterns/companion-noul.md
5. TypeSafe, "How to build with TypeSafe". https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md
6. TypeSafe, "Request rules and errors". https://docs.typesafe.ai/api/errors.md
7. TypeSafe, "Legal" (DPA, training, zero retention). https://docs.typesafe.ai/legal.md
8. Microsoft Learn, "Deploy and use Microsoft-Decision-1.1 in Microsoft Foundry" (updated 2026-11-17). https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision
9. OpenAI, "Decisions" guide. https://developers.openai.com/api/docs/guides/decisions
10. OpenAI, "Data controls in the OpenAI platform". https://developers.openai.com/api/docs/guides/your-data
11. Google AI Studio, "Decisions API". https://aistudio.google.com/docs/decisions-api
12. Google, Gemini Decisions API launch post, 11 Nov 2026. https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/
13. OpenRouter, "Decisions". https://openrouter.ai/docs/guides/features/decisions
14. Cloudflare, "Clef" decision models (Apache-2.0 open weights). https://blog.cloudflare.com/clef-decision-models
15. Azizi, Baghaei Potraghloo, Pedram, "One Word Opens the Gate: The Option-Channel Attack on Typed Decision Models as Agent Guardrails", arXiv 2610.12292 (8 Oct 2026). https://arxiv.org/abs/2610.12292
16. Hu et al., "JevAdvBench: A Benchmark and Black-Box Attacks for Reinforcement Learning for Calibrated Decisions Models", arXiv 2609.31142 v2. https://arxiv.org/abs/2609.31142
17. Wu, Lim, "Decision Hijacking: Prompt Injection Attacks on Jev's Typed Probabilistic Decisions", arXiv 2609.28613. https://arxiv.org/abs/2609.28613
18. Lan, Kaul, Pandurangan, Sanyal, "From Detection to Decision: Calibration and Deferral for Prompt-Injection Detection", arXiv 2610.20907. https://arxiv.org/abs/2610.20907
19. Lan et al., "DecisionRobust: Benchmarking Robustness for JEV Style Decision Models Across Text and Vision", arXiv 2610.19118. https://arxiv.org/abs/2610.19118
20. JevBench README (option-order result). https://github.com/fstandhartinger/jevbench
21. deepset/prompt-injections dataset (revision 4f61ecb, apache-2.0). https://huggingface.co/datasets/deepset/prompt-injections
22. NIST AI 100-2 E2025, "Adversarial Machine Learning: A Taxonomy and Terminology of Attacks and Mitigations", section 2.2.2. https://csrc.nist.gov/pubs/ai/100/2/e2025/final
23. MITRE ATLAS data release 2026.10 (released 2026-10-28), techniques and case studies as named above; AML.T0012 and AML.T0013 checked against the data file on 2026-11-24. https://github.com/mitre-atlas/atlas-data/blob/main/dist/v6/ATLAS-2026.10.yaml
24. Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv 2306.05685. https://arxiv.org/abs/2306.05685
25. Gu et al., "Auditing Prompt Caching in Language Model APIs", arXiv 2502.07776. https://arxiv.org/abs/2502.07776
26. OWASP, "Top 10 for LLM Applications 2026" (OWASP-GenAI-LLM-Top-10-2026-v1.0), read 2026-11-24. https://genai.owasp.org/top-10-for-llm-applications-2026/ and https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/
27. Wang, Chi, Jiang, "Same Facts, Different Decision: Fact-Invariant Manipulation and Provenance-Based Defense in Typed Decision Models" (LEVER, Provenance Gate), arXiv 2611.27016 (20 Nov 2026), read 2026-11-24. https://arxiv.org/abs/2611.27016
28. Zeng et al., "VisualJevBench: A Benchmark and Black-Box Attacks for Visual Typed Decision Models", arXiv 2611.25435 (19 Nov 2026), read 2026-11-24. https://arxiv.org/abs/2611.25435
29. Datadog Security Labs, "Jev as a judge: How counterfeit policy steers Jev", 15 Oct 2026, read 2026-11-24. https://securitylabs.datadoghq.com/articles/jev-as-a-judge-how-counterfeit-policy-steers-jev/
30. Lin, "Hidden Prompts in Manuscripts Exploit AI-Assisted Peer Review", arXiv 2507.06185, read 2026-11-24. https://arxiv.org/abs/2507.06185
31. Sahoo et al., "When Reject Turns into Accept: Quantifying the Vulnerability of LLM-Based Scientific Reviewers to Indirect Prompt Injection", arXiv 2512.10449, read 2026-11-24. https://arxiv.org/abs/2512.10449
32. Check Point Research, malware sample with a prompt injection aimed at AI analysis, 25 Jun 2025 (ATLAS AML.CS0043), read 2026-11-24. https://research.checkpoint.com/2025/ai-evasion-prompt-injection/
33. Cisco Talos, AI-analysis evasion in malware (FRUITSHELL, PLOTSAFE, HOLLOWCLAD, MANTLEMAZE), 8 Oct 2026, read 2026-11-24. https://blog.talosintelligence.com/ignore-all-instructions-and-read-this-blog-the-state-of-ai-analysis-evasion-in-malware/
34. Meta, "Taking action against nudify apps", 12 Jun 2025, read 2026-11-24. https://about.fb.com/news/2025/06/taking-action-against-nudify-apps/
35. Mobley v. Workday, Inc., No. 23-cv-00770-RFL (N.D. Cal.), order of 16 May 2025, Dkt. 128, read 2026-11-24. https://cases.justia.com/federal/district-courts/california/candce/3:2023cv00770/408645/128/0.pdf
36. AppZen, "Receipt fraud: The four types and how finance teams detect them" (vendor platform data), read 2026-11-24. https://www.appzen.com/learn/receipt-fraud-the-four-types-and-how-finance-teams-detect-them
37. Microsoft, "Microsoft Digital Defense Report 2025", 16 Oct 2025, read 2026-11-24. https://blogs.microsoft.com/on-the-issues/2025/10/16/mddr-2025/
38. Microsoft Threat Intelligence, Jasper Sleet: North Korean remote IT workers' evolving tactics, 30 Jun 2025, read 2026-11-24. https://www.microsoft.com/en-us/security/blog/2025/06/30/jasper-sleet-north-korean-remote-it-workers-evolving-tactics-to-infiltrate-organizations/
39. Google Threat Intelligence Group, AI Threat Tracker, 5 Nov 2025, read 2026-11-24. https://cloud.google.com/blog/topics/threat-intelligence/threat-actor-usage-of-ai-tools
40. OpenAI, "Disrupting malicious uses of AI" (February 2026 report) and criminal scam operation case study (31 Jul 2026), read 2026-11-24. https://openai.com/index/disrupting-malicious-ai-uses/ and https://openai.com/index/disrupting-malicious-uses-of-ai-criminal-scam-operation/
41. Anthropic, "Detecting and countering misuse of AI: September 2026", read 2026-11-24. https://www.anthropic.com/threat-intelligence-report-september-2026
42. Reality Defender, "Reality Defender Bypasses Sora 2 Security Measures", 3 Oct 2025, read 2026-11-24. https://www.realitydefender.com/insights/sora-2-identity-bypass
43. Palo Alto Networks Unit 42, North Korean synthetic identity creation for remote job interviews, Apr 2025, read 2026-11-24. https://unit42.paloaltonetworks.com/north-korean-synthetic-identity-creation/
44. OpenAI, "Suppressing misalignment monitoring alerts and disabling misalignment monitoring" (misalignment report, October 2026), read 2026-11-24. https://openai.com/safety-alignment/misalignment-reports/suppressing-misalignment-monitoring-alerts-and-disabling-misalignment-monitoring/
45. OpenAI, "GPT-Live System Card", 2026-07-08, change log of 2026-08-04, read 2026-11-24. https://deploymentsafety.openai.com/gpt-live
46. OWASP, "Top 10 for Agentic Applications for 2026" (December 2025), read 2026-11-24. https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
47. OWASP, "MCP Top 10" (beta, v0.1), read 2026-11-24. https://owasp.org/www-project-mcp-top-10/
