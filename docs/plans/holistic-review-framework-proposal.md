# Proposal — refocus `ai-security-evals` as a holistic AI security review toolkit

_Status: revision 6 · 2026-11-14 · **Phase 0 is implemented** (plugin layout, manifests, standard frontmatter, the `app-benchmark` and `model-benchmark` renames); everything else is still a proposal_

Changes in revision 6: this repo only evaluates scanners; scanning a skill or MCP server
lives in `ai-security-sdlc`, so `agent-extension-scan` is out (§3.5).
Changes in revision 4: this repo evaluates controls and never implements them (§2, §3.5);
the code-generation skill becomes a plain A/B test of any guidance placed in front of an
agent, scored on BaxBench (§5.3). Revision 3 added the
naming rule and merges; revision 2 added Agent Plugins manifests, the no-thresholds rule,
the guided review stages and the skill audit.

## 1. The problem this repo should solve

Leadership asks for a thumbs-up or thumbs-down on enabling an AI capability, usually within
days: new frontier models, the same model inside different coding harnesses, voice and image
models, new endpoint types (decision APIs, realtime), new features (computer use, memory,
connectors).

Today the repo is nine measurement skills organised by **what is under test**. That
taxonomy stays. Three things are missing:

1. **Everything around the benchmark** — scoping, vendor evidence, threat modelling, the
   organisation's own acceptance criteria, and a report. Only testing exists.
2. **Deployment context as a first-class input.** Results depend on the surface and harness,
   not only the model. Nothing records where a result applies.
3. **Subjects that are not a chat endpoint** — voice, image, decision models.

## 2. Design principles

| Principle | What it means in the repo |
|---|---|
| **This repo measures; the organisation decides** | No acceptance threshold, pass mark or gate ships here, in code, config, templates or docs. The review plugin walks an organisation through writing its own criteria. |
| **Evaluations only** | The repo measures how well a control works. It ships no control: no rule files, guidance skills, hooks, guardrails or scanners of its own. Controls under test are supplied by the user (§3.5). |
| A review is a pipeline | Scope → evidence → threat model → test → criteria → report. Benchmarks are one stage. |
| Names say what a skill is for | `<subject>-<method>`, from a fixed vocabulary (§3.2). |
| Results are "subject in context" | Every measurement carries the surface, harness, system prompt, tools and safeguards it ran under. |
| Harvest before compute | Vendor cards, published scores and documented limits are evidence with provenance; measure only what they leave open. |
| Standard benchmarks first, gaps stated | One catalogue maps threats to benchmarks. "No standardized benchmark exists" is a reportable state. |
| Fits in a day | Every skill prints its cost plan before running; depths are `smoke` / `standard` / `full`. |
| Safe by default | Pure-API or in-memory by default; sandboxed work has no egress; exploit-development suites are an opt-in supervised tier. |
| Every comparison is one axis | Hold everything fixed and vary one arm: the control, the model, the harness, or the modality. One statistics library throughout. |

**Validity flags are not thresholds, and this needs your confirmation.** Three existing
checks tell a reader whether a *measurement* can be trusted, not whether a *result* is
acceptable: judge returned no usable verdict (`model-bench`), agent utility too low for a
security score to mean anything (`model-bench`), scanner run-to-run agreement
(`tool-assetscan`, `control-codegen`). I recommend keeping them as clearly labelled,
configurable validity flags that never hide the number. The existing wording that gives
gating advice ("κ<0.6 ⇒ unusable for CI gating") would be removed.

## 3. Structure

### 3.1 Plugin and marketplace manifests

- **Each plugin conforms to Agent Plugins 1.0.0** (the published version; 1.1.0 is a working
  draft that adds hooks and is not relied on). Root `plugin.json` with the required
  `$schema` and `name`; skills as immediate children of `skills/`; `mcp.json` only if a
  plugin ships an MCP server (none planned).
