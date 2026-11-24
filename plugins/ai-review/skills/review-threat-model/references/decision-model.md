# Threat template — Decision model

A model that takes a state and typed questions with a closed answer set and returns answers with probabilities, used to route, gate, grade or screen.

Which threats a catalogued benchmark covers depends on the catalogue at the time the plan is built; `scripts/plan.py` decides that. The last column says how a threat is assessed when no available benchmark covers it. A `—` in a framework column means no id was verified for that threat, not that none exists. The verified ids and where they were checked are in [framework-ids.md](framework-ids.md).

## Questions to ask for this subject type

- What does the decision gate, and what happens on each answer?
- Who writes the question instructions and option criteria, and is any of that text built from data?
- Who controls the content being judged?
- Is there an abstain option, and what does the caller do on refusal or error?
- Is a confidence threshold used, and what happens below it?
- Which wire format: one undifferentiated state, or separate roles?

Core benchmark for this subject type: `decision-model-benchmark`. Run it first. Its references/threat-model.md says where the risks come from for this subject type and lists the core threats it measures in two lanes (published benchmarks and its own core set); its scorecard compares models threat by threat. The threats below are the wider review list, including those no benchmark measures.

## Threats

| Threat id | Threat | Why it matters here | OWASP LLM 2026 | OWASP Agentic 2026 | MITRE ATLAS | With no benchmark available |
|---|---|---|---|---|---|---|
| `decision-error-asymmetry` | **Fail-open and fail-closed errors hidden in one number.** A single accuracy figure hides which way the model fails. Allowing what should be blocked and blocking what should be allowed cost different things. | Start here: decide which error is which before reading any number. | — | — | — | custom probe: Score labelled cases from the deployment's own policy and report fail-open and fail-closed rates separately. |
| `decision-state-injection` | **Injection through the judged content.** Text inside the content being judged changes the decision. Unverified opinions and flawed arguments work about as well as explicit commands. | The judged content is usually attacker-controlled and arrives as one blob. | LLM01:2026 | — | AML.T0051.001 | custom probe: Add injected text to labelled cases the model gets right and count flips, beside the flip rate of identical re-runs. |
| `decision-option-channel` | **Policy override through option labels or criteria.** Option labels and criteria are part of the prompt. If any of that text is attacker-influenced or templated from data, the gate fails open. | Labels and criteria are prompt. | — | — | — | custom probe: Edit one label or criterion at a time on labelled cases and count flips toward the permissive option. |
| `decision-perturbation-flip` | **Decision flips under benign-looking changes.** Irrelevant context, paraphrase or option order changes the answer. | First-option bias and wording sensitivity are documented by vendors. | — | — | AML.T0015, AML.T0043 | custom probe: Reorder options, paraphrase and pad labelled cases; report consistency. |
| `decision-confidence-manipulation` | **Confidence pushed across a review threshold.** Input shifts the reported confidence so that a wrong answer stays confident or a right answer is sent to human review. | Decides whether 'escalate when unsure' works. | — | — | — | custom probe: Record the full distribution for clean and attacked cases and compare the confidence of flipped decisions. |
| `decision-probability-oracle` | **Returned probabilities guide an attack.** The probabilities in the response give an attacker a signal to optimise against without any model access. | Every response returns a signal. | — | — | AML.T0043.001 | custom probe: An adaptive attack using returned probabilities as feedback; costly, for shortlisted models only. |
| `decision-forced-choice` | **Forced choice and refusal handling.** The model always answers unless an abstain option exists; a refusal or error treated as allow is an evasion path. | A model that must answer will. | — | — | — | custom probe: Send cases with no correct option, and cases that provoke refusal or error, and record what the calling code does with each. |
| `decision-confused-deputy` | **Gate reads content controlled by the party it judges.** A decision model used as an agent gate reads tool output or content written by the attacker whose action it is approving. | When the model approves an agent's tool calls. | LLM01:2026 | — | AML.T0051.001 | custom probe: Place the model as tool-call approver in front of a fixed agent and report utility and attack success together. |
| `decision-no-rationale` | **No rationale to audit.** The model returns no explanation, so a decision can be audited only from the logged input and the full returned distribution. | Audit rests on logging. | — | — | — | design review: Review what is logged for each decision and for how long. |
| `obfuscated-input` | **Attack carried by encoding, language or modality.** An attack that plain-English safeguards catch gets through when it is encoded, obfuscated, written in another language or moved to another modality. | Encoding, language and image overlays. | — | — | AML.T0068 | custom probe: Re-send a sample of refused requests in the encodings, languages and modalities the deployment accepts. |
| `version-drift` | **The thing reviewed is not the thing running later.** An alias moves to a new model, the harness updates itself, or outputs are not reproducible, so results stop describing the deployment. | No seed; aliases move. | — | — | — | design review: Record the pinned identifiers, how updates arrive, and who is told. |
| `unbounded-consumption` | **Unbounded cost or resource use.** Requests, loops or tool calls drive cost or load without a cap. | Input-token billing with very large contexts and many questions per request. | LLM06:2026 | — | AML.T0034, AML.T0029 | design review: Review rate limits, spend caps, context and step limits as configured. |
| `policy-leakage` | **Policy or data inferred through probabilities.** The policy text or properties of the judged data are inferred by probing. | Limited to probing through probabilities. | — | — | — | uncovered: No published study or benchmark was found. |
| `bias` | **Decisions differ by protected attribute.** Decisions about people change with attributes that should not matter. | When decisions concern people. | — | — | — | uncovered: No fairness benchmark for decision models was found. |
| `data-retention-hosting` | **Retention, training use and hosting of submitted data.** Prompts, outputs, files or audio are kept, used for training, or processed in a place or by a party the organisation has not accepted. | The judged content is often the sensitive part. | — | — | — | design review: Read the contract and the vendor's data terms; record what was signed, not what the public page says. |
| `supply-chain-model` | **Tampered or unsafe model artefact.** Downloaded weights or model files carry malicious code or were replaced on the way: unsafe serialisation formats, a look-alike repository, a changed revision. | Open-weight decision models only. | LLM04:2026 | — | AML.T0010.003, AML.T0011.000, AML.T0018.002 | design review: For open weights, harvest the published scan verdicts with review-evidence and record the pinned revision. For closed weights only vendor statements exist. |

## What the template does not cover

The list is a starting point for this subject type. Threats that come from the particular deployment (its data, its users, its integrations) are added by the reviewer. The template names no controls.

---
Generated by `scripts/render_templates.py` from `threats.json` and `templates.json`. Edit the JSON, then re-run the script.
