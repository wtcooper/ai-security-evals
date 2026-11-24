# Threat models

A short threat model for each asset class this repository evaluates. Each one is meant to be
read on its own: an executive summary of the core risks at the top, then where those risks
come from, the main threats in a little more detail, and how the evaluation skills here
relate to them.

| Asset class | Threat model | Related skills |
|---|---|---|
| General-purpose models (frontier API and open weights) | [general-purpose-model.md](general-purpose-model.md) | `model-benchmark` |
| Restricted-access cyber-capable models | [restricted-cyber-model.md](restricted-cyber-model.md) | none (see below) |
| Decision and classification models | [decision-model.md](decision-model.md) | `decision-model-benchmark` |
| Realtime voice models | [voice-model.md](voice-model.md) | `voice-model-benchmark` |
| Vision-input models | [vision-input-model.md](vision-input-model.md) | `vision-model-benchmark` |
| Image-generation models | [image-generation-model.md](image-generation-model.md) | `image-generation-benchmark` |
| AI coding agents | [coding-agent.md](coding-agent.md) | `agent-misuse-benchmark`, `coding-guidance-benchmark` |
| Agent features | [agent-features.md](agent-features.md) | `agent-feature-review` |
| LLM applications | [llm-application.md](llm-application.md) | `app-benchmark`, `app-redteam` |
| Guardrails and safety classifiers | [guardrail.md](guardrail.md) | `guardrail-benchmark` |
| AI-assisted security tools | [security-tooling.md](security-tooling.md) | `security-tool-benchmark` |

**Restricted-access cyber-capable models** are offered by some providers only to vetted
security teams, for offensive security work. They are not benchmarked here: access is limited
to a few named people, and the questions that matter are who has access, what the model is
pointed at, and where its output goes.

Two shared files sit beside them:

- [incidents.md](incidents.md) — a dated register of the AI security incidents from January 2025 to
  November 2026 that the threat models draw on: attacks on AI systems, AI used against other systems or
  people, failures and accidents, disclosed vulnerabilities and research results, each with its primary
  source.
- [frameworks.md](frameworks.md) — the framework ids the threat models use: the OWASP Top 10 for LLM
  Applications 2026 (with the crosswalk from the 2025 edition), the OWASP Top 10 for Agentic
  Applications, the OWASP MCP Top 10 (a beta) and MITRE ATLAS release 2026.10.

## How to read them

Most documents follow the same rough outline: executive summary, scope, system model and
threat actors, core threats, framework mapping, recent incidents, how the evaluations relate,
design-review questions, references.

Each threat says what the evidence for it is: *observed in deployed systems* (an incident),
*disclosed vulnerability* (a CVE or advisory with no known exploitation), *demonstrated in research*,
or *theoretical*. The framework mapping checks every item of each OWASP list that applies to the asset
class and says which threat covers it or why it does not apply.

Risk ratings (Low, Medium, High, Critical) are rough inherent ratings for the typical deployment each
document describes, from likelihood and impact, to show where attention belongs. *Critical* means
both are high in that deployment. The evidence status sits beside each rating, so a high rating
resting on research alone is visible as such.
They are not acceptance thresholds, and they change with deployment context; re-rate them for your own.

Where a document describes controls, it does so to explain what addresses a threat, not to
prescribe one. This repository ships no controls.

All documents were last reviewed on 2026-11-24.