- **The spec defines no marketplace format**, so marketplace manifests are client-specific.
  One source file generates each: `.claude-plugin/marketplace.json` (read by Claude Code,
  Codex and Copilot CLI), `.agents/plugins/marketplace.json` (Codex),
  `.github/plugin/marketplace.json` (Copilot). Adding a client is a generator change.
- **Client-specific plugin manifests are generated too** (`.claude-plugin/plugin.json`
  today), from the root `plugin.json`, so name and version cannot drift. CI checks
  generated files are current and runs each client's validator where one exists.
- **Containment.** The spec rejects any path resolving outside the plugin root, and
  installers copy only the plugin directory. The repo's existing rule — vendor shared code
  into each skill, check drift in CI — already satisfies this and is kept.
- **Skill frontmatter moves to the Agent Skills standard fields only** (`name`,
  `description`, `license`, `compatibility`, `metadata`, `allowed-tools`). Every current
  skill uses Claude-only fields (`disable-model-invocation`, `user-invocable`,
  `argument-hint`) and a non-standard `dependencies` list. Consequence: skills can be
  model-invoked; this is acceptable because each begins with a plan stage that asks before
  running anything.

### 3.2 Naming rule and layout

Every skill is named **`<subject>-<method>`**. The subject is the thing a requester would
name; the method is one of four words:

| Method | Meaning |
|---|---|
| `benchmark` | A fixed, labelled test set; a repeatable score you can compare across runs |
| `redteam` | Adaptive attacks that react to the target's replies |
| `scan` | Inspect a file or package for malicious or unsafe content |
| `review` | A guided assessment where no standard test exists |

Where one subject has two benchmarks, a qualifier sits in the middle
(`decision-model-benchmark`, `voice-model-benchmark`).

```
ai-security-evals/
├── marketplace.source.json                # single source → generated client marketplace files
├── .claude-plugin/                        (generated; other clients' files added as verified)
├── plugins/
│   ├── ai-review/      review-scope · review-evidence · review-threat-model ·
│   │                   review-criteria · review-report                           (new)
│   ├── model-evals/    model-benchmark · decision-model-benchmark (new) ·
│   │                   voice-model-benchmark (new) · image-model-review (new)
│   ├── agent-evals/    agent-misuse-benchmark (new) · agent-feature-review (new)
│   ├── app-evals/      app-benchmark · app-redteam
│   └── defense-evals/  guardrail-benchmark · coding-guidance-benchmark ·
│                       security-tool-benchmark
│       each plugin:  plugin.json · README.md · skills/<skill>/{SKILL.md, scripts, references, lib (vendored)}
├── tools/              # maintainer-only source of truth vendored into skills (unchanged)
├── catalog/            # benchmark catalogue + threat coverage map                 (new)
├── targets/  evaluations/  e2e/  docs/  scripts/
```

Five plugins, fifteen skills: five review stages and ten measurement skills, of which six
are the existing nine after merging.

### 3.3 Shared contracts

The repo already has a good results contract; it is only used by four of nine skills. The
proposal is to make it universal rather than invent another.

| File | Status | Contents |
|---|---|---|
| `manifest.json` (v2) | exists; adopt everywhere | What ran: tool, model, benchmark, arms, k, scorers, cost. **Add a `context` block** (surface, harness + version, system prompt, tools, safeguards on/off) |
| `samples.jsonl` | exists; adopt everywhere | One row per arm × target × sample, including zero-finding rows, so denominators are honest |
| `findings.jsonl` | exists; keep for detection-style skills | One row per finding |
| `summary.md` / `summary.json` | exists; adopt everywhere | Rates with intervals, paired deltas against a named baseline arm |
| `review.yaml` | new | Subject, deployment context, data sensitivity, autonomy scope, who controls each input, time budget |
| `evidence.jsonl` | new | One row per claim: threat id, source, provenance (`published` / `harvested` / `self_run` / `reviewed`), pointer to the summary it came from |
| `criteria.yaml` | new, **organisation-owned** | The organisation's own acceptance criteria. The repo ships an empty template and the walkthrough; never values |

