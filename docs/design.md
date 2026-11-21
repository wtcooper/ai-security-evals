# Design

Why the repository is shaped the way it is. For what exists, see the [README](../README.md);
for the rules every skill meets, see [skill-standard.md](skill-standard.md).

## 1. The problem

A security team is asked whether an AI capability can be enabled: a new model, the same
model inside a different agent harness, a voice or image model, a new endpoint type such as
a decision API, a new agent feature such as computer use or persistent memory. The answer is
usually wanted within days.

A benchmark score does not answer that question. A review does, and a review is scoping,
gathering what vendors already publish, modelling the threats, testing what can be tested,
applying the organisation's own criteria, and recording the result. This repository is a
toolkit for that whole path, as agent skills an agent runs on the reviewer's behalf.

## 2. Principles

| Principle | What it means here |
|---|---|
| **The repository measures; the organisation decides** | No acceptance threshold, pass mark or gate ships, in code, config, templates or prose. `review-criteria` walks an organisation through writing its own. |
| **Evaluations only** | A skill measures how well a control works and never ships one: no rule files, guidance skills, hooks, guardrails or scanners. Controls and tools under test come from the user, through small adapters. |
| **A review is a pipeline** | Scope → evidence → threat model → test → criteria → report. Benchmarks are one stage. |
| **Results are "subject in context"** | Every measurement records the surface, harness, system prompt, tools and safeguards it ran under. The same model can behave differently in a different harness. |
| **Harvest before compute** | Vendor cards, published scores and documented limits are evidence with provenance. Measure what they leave open. |
| **Standard benchmarks first, gaps stated** | One catalogue maps threats to benchmarks. "No standardized benchmark exists" is a reportable state, not a silence. |
| **Fits in a day** | Every measurement skill shows its cost before running and has `smoke` / `standard` / `full` depths. |
| **Safe by default** | Pure API or in-memory by default; sandboxed work has no network; suites that elicit working exploits are out of scope. |
| **Every comparison is one axis** | Hold everything fixed and vary one arm: the model, the harness, the control, the tool, or the modality. Every arm sees the same seeded samples. |
| **Names say what a skill is for** | `<subject>-<method>`. |

### Validity flags are not thresholds

A threshold says whether a *result* is acceptable; the repository has none. A validity flag
says whether a *measurement* can be trusted: the judge could not grade a share of samples,
an agent rarely completed its task so its "security" score mostly reflects doing nothing, a
scanner gives different verdicts on identical runs. Flags have configurable limits, are
listed before any number in a report, and never hide a number.

## 3. Structure

### 3.1 Packaging

- Each plugin conforms to **Agent Plugins 1.0.0**: a root `plugin.json` with the required
  `$schema` and `name`, and skills as immediate children of `skills/`.
- That specification defines no marketplace format, so marketplace manifests are
  client-specific and **generated** from one source file (`marketplace.source.json`) by
  `scripts/gen_manifests.py`. The Claude Code marketplace file is generated today; Codex and
  Copilot CLI read the same file. Supporting another client is one more generator function.
- Client-specific plugin manifests are generated from the root `plugin.json`, so names and
  versions cannot drift. CI checks that generated files are current.
- The specification rejects any path that resolves outside a plugin, and installers copy
  only the plugin directory. Shared code is therefore **vendored** into each skill from
  `tools/lib/` by `tools/sync_skills.sh`, and CI fails on drift.
- `SKILL.md` frontmatter uses the Agent Skills standard fields only, so a skill loads in any
  client.

### 3.2 Naming

`<subject>-<method>`. The subject is what a requester would call the thing. The method is one
of:

| Method | Meaning |
|---|---|
| `benchmark` | A fixed, labelled test set; a repeatable score comparable across runs |
| `redteam` | Adaptive attacks that react to the target's replies |
| `review` | A guided assessment where no standard test exists |

Review-pipeline stages are `review-<stage>`.

### 3.3 Shared contracts

| File | Written by | Contents |
|---|---|---|
| `review.json` | `review-scope` | Subject, deployment context, data sensitivity, autonomy, who controls each input, time budget |
| `evidence.jsonl` | `review-evidence`, guided reviews | One row per claim: threats it bears on, source, date, provenance (`published` / `harvested` / `self_run` / `reviewed`); absences are rows too |
| `manifest.json` | `new_experiment.sh` | What ran: tool, model, benchmark, arms, scorers, cost, and the deployment `context` |
| `samples.jsonl` | measurement skills | One row per arm × target × sample, including rows with nothing to report, so denominators are honest |
| `findings.jsonl` | detection-style skills | One row per finding |
| `summary.md` / `summary.json` | measurement skills | Rates with intervals, paired differences against a named baseline arm, validity flags first |
| `criteria.json` | the organisation, via `review-criteria` | Its own acceptance criteria. An empty template ships; values never do |

Machine-readable files are JSON so skills need only the Python standard library.

### 3.4 Benchmark catalogue and execution tiers

`catalog/benchmarks.json` lists, per benchmark: the skill that runs it, engine, threats
covered, calls per sample, judge and sandbox needs, licence, and whether each fact was
verified. `review-threat-model` uses it to sort each threat into: covered by a standard
benchmark, needs a custom probe, design review only, or uncovered.

