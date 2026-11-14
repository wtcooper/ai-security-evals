# Proposal — refocus `ai-security-evals` as a holistic AI security review toolkit

_Status: revision 2, for review before any build · 2026-11-14 · nothing here is implemented_

Changes in this revision: plugins conform to the Agent Plugins spec with generated client
manifests (§3); **no thresholds or gates ship in this repo** (§2, §4); the review process is
six guided stages including "set your own criteria" (§4); a full audit of the existing skills
with a recommendation for each (§5); `ai-security-sdlc` is treated as a separate project.

## 1. The problem this repo should solve

Leadership asks for a thumbs-up or thumbs-down on enabling an AI capability, usually within
days: new frontier models, the same model inside different coding harnesses, voice and image
models, new endpoint types (decision APIs, realtime), new features (computer use, memory,
connectors).

Today the repo is nine measurement harnesses organised by **what is under test**. That
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
| A review is a pipeline | Scope → evidence → threat model → test → criteria → report. Benchmarks are one stage. |
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

### 3.2 Layout

```
ai-security-evals/
├── marketplace.yaml                       # single source → generated client marketplace files
├── .claude-plugin/  .agents/plugins/  .github/plugin/      (generated)
├── plugins/
│   ├── ai-review/        review-scope · review-evidence · review-threat-model ·
│   │                     review-test · review-criteria · review-report            (new)
│   ├── model-evals/      model-bench · harness-bench (new) · decision-bench (new)
│   ├── modality-evals/   voice-bench · vision-bench · imagegen-review             (new)
│   ├── feature-evals/    feature-review · asset-scan                              (new)
│   ├── app-evals/        app-bench (was app-eval) · app-redteam
│   ├── control-evals/    control-isolate · control-bench · control-codegen
│   └── tool-evals/       tool-codescan · tool-assetscan · tool-pentest
│       each plugin:  plugin.json · README.md · skills/<skill>/{SKILL.md, scripts, lib (vendored)}
├── shared/               # source of truth vendored into skills (today's maintainer `lib`)
├── catalog/              # benchmark catalogue + threat coverage map                (new)
├── targets/  evaluations/  e2e/  docs/  scripts/
```

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
no-egress container · **T2** supervised sandbox, off by default). `model-bench/suite.py` is
the seed. `review-threat-model` reads it to sort each threat into: covered by a standard
benchmark, needs a custom probe, design review only, or uncovered.

## 4. The `ai-review` plugin — six guided stages

| Stage | Skill | Output |
|---|---|---|
| 1. Scope | `review-scope` | `review.yaml`: what is being enabled, where, with what data and permissions |
| 2. Evidence | `review-evidence` | Vendor cards, published scores, documented limits, data handling — each with source and date; what is absent is recorded as a finding |
| 3. Threat model | `review-threat-model` | Threats for this subject type, mapped to OWASP and MITRE ATLAS ids, and a test plan sorted by the catalogue |
| 4. Test | `review-test` | Runs the planned measurement skills inside the time budget; collects their summaries |
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

### 5.1 Verdict per skill

| Skill | Still relevant? | Recommendation |
|---|---|---|
| `app-eval` | Yes | **Keep, rename `app-bench`** (every other benchmark skill is `-bench`). Add intervals. Its corpus becomes the shared source that `voice-bench` speaks aloud. |
| `app-redteam` | Yes | **Keep.** Build repeated trials in; today the runbook only advises them. Profile the target once and share it with `app-bench`. |
| `control-isolate` | Yes | **Keep.** It is the home for guardrail *models* too. Share metric definitions with `decision-bench` (a decision model used as a guardrail is the same shape). |
| `control-bench` | Yes | **Re-platform on the shared Inspect runner** that `model-bench` uses. As written it has three defects, below. |
| `model-bench` | Yes | **Keep.** Move `weights_scan.py` out to `asset-scan`; adopt the shared contract and depth names. |
| `control-codegen` | Yes, but it is the heaviest skill | **Keep as a `full`-depth skill and refactor**, below. |
| `tool-assetscan` | Yes — reviews rely on these scanners | **Keep.** Fix a reference to `hf_harvest.py`, which does not exist. |
| `tool-codescan` | Marginal | **Keep, no new investment.** Relevant only when the capability under review is an AI code reviewer. |
| `tool-pentest` | Marginal | **Keep, no new investment.** Relevant only when the capability under review is an AI pentest agent. |

Nothing is dropped. Two engines are merged; no skills are.

### 5.2 `control-bench` defects (verified by reading the runbook)

- **Unrouted judge.** It tells the user to run `inspect_evals/cyse4_mitre` with no judge
  arguments. That task's judge and expansion model default to a hardcoded OpenAI model, so
  the run either bills a provider silently or fails. `model-bench` already solves this.
- **No intervals and no paired comparison** between arms; analysis is a printed dict.
- **First-N sampling** through `--limit`, on datasets sorted by category.