### 3.4 Benchmark catalogue

One file per benchmark: engine, verified metric keys, calls per sample, judge and sandbox
needs, licence, threats covered, execution tier (**T0** pure API · **T1** in-memory or
no-egress container · **T2** supervised sandbox, off by default). `model-benchmark`'s `suite.py` is
the seed. `review-threat-model` reads it to sort each threat into: covered by a standard
benchmark, needs a custom probe, design review only, or uncovered.

### 3.5 Control types the repo understands, and what stays out

Each skill knows which kind of control it measures and reports efficacy in that control's
terms. The control itself always comes from the user.

| Control type | Evaluated by | Efficacy measure |
|---|---|---|
| Guardrail or content filter (API or model) | `guardrail-benchmark` | Catch rate against false-block rate; risk removed inside a benchmark |
| Guidance in front of a coding agent (skill, rule, hook, MCP server, any mix) | `coding-guidance-benchmark` | Change in correct-and-secure rate against no guidance |
| Model, provider and harness safeguards | `model-benchmark`, `agent-misuse-benchmark` (safeguards on/off arm) | Refusal on malicious tasks beside completion on legitimate ones |
| App-level defences (system prompt, filters) | `app-benchmark`, `app-redteam` (two-arm runs) | Change in attack success rate |
| Decision model used as a gate | `decision-model-benchmark` | Fail-open and fail-closed rates; flip rate under attack |
| Security tools (code scanners, extension scanners, pentest tools) | `security-tool-benchmark` | Recall and precision against known answers |

What this rules out or moves:

- **Removed from the code-generation skill:** the script that installs CodeGuard, the script
  that authors a Secure Build Plan, and the hand-written rule files. All three produce or
  ship a control.
- **Withdrawn from the last revision:** a reference CodeGuard arm and a nudge-rule template.
- **Out of scope:** scanning a skill, plugin or MCP server. That lives in
  `ai-security-sdlc`. This repo keeps only the evaluation of those scanners: the
  *extension* kind of `security-tool-benchmark`, with adapters for Tencent AI-Infra-Guard,
  Cisco skill-scanner and mcp-scanner, and NVIDIA SkillSpector to start.
- **Moved:** `weights_scan.py` reads scan verdicts Hugging Face already publishes. That is
  evidence harvesting, so it moves from `model-benchmark` to `review-evidence`.
- **Relabelled:** the LiteLLM gateway under `targets/` bundles a mock content filter. It is
  a test fixture for exercising the skills, not something to deploy.
- **Review skills** record which controls were in place and which were evaluated. They do
  not prescribe or generate controls.
- **Not affected:** credential stripping, the no-egress sandbox and the pre-run egress
  check. These protect the evaluation run itself.

## 4. The `ai-review` plugin — the guided review

| Stage | Skill | Output |
|---|---|---|
| 1. Scope | `review-scope` | `review.yaml`: what is being enabled, where, with what data and permissions |
| 2. Evidence | `review-evidence` | Vendor cards, published scores, documented limits, data handling — each with source and date; what is absent is recorded as a finding |
| 3. Threat model | `review-threat-model` | Threats for this subject type, mapped to OWASP and MITRE ATLAS ids, and a **test plan** naming which measurement skills to run, at what depth |
| 4. Test | — | Run the measurement skills the plan names. There is no `review-test` skill: it would only call the others |
| 5. Criteria | `review-criteria` | The organisation writes its own `criteria.yaml` |
| 6. Report | `review-report` | Evidence, results with intervals, uncovered threats, and — only if the organisation supplied criteria — its criteria beside the results. Decision and sign-off fields are left for people to fill |

How `review-criteria` works without setting anything itself:

- For each measured dimension it shows what the number means, its interval width at the
  depth run, and what each kind of error costs in this deployment.
- It offers **the organisation's own reference points**: results for models and controls it
  already runs, measured with the same seed. It never offers a suggested value.