Execution tiers: **T0** pure API · **T1** in-memory, or a container with no network ·
**T2** a supervised sandbox with live targets, never the default.

### 3.5 Control types and what stays out

Each skill knows which kind of control it measures and reports efficacy in that control's
terms.

| Control type | Evaluated by | Efficacy measure |
|---|---|---|
| Guardrail or content filter (API or model) | `guardrail-benchmark` | Catch rate against false-block rate; risk removed inside a benchmark against over-blocking |
| Guidance in front of a coding agent (skill, rule, hook, MCP server, any mix) | `coding-guidance-benchmark` | Change in correct-and-secure rate against no guidance |
| Model, provider and harness safeguards | `model-benchmark`, `agent-misuse-benchmark` | Refusal on restricted tasks beside completion on legitimate ones |
| Application defences (system prompt, filters) | `app-benchmark`, `app-redteam` | Change in attack success rate |
| Decision model used as a gate | `decision-model-benchmark` | Fail-open and fail-closed rates; decision flips under attack |
| Security tools (code scanners, scanners of skills / MCP servers / model files, pentest tools) | `security-tool-benchmark` | Recall and precision against known answers |

Deliberately out of scope:

- **Shipping or authoring a control.** No rule files, guidance content, hooks or guardrails.
- **Scanning a user's own code, skills or MCP servers.** That is operating a scanner. This
  repository evaluates scanners; it does not replace one.
- **Deciding.** Reports leave decision, conditions and sign-off blank.
- **Exploit-development benchmarks.** Suites that ask a model to produce working exploits
  need an environment powerful enough to be dangerous, and answer a capability question
  rather than a resistance one.

Not affected by "evaluations only": stripping credentials before a run, sandboxes with no
network, and pre-run network checks. These protect the evaluation itself.

## 4. The review pipeline

| Stage | Skill | Output |
|---|---|---|
| Scope | `review-scope` | `review.json` |
| Evidence | `review-evidence` | `evidence.jsonl`; what is absent is recorded as a finding |
| Threat model | `review-threat-model` | Threats for this subject type and a test plan naming which skills to run, at what depth |
| Test | the measurement skills | Experiment folders |
| Criteria | `review-criteria` | The organisation's own `criteria.json` |
| Report | `review-report` | Evidence, results, uncovered threats; the organisation's criteria beside results only if supplied |

`review-criteria` never proposes a value. For each measured dimension it explains what the
number means, how wide its interval is at the depth run, and what each kind of error costs in
this deployment, and it offers the organisation's own earlier results as reference points. It
records who set each criterion and whether that was before or after the results were seen.

## 5. Design notes on individual skills

- **One Inspect runner, any arm axis.** `model-benchmark` varies the model;
  `guardrail-benchmark`'s in-line mode varies the guardrail in front of one model. Both use
  the same suite, runner and report.
- **Metric direction is read from scorer source, not from the metric's name.** Several
  upstream metrics named `accuracy` are attack-success rates where lower is better. Every run
  cross-checks that per-sample outcomes add up to the headline metric and withholds the
  paired comparison when they do not.
- **A judge is never the model under test**, is always routed explicitly, and provider
  credentials are stripped before a run so an unrouted judge fails instead of calling a
  provider nobody chose.
- **A tool that failed to run is not a tool that found nothing.** `security-tool-benchmark`
  logs every run and excludes a tool on the targets where it failed.
- **`coding-guidance-benchmark` treats an arm as an opaque folder.** It never inspects or
  interprets the guidance; only a placebo arm ships. Tasks and scoring come from BaxBench.
- **`voice-model-benchmark` varies the modality.** The same prompts go in as text and as
  locally synthesised speech, with seeded audio perturbations.
- **`agent-misuse-benchmark` is a scaffold.** The scenario format, the sweep, the statistics
  and the report ship; the scenarios, the harness module and the outcome scorer are supplied
  by whoever completes it, because what an agent must decline is each organisation's own
  policy. Its build guide says how.

## 6. Reference frameworks

Used as vocabularies for threat ids and context, not as the process: OWASP Top 10 for LLM
Applications and for Agentic Applications, MITRE ATLAS, the AWS Agentic AI Security Scoping
Matrix (autonomy), Microsoft's taxonomy of agentic failure modes, CSA's AI controls
questionnaire, NIST AI RMF with its Generative AI Profile. Ids appear in templates only where
they were verified against the primary source.

## 7. Known gaps

- No skill has been run against a real model, vendor API or guardrail by the maintainers of
  the current versions; each `SKILL.md` lists exactly what was not verified.
- `agent-misuse-benchmark` needs completing before it measures anything.
- Only one marketplace manifest format is generated.
- No fairness benchmark, policy-extraction test or encoding-specific study was found for
  decision models; `decision-model-benchmark` says what it does not measure.
- Image generation has no published security benchmark; `image-generation-benchmark` relies on
  its own core set and the C2PA reference verifier, and says so. Several voice threats are
  likewise measured only by that skill's core set.