Fix: `control-bench` becomes the injection shim plus the shared runner with a `--arms`
axis. One runner then serves both skills: `model-bench` varies the model, `control-bench`
varies the guardrail. The runbook also lists a `runners/` directory that does not exist.

### 5.3 `control-codegen` refactor

- **Overstated coverage.** The description says it bundles five scored specs. Six specs
  exist; only spec-01 has probes and acceptance tests. Either finish them or describe what
  is there.
- **Standard benchmark first.** BaxBench (392 scenarios with functional tests and exploits)
  already has an adapter in the skill. Make it the primary path and the custom specs
  secondary.
- **Coupled to `ai-security-sdlc`.** Two of its four arms and one scorer call sdlc skills.
  Make an arm "any pre-build diff" with CodeGuard and the Secure Build Plan as optional
  adapters.
- **One harness, public GitHub repos, real cost.** It drives Claude Code only, needs
  ephemeral public repos for CodeQL, and budgets $15 per build at k=10 per arm. Moving it
  onto the `harness-bench` engine (§6.1) gives it Codex, Gemini CLI and opencode, a
  no-egress sandbox, and a local CodeQL path. Do this with `harness-bench`, not before.
- Its baseline arm alone answers "how secure is the code this agent writes", which is a
  model × harness measurement. That becomes a `harness-bench` scenario family.

### 5.4 Standard every skill must meet, and where each stands

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

### 6.1 `harness-bench` — a model inside agent harnesses

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

### 6.2 `decision-bench`

A thin adapter across the three wire formats; fail-open and fail-closed rates on labelled
cases; flip rate under attack against the re-run noise floor; option-order and paraphrase
consistency; DecisionRobust and JevBench. Detail in
`docs/research/decision-models-security-eval.md`.

### 6.3 `voice-bench`

- The audio channel is measurably weaker than text (JALMBench; arXiv 2510.20223).
- Inspect cannot drive realtime models; promptfoo's `openai:realtime` provider and PyRIT's
  `RealtimeTarget` can. Synthesise speech locally, since promptfoo's `audio` strategy sends
  prompts to its remote service.
- Standard runs: text-to-speech parity, perturbation delta, a sample of
  Jailbreak-AudioBench-Plus or JALMBench.
- No benchmark exists for background-speech injection in your call flow, tool abuse by
  voice, the transcript-versus-audio guardrail gap, barge-in, SIP spoofing or cost caps.

### 6.4 `vision-bench`, `imagegen-review`, `feature-review`, `asset-scan`

- **Vision input:** `cyse3_visual_prompt_injection` and promptfoo's `vlguard` / `vlsu`
  run today; computer-use injection suites need VMs (T2).
- **Image generation:** no standardized benchmark for the security concerns; a review with
  provenance checks and a small hand-built probe set.
- **`feature-review`:** one threat-and-test template per feature (computer use, memory,
  connectors/MCP, code execution, multi-agent, background agents).
- **`asset-scan`:** scan a submitted MCP server, skill, plugin or weights repo. Takes
  `weights_scan.py` from `model-bench`; `tool-assetscan` remains the skill that tells you
  how far to trust those scanners.

## 7. Phasing

| Phase | Work |
|---|---|
| 0 | Move skills into `plugins/`; root `plugin.json` per plugin; manifest generator and CI validation; standard frontmatter; rename `app-eval`; repo cleanup (§5.5). No behaviour change. |
| 1 | Standardise the existing skills (§5.4): shared contract with context block, shared Inspect runner under `model-bench` and `control-bench`, depth names, intervals, remove gating wording. |
| 2 | `ai-review` plugin and the benchmark catalogue. |
| 3 | `voice-bench` and `decision-bench` (both have reviews pending). |
| 4 | `harness-bench`, then the `control-codegen` refactor on its engine. |
| 5 | `vision-bench`, `imagegen-review`, `feature-review`, `asset-scan`. |

The GPT Realtime 2.1 review can be run by hand from §6.3 before Phase 3 lands.

## 8. Open points for your review

1. **Validity flags (§2):** keep them as labelled, configurable flags, or remove default
   cut-offs entirely?
2. **`tool-codescan` and `tool-pentest`:** keep as an optional plugin with no further
   investment (recommended), or move them out of this repo?
3. **`control-codegen`:** finish the five unscored specs, or cut to spec-01 plus BaxBench
   (recommended)?
4. **Internal harness suite:** can it be released as the `harness-bench` scenario pack?
5. **Rename `app-eval` → `app-bench`:** acceptable, given it changes the install name?

## 9. Evidence caveats

Research was three single-pass web surveys plus the Agent Plugins 1.0.0 spec read directly.
Not verified: runtime behaviour of an Agent Plugins package in each client (only Claude
Code's validator was exercised, by a research agent); the tail of the 1.1.0 draft; dataset
licences for JALMBench, AJailBench and SACRED-Bench; whether a GPT-Realtime-2.x system card
exists. `ai-security-sdlc` was not readable in this session. The skill audit is from the
runbooks and file layout; the promptfoo, codegen and tool skills were not executed.