- It records who set each criterion and whether it was set before or after the results for
  the subject were seen, since criteria chosen afterwards are weaker evidence.
- A CI check keeps the shipped template free of values.

`ai-security-governance` keeps its own gate; nothing is ported from it.

## 5. Audit of the existing skills

### 5.1 What each existing skill does, and what it becomes

| Today | What it actually does | Becomes |
|---|---|---|
| `app-eval` | Sends a fixed set of attack and benign prompts to your app's endpoint and scores how many it handles correctly | `app-benchmark` |
| `app-redteam` | Runs multi-turn attacks against your app that adapt to its replies | `app-redteam` (unchanged) |
| `control-isolate` | Sends labelled harmful and benign prompts **straight to a guardrail API**, no model involved, and scores catch rate against false-block rate | `guardrail-benchmark`, *direct* mode |
| `control-bench` | Runs a standard model benchmark twice, guardrail off and on, and reports how much risk the guardrail removed and what it cost in over-blocking | `guardrail-benchmark`, *in-line* mode |
| `model-bench` | Runs a fixed security benchmark suite against one or more models | `model-benchmark` (gains a vision-input profile; the weights scan moves to `review-evidence`) |
| `control-codegen` | Has a coding agent build an app from a spec, with and without security rule files, then scans and attacks the result to see whether the rules made the code safer | `coding-guidance-benchmark` |
| `tool-codescan` | Compares **code scanners** (CodeQL, Semgrep, an LLM reviewer) on source code with known vulnerabilities | `security-tool-benchmark`, *code* kind |
| `tool-assetscan` | Compares **scanners of AI components** (skills, MCP servers, model files) on labelled malicious and benign samples | `security-tool-benchmark`, *extension* kind |
| `tool-pentest` | Compares **pentest tools** (an AI pentest agent, Nuclei, ZAP) against running vulnerable apps, counting only exploits an oracle confirms | `security-tool-benchmark`, *pentest* kind |

**Why these merges.**

- **The two guardrail skills** answer one question, "how good is this guardrail", by two
  routes. One skill, with the mode chosen in its plan step; only the engine that mode needs
  is installed. Guardrail *models* and decision models used as guardrails run in direct mode.
- **The three tool skills** are one design applied to three kinds of input: the arms are
  the tools, the targets have known answers, each tool is driven by a small adapter that
  emits SARIF, and one statistics library scores them. They differ only in what the tool
  inspects. One skill with a `--kind`, and the per-kind detail in `references/`.
- **Vision input** is not a separate skill: its benchmarks run through the same engine as
  `model-benchmark`, so it is a profile there.
- **Not merged:** `app-benchmark` and `app-redteam` (different methods, already clear);
  the model skills for decision, voice and image (different APIs and engines).

Nothing is dropped. `security-tool-benchmark` matters to a review only when the capability
under review is itself an AI security tool, or when you need to know how far to trust a
scanner the review relies on; it gets no new investment beyond the merge.

### 5.2 Defects in today's `control-bench` (verified by reading the runbook)

- **Unrouted judge.** It tells the user to run `inspect_evals/cyse4_mitre` with no judge
  arguments. That task's judge and expansion model default to a hardcoded OpenAI model, so
  the run either bills a provider silently or fails. `model-benchmark` already solves this.
- **No intervals and no paired comparison** between arms; analysis is a printed dict.
- **First-N sampling** through `--limit`, on datasets sorted by category.

Fix: `guardrail-benchmark`'s in-line mode becomes the injection shim plus the shared runner
with a `--arms` axis. One runner then serves both skills: `model-benchmark` varies the
model, `guardrail-benchmark` varies the guardrail. The runbook also lists a `runners/` directory that does not exist.

### 5.3 `coding-guidance-benchmark` — today's `control-codegen`, simplified

A plain A/B test: does anything placed in front of a coding agent change the security of
the code it writes?

