# ai-security-evals

Security evaluations for AI capabilities — models, agents, applications and the defences
around them — packaged as **agent skills** an agent runs on your behalf.

A security team is asked whether an AI capability can be enabled: a new frontier model, a
model inside a coding harness, a voice or image model, a decision API, a new agent feature.
This repo is the toolkit for answering with evidence. It **measures and records**. It does
not decide, and it ships no acceptance thresholds: each organisation sets its own.

- **A review is a pipeline:** scope → evidence → threat model → test → your criteria → report.
- **Results are "subject in context":** every result records the surface, harness, system
  prompt, tools and safeguards it ran under.
- **Standard benchmarks first,** with the gaps stated. One catalogue maps threats to
  benchmarks; "no standardized benchmark exists" is a reportable state.
- **Evaluations only:** a skill measures a control and never ships one. Guardrails, guidance
  and scanners under test come from you, through small adapters.
- **Fast and cheap by default:** every measurement skill shows its cost before running and
  has `smoke` / `standard` / `full` depths. Exploit-development suites are out of scope.

---

## Plugins and skills

Five plugins following [Agent Plugins 1.0.0](https://agent-plugins.org/specification).
Skill names are `<subject>-<method>`: `benchmark` (a fixed labelled test set), `redteam`
(adaptive attacks), `review` (a guided assessment where no standard test exists).

| Plugin | Skill | What it does |
|---|---|---|
| [`ai-review`](plugins/ai-review/) | `review-scope` | Interview the requester; write `review.json` (subject and deployment context) |
| | `review-evidence` | Harvest vendor cards, published scores, documented limits — each with provenance; includes the open-weights scan harvest |
| | `review-threat-model` | Threats for this subject type and a test plan sorted by the benchmark catalogue |
| | `review-criteria` | Walk the organisation through writing **its own** acceptance criteria; never proposes a value |
| | `review-report` | Compile evidence, results (validity flags first), uncovered threats; decision fields left blank |
| [`model-evals`](plugins/model-evals/) | `model-benchmark` | A fixed suite of Inspect benchmarks, one per risk dimension, on the same seeded samples for every model |
| | `vision-model-benchmark` | Models that read images: instructions hidden in images, secret extraction, tool hijack, harmful requests written as images, over-refusal; CyberSecEval 3 and FigStep plus a rendered core set |
| | `decision-model-benchmark` | Decision / classification endpoints: fail-open and fail-closed rates, decision flips under attack against the re-run noise floor |
| | `voice-model-benchmark` | Realtime voice models: spoken harmful requests, audio distortions, a second voice giving instructions, talking the agent into a tool call, secret leakage, over-refusal; AdvBench and XSTest spoken plus a 48-case core set |
| | `image-generation-benchmark` | Image generation: phishing assets, forged documents, working QR payloads, likeness, justification bypass and provenance, on a small core set plus the C2PA reference verifier |
| [`agent-evals`](plugins/agent-evals/) | `agent-misuse-benchmark` | **Scaffold.** Does a model inside an agent harness carry out tasks your policy says it must decline? Ships the scenario format, arm sweep, statistics and report; you supply the scenarios, harness module and outcome scorer |
| | `agent-feature-review` | Guided review of an agent feature: computer use, memory, connectors/MCP, code execution, file search, multi-agent, background agents |
| [`app-evals`](plugins/app-evals/) | `app-benchmark` | A bundled labelled corpus against your app's endpoint: recall, false-block rate, by technique |
| | `app-redteam` | Adaptive multi-turn attacks against your app, with repeats |
| [`defense-evals`](plugins/defense-evals/) | `guardrail-benchmark` | How good is this guardrail: direct (its own verdict on a labelled corpus) and in-line (risk removed vs over-blocking inside benchmarks) |
| | `coding-guidance-benchmark` | A/B test of anything placed in front of a coding agent (skill, rule, hook, MCP server), scored on BaxBench |
| | `security-tool-benchmark` | Compare security tools on targets with known answers: code scanners, scanners of skills / MCP servers / model files, pentest tools |

The design rationale is in [`docs/design.md`](docs/design.md).

### Which skill for which question

| You are asked… | Start with |
|---|---|
| "Can we enable this new model?" | `review-scope` → `model-benchmark` (+ `review-evidence` for open weights) |
| "Can we enable this voice / realtime model?" | `voice-model-benchmark` |
| "Can we use this decision API as a gate?" | `decision-model-benchmark` |
| "Can we let this model read images, screenshots or documents?" | `vision-model-benchmark` |
| "Can we enable this image-generation model?" | `image-generation-benchmark` |
| "Can we turn on computer use / memory / this connector?" | `agent-feature-review` |
| "Will this model do things we do not want inside this coding agent?" | `agent-misuse-benchmark` (a scaffold: bring your own scenarios) |
| "Is our chatbot safe to ship?" | `app-benchmark`, then `app-redteam` |
| "Does this guardrail work, and what does it cost us?" | `guardrail-benchmark` |
| "Do our secure-coding skills or rules change what the agent writes?" | `coding-guidance-benchmark` |
| "Which scanner should we trust for skills and MCP servers?" | `security-tool-benchmark` (`extension` kind) |
| "What do I hand leadership?" | `review-report` |

---

## Install

**Claude Code:**
```
/plugin marketplace add wtcooper/ai-security-evals
/plugin install model-evals@ai-security-evals        # or ai-review, agent-evals, app-evals, defense-evals
```
**Any Agent Plugins client:** load a `plugins/<plugin>/` directory.
**Any agent that reads skills:** copy a `plugins/<plugin>/skills/<skill>/` folder; every
skill is self-contained.

Then ask the agent to run the skill. It drives **Plan → Run → Analyze** and asks for what it
needs. Every step is also runnable by hand from the skill's `SKILL.md`.

## Try it without any API key

Every measurement skill documents a keyless smoke test under a `Smoke test` heading in its
`SKILL.md`. For example:
```bash
uv sync --extra dev
# compare two "tools" on a bundled tree with three known vulnerabilities
bash plugins/defense-evals/skills/security-tool-benchmark/tests/smoke.sh
# the whole review pipeline on bundled example inputs
bash plugins/ai-review/skills/review-report/tests/smoke.sh
```
For real model behaviour with no key or spend, [`targets/proxy/`](targets/proxy/) is a
local LiteLLM gateway that fronts mock models, local Ollama models or any provider behind
one OpenAI-compatible endpoint; see [`targets/`](targets/README.md).

---

## How results are kept

Every run opens `.evals/<skill>/<label>_<date>/` (gitignored) with `manifest.json` (what
ran, and the deployment `context`), the engine's native output, `samples.jsonl`, and
`summary.md` / `summary.json`. Rates carry 95% intervals; arms are compared paired, on the
same seeded samples, against a named baseline.

**Validity flags are not thresholds.** A flag says a *measurement* may not be trustworthy
(the judge could not grade, the agent never completed its task, a scanner disagrees with
itself). Flags have configurable limits, are listed before any number, and never hide one.

The rules every skill meets are in [`docs/skill-standard.md`](docs/skill-standard.md).

---

## Repository layout

```
ai-security-evals/
├── marketplace.source.json         # marketplace name, owner, plugin list (hand-edited)
├── .claude-plugin/marketplace.json # GENERATED by scripts/gen_manifests.py
├── plugins/<plugin>/               # Agent Plugins 1.0.0 packages
│   ├── plugin.json · README.md
│   └── skills/<skill>/             #   SKILL.md + scripts, vendored lib/, tests/, references/
├── catalog/benchmarks.json         # benchmark catalogue: threats covered, engine, tier, cost
├── targets/                        # things to point skills at: local gateway, vulnerable apps
├── tools/                          # MAINTAINER ONLY: shared library, corpus builder, tests
│   ├── lib/                        #   source of truth for code vendored into skills
│   └── sync_skills.sh              #   vendors it (CI checks there is no drift)
├── scripts/                        # manifest generator, conformance and standard checks, run_tests.sh
├── e2e/                            # real-model end-to-end tests for four of the skills
└── docs/                           # skill standard, reference, tutorials, plans, research
```
More: [corpus, red-team objectives, block handling and experiment folders](docs/reference.md) ·
[promptfoo tutorial](docs/promptfoo-tutorial/) · [Inspect tutorial](docs/inspect-ai-tutorial/).

## Tests

```bash
bash scripts/run_tests.sh     # Node + Python unit tests, keyless smoke scripts, vendoring drift,
                              # Agent Plugins conformance, the skill standard, self-containment
bash e2e/run_e2e.sh all       # real-model end-to-end for four of the skills (needs a provider key)
```

## What has and has not been verified

Every skill's unit tests and keyless smoke test pass. `agent-misuse-benchmark` is a scaffold
and measures nothing until its scenarios, harness module and scorer are supplied. No skill
was run against a real model, vendor API or guardrail in the environment where the current
versions were built, and each
`SKILL.md` ends with a `Not verified` list saying exactly what was not exercised. Treat a
first real run of any skill as part of its verification.

## License

MIT. Bundled corpora carry their own licences; see [`docs/reference.md`](docs/reference.md)
and each skill's corpus notes.
