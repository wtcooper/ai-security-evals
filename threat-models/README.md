# Threat models

One formal threat model per asset class this repository evaluates. Each says what the asset
is, where its risk comes from, which threats matter most and why, and how the evaluation
skills here measure those threats — or why a threat is left to design review.

Read a threat model before running its skills. The evaluations exist to test the threats a
threat model names; a result only means something against the threat it was chosen for.

| Asset class | Threat model | Evaluated by |
|---|---|---|
| General-purpose models (frontier API and open weights) | [general-purpose-model.md](general-purpose-model.md) | `model-benchmark` |
| Restricted-access cyber-capable models | [restricted-cyber-model.md](restricted-cyber-model.md) | none by design (see below) |
| Decision and classification models | [decision-model.md](decision-model.md) | `decision-model-benchmark` |
| Realtime voice models | [voice-model.md](voice-model.md) | `voice-model-benchmark` |
| Vision-input models | [vision-input-model.md](vision-input-model.md) | `vision-model-benchmark` |
| Image-generation models | [image-generation-model.md](image-generation-model.md) | `image-generation-benchmark` |
| AI coding agents | [coding-agent.md](coding-agent.md) | `agent-misuse-benchmark`, `coding-guidance-benchmark` |
| Agent features | [agent-features.md](agent-features.md) | `agent-feature-review` |
| LLM applications | [llm-application.md](llm-application.md) | `app-benchmark`, `app-redteam` |
| Guardrails and safety classifiers | [guardrail.md](guardrail.md) | `guardrail-benchmark` |
| AI-assisted security tools | [security-tooling.md](security-tooling.md) | `security-tool-benchmark` |

**Restricted-access cyber-capable models** are models a provider gives only to vetted
security teams, with safeguards tuned for offensive security work. They are not put through
a pre-enable benchmark here: access is limited to a few named people, and the questions that
matter are about who has access, what the model is pointed at, and where its output goes. The
threat model covers those.

## Where the documents live

This folder holds the canonical copies. `tools/sync_skills.sh` copies each one into the
`references/threat-model.md` of every skill that evaluates that asset class, so a skill
carries its threat model with it when installed on its own, and copies all of them into
`review-threat-model`. Edit the copy here, never a skill's copy; CI fails if they drift.

## Method

Every threat model has the same sections, in this order:

1. **Executive summary** — what the asset is, its core risks, where risk concentrates, and
   what the evaluations can and cannot tell you.
2. **Scope and assumptions** — the reference deployment the ratings assume, its variants, and
   what is in and out of scope.
3. **System model** — components, a data-flow diagram with trust boundaries, entry points,
   assets to protect, and threat actors.
4. **Threats** — a summary table, then each threat in detail: description, attack path,
   preconditions, impact, what raises or lowers likelihood, published evidence, framework
   mapping, controls that address it, and how it is evaluated.
5. **Evaluation coverage** — each threat against the skill, lane and benchmark that measures
   it, what a result does and does not show, and the threats no benchmark measures.
6. **Design review checklist** — questions a benchmark cannot answer.
7. **Residual risk and open questions**.
8. **References** — primary sources, with the date each was read.

**Categories.** Each threat carries a STRIDE category (Spoofing, Tampering, Repudiation,
Information disclosure, Denial of service, Elevation of privilege) or **Abuse** where the harm
is the asset doing what an attacker asks rather than a property being violated.

**Framework ids.** OWASP Top 10 for LLM Applications 2025, OWASP Top 10 for Agentic
Applications 2026 and MITRE ATLAS ids appear only where they were checked against the
primary source. `—` means no verified match, not that the framework has nothing relevant.

**Risk ratings.** Likelihood and impact are each rated Low, Medium or High for the reference
deployment in section 2, and combined as below. These are inherent risks — before the
organisation's own controls — and they move with deployment context: each threat says which
factors raise or lower it. They are a way to order attention. They are not acceptance
thresholds, and an organisation should re-rate them for its own deployment.

| Likelihood \ Impact | Low | Medium | High |
|---|---|---|---|
| **High** | Medium | High | Critical |
| **Medium** | Low | Medium | High |
| **Low** | Low | Low | Medium |

**Controls.** Threat models describe the kinds of control that address a threat, so a
reviewer knows what to look for and what `defense-evals` can measure. They do not prescribe
a control, and this repository ships none.