- **An arm is an opaque folder** copied into the agent's workspace or configuration before
  it starts. It may hold a skill, a rules file, a hook, an MCP server configuration, or any
  mix. The benchmark does not inspect or interpret it. A one-line label states the control
  type so the report can name it.
- **Baseline arm:** nothing in place. **Placebo arm** (the only arm the repo ships): a
  folder of irrelevant content, used for the keyless smoke test and to show the noise floor.
- **Tasks and scoring come from BaxBench:** 392 backend-building tasks with functional tests
  and expert exploits. The metric is "correct and secure", with no judge model. Every arm
  builds the same seeded subset of tasks, and the cost is shown before a run.
- **Reported:** correct-and-secure rate per arm with intervals, the paired difference from
  baseline, and the extra tokens and time the guidance cost.
- **Optional diagnostic:** whether the agent touched the arm at all (read a file from the
  folder, loaded a skill, called an MCP tool), read generically from the transcript. This
  separates "the guidance did not help" from "the guidance was never used".
- **Removed:** the six custom specs and their probes, the GitHub ephemeral-repo and CodeQL
  path, the three-run LLM review, and everything listed in §3.5. This deletes existing work.
- **Engine:** shared with `agent-misuse-benchmark`, which adds Codex, Gemini CLI and
  opencode. Builds need package registries, so this skill allows those hosts only or uses
  pre-built images.

### 5.4 Standard every skill must meet, and where each stands

Skills are listed by today's names.

| Requirement | Meets it today |
|---|---|
| Standard frontmatter only | none |
| Shared contract (manifest v2, `samples.jsonl`, `summary.md`) | `control-codegen`, `tool-*` |
| Rates with intervals; paired comparison to a baseline arm | `control-codegen`, `tool-*`; `model-bench` has intervals only |
| Cost plan printed before running | `model-bench` |
| Judge independence enforced, unusable judge reported | `control-codegen`, `model-bench`; `app-eval` in prose only |
| Provider keys stripped; no keys in a sandbox | `model-bench` |
| Depth names `smoke` / `standard` / `full` | none (three naming schemes in use) |
| Context block recorded | none |
| No dependency on `ai-security-sdlc` | `app-*`, `control-isolate`, `control-bench`, `model-bench` |
| No acceptance thresholds or gating advice | all but the two with κ wording |
| Keyless smoke test | `model-bench`; promptfoo skills via the mock gateway |

The three generations of output format are the real inconsistency: promptfoo skills write
`results.json` + `summary.txt`; `control-bench` writes Inspect logs and a printed dict; the
later skills write the full contract. Converging on the last is most of the standardising
work.

### 5.5 Repo-level cleanup

- `CONTRIBUTING.md` references a skill and a directory that no longer exist.
- `e2e/` covers four skills of nine.
- `find_sdlc.sh` sits in the shared library vendored into four skills; move it into the
  optional sdlc adapters.
- The two sdlc plan documents under `docs/plans/` describe a finished project; archive them.

## 6. New measurement skills

### 6.1 `agent-misuse-benchmark` — a model inside agent harnesses

- **Why:** Anthropic's Opus 5.5 system card reports bare-API and claude.ai results
  separately and calls model refusals "only a secondary protection". Gray Swan's CRF
  benchmark (arXiv 2606.02644) saw one model refuse 100% of tasks against localhost and 0%
  against production sites. Counter-evidence exists (IssueTrojanBench), so it must be
  measured per case.
- **Engine:** `inspect-swe` 0.3.0 runs `claude_code`, `codex_cli`, `gemini_cli`, `opencode`
  as the solver; model traffic is proxied back to Inspect so keys never enter the sandbox.
  Harness version is pinned and logged.
- **Sweep:** model × harness × safeguards on/off over the same scenarios.
- **Scenarios:** a malicious set and a matched dual-use/benign set of equal size, with
  target framing as an explicit factor. Report refusal rate and benign completion together.
  Your internal Inspect suite is the natural scenario pack if it can be released.
- **Safety:** three 2026 incidents had eval agents reaching the live internet. Controls:
  no egress at two layers, pre-baked images, an automated pre-run egress check, explicit
  scope in the prompt, provider classifiers left on unless deliberately tested off.

### 6.2 `decision-model-benchmark`

A thin adapter across the three wire formats; fail-open and fail-closed rates on labelled
cases; flip rate under attack against the re-run noise floor; option-order and paraphrase
consistency; DecisionRobust and JevBench. Detail in
`docs/research/decision-models-security-eval.md`.

### 6.3 `voice-model-benchmark`

- The audio channel is measurably weaker than text (JALMBench; arXiv 2510.20223).
- Inspect cannot drive realtime models; promptfoo's `openai:realtime` provider and PyRIT's
  `RealtimeTarget` can. Synthesise speech locally, since promptfoo's `audio` strategy sends
  prompts to its remote service.
- Standard runs: text-to-speech parity, perturbation delta, a sample of
  Jailbreak-AudioBench-Plus or JALMBench.
- No benchmark exists for background-speech injection in your call flow, tool abuse by
  voice, the transcript-versus-audio guardrail gap, barge-in, SIP spoofing or cost caps.

### 6.4 Vision profile, `image-model-review`, `agent-feature-review`

- **Vision input (a `model-benchmark` profile):** `cyse3_visual_prompt_injection` and
  promptfoo's `vlguard` / `vlsu` run today; computer-use injection suites need VMs (T2).
- **`image-model-review`:** no standardized benchmark exists for the security concerns of
  image generation; a review with provenance checks and a small hand-built probe set.
- **`agent-feature-review`:** one threat-and-test template per feature (computer use,
  memory, connectors/MCP, code execution, multi-agent, background agents).

## 7. Phasing

| Phase | Work |
|---|---|
| 0 — done | Skills moved into `plugins/`; root `plugin.json` per plugin; manifest generator and CI validation; standard frontmatter; `app-eval` and `model-bench` renamed. Skills that will be merged keep their old names until Phase 1. Only the Claude marketplace file is generated so far: it is the one Claude Code, Codex and Copilot CLI all read, and the other clients' own formats were not verified. `allowed-tools` was dropped from every skill rather than converted, so no shell access is pre-approved. |
| 1 | Merge and standardise the existing skills (§5.1, §5.4): the two guardrail skills into `guardrail-benchmark`, the three tool skills into `security-tool-benchmark`, shared Inspect runner, shared contract with context block, depth names, intervals, remove gating wording. |
| 2 | `ai-review` plugin and the benchmark catalogue. |
| 3 | `voice-model-benchmark` and `decision-model-benchmark` (both have reviews pending). |
| 4 | `agent-misuse-benchmark` with a new public scenario set, then `coding-guidance-benchmark` rebuilt on its engine. |
| 5 | Vision profile, `image-model-review`, `agent-feature-review`. |

The GPT Realtime 2.1 review can be run by hand from §6.3 before Phase 3 lands.

## 8. Settled, and still open

Settled: plugin standard and generated manifests; no thresholds; naming and merges; a new
public scenario set for `agent-misuse-benchmark`; BaxBench for `coding-guidance-benchmark`.

Open:

1. **Validity flags (§2):** proceeding with labelled, configurable flags that never hide
   the number, unless you say otherwise.
2. **§3.5 changes:** moving the weights scan to `review-evidence`, and deleting the custom
   code-generation specs.

## 9. Evidence caveats

Research was three single-pass web surveys plus the Agent Plugins 1.0.0 spec read directly.
Not verified: runtime behaviour of an Agent Plugins package in each client (only Claude
Code's validator was exercised, by a research agent); the tail of the 1.1.0 draft; dataset
licences for JALMBench, AJailBench and SACRED-Bench; whether a GPT-Realtime-2.x system card
exists. `ai-security-sdlc` was not readable in this session. The skill audit is from the
runbooks and file layout; the promptfoo, codegen and tool skills were not executed.
