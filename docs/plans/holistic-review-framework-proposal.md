# Proposal — refocus `ai-security-evals` as a holistic AI security review toolkit

_Status: proposal for decision · 2026-11-14 · nothing in this document has been implemented_

## 1. The problem this repo should solve

Leadership asks for a thumbs-up or thumbs-down on enabling an AI capability, usually within
days. The requests are no longer just "is this app safe": they are new frontier models, the
same model inside different coding harnesses, voice and image models, new endpoint types
(decision APIs, realtime), and new features (computer use, memory, connectors).

Today the repo is eight measurement harnesses organised by **what is under test** (`app-*`,
`control-*`, `tool-*`, `model-*`). That taxonomy is sound and should stay. Three things are
missing:

1. **Everything around the benchmark.** A review is scoping, harvesting vendor evidence,
   threat modelling, targeted testing, and a recorded decision. Only the testing exists.
   Research found no open-source end-to-end intake toolkit or system-card harvester, so this
   is a real gap, not a duplicate.
2. **Deployment context as a first-class input.** Results depend on the surface and harness,
   not only the model (evidence in §4). Nothing in the repo records where a result applies.
3. **Subjects that are not a chat endpoint.** Voice, image, and decision models need adapters
   and their own threat models; several have no standardized benchmark at all.

## 2. Design principles

| Principle | What it means in the repo |
|---|---|
| A review is a pipeline, not a benchmark | Scope → harvest → threat-model → measure → decide. Benchmarks are one stage. |
| Results are always "subject in context" | Every measurement carries the surface, harness, system prompt, tools, and safeguards it ran under. |
| Harvest before compute | Vendor system cards, published scores and documented limitations are evidence with provenance; only measure what they leave open. |
| Standard benchmarks first, gaps stated | One catalogue maps threats to benchmarks. "No standardized benchmark exists" is an explicit, reportable state. |
| The organisation sets the bar | Skills measure. A versioned policy file holds thresholds; the verdict is computed from it, never by a model. |
| Fits in a day | Every skill prints its cost plan before running and offers smoke / standard / deep depths. |
| Safe by default | Pure-API or in-memory by default; sandboxed work has no egress; exploit-development suites are an opt-in supervised tier. |
| Every comparison is one axis | Hold everything fixed and vary one thing: the control (`control-bench`), the model (`model-bench`), the harness, or the modality. Same statistics throughout. |

## 3. Proposed structure

### 3.1 Which "plugin standard"

There are two things this could mean, and one repo can satisfy both:

- **Agent Plugins 1.0.0** (agent-plugins.org, announced 2026-08-06): vendor-neutral, root
  `plugin.json` + `skills/` + `mcp.json`. Clients listed include VS Code, Cursor, GitHub
  Copilot, ChatGPT/Codex. It defines **no marketplace format**, and Claude Code is not a
  listed client.
- **Claude Code's plugin marketplace** (`.claude-plugin/marketplace.json`): the de-facto
  marketplace file; Codex and Copilot CLI also read it.

**Recommendation:** dual manifests per plugin (root `plugin.json` for Agent Plugins,
`.claude-plugin/plugin.json` for Claude Code) plus one `.claude-plugin/marketplace.json`.
A dual-manifest plugin was confirmed to pass `claude plugin validate --strict`; runtime
behaviour in other clients was not tested.

Two consequences for existing skills:

- Current `SKILL.md` files use Claude-only frontmatter (`disable-model-invocation`,
  `user-invocable`). Non-standard fields hard-fail upload to claude.ai and the Skills API,
  so move to standard fields (`name`, `description`, `license`, `compatibility`,
  `allowed-tools`) and keep Claude-specific behaviour in the Claude manifest.
- Installing a plugin copies only that plugin's directory, so `../shared` cannot work. The
  existing "vendor a copy, check drift in CI" approach is the right one and extends
  unchanged.

### 3.2 Layout

```
ai-security-evals/
├── .claude-plugin/marketplace.json
├── plugins/
│   ├── ai-review/          # the review pipeline (new)
│   │   └── skills/  review-scope · review-evidence · review-threat-model · review-decide
│   ├── model-evals/        # a model, reached through an API or a harness
│   │   └── skills/  model-bench · harness-bench (new) · decision-bench (new)
│   ├── modality-evals/     # non-text input or output (new)
│   │   └── skills/  voice-bench · vision-bench · imagegen-review
│   ├── feature-evals/      # a capability switched on for an existing model (new)
│   │   └── skills/  feature-review (computer use, memory, connectors/MCP, code execution,
│   │                multi-agent, background agents — one threat/test template each)
│   ├── app-evals/          # app-eval · app-redteam
│   ├── control-evals/      # control-isolate · control-bench · control-codegen
│   └── tool-evals/         # tool-codescan · tool-assetscan · tool-pentest
├── shared/                 # single source of truth, vendored into skills (today's `tools/lib`)
├── catalog/                # benchmark catalogue + threat coverage map (new)
├── targets/  evaluations/  e2e/  docs/
└── scripts/  .github/workflows/validate.yml
```

Each plugin carries `plugin.json`, `.claude-plugin/plugin.json`, a README with its install
line, and its skills. Existing skills move unchanged apart from frontmatter.

### 3.3 The contracts that make it one framework

These four files are the actual restructuring; the directory move is cosmetic by comparison.

| File | Written by | Contents |
|---|---|---|
| `review.yaml` | `review-scope` | Subject (model, endpoint, feature, app); **deployment context** — surface, harness and version, system prompt, tools and permissions, safeguards on/off, data sensitivity, autonomy scope, who controls each input; time budget |
| `evidence.jsonl` | every skill | One row per claim or measurement: threat id, value and interval, context tags, status, and **provenance** (`published` / `harvested` / `self_run` / `reviewed`) with source |
| `policy.yaml` | the organisation | Thresholds per check and risk tier, which checks are mandatory, maximum judge-unresolved rate. Versioned; the hash is recorded in the decision |
| `decision.md` | `review-decide` | Verdict (approve / approve with conditions / restrict / reject), the conditions as compensating controls, residual risk, uncovered threats, re-review triggers |

`review-decide` ports the deterministic gate from `ai-security-governance`. The governance
web app can remain an optional front end and system of record that consumes
`evidence.jsonl`; the toolkit should not depend on it.

### 3.4 The benchmark catalogue

One file listing, per benchmark: engine, verified metric keys, cost per sample, whether it
needs a judge or a sandbox, licence, and which threats it covers. `model-bench/suite.py` is
the seed. `review-threat-model` reads it to turn a threat list into a test plan with three
buckets: covered by a standard benchmark, needs a custom probe, not testable (design review
only). Execution tiers: **T0** pure API · **T1** in-memory or no-egress container ·
**T2** supervised sandbox, off by default.

## 4. New measurement skills

### 4.1 `harness-bench` — a model inside agent harnesses

Evidence that the harness matters (single research pass, primary sources read):

- Anthropic's Opus 5.5 system card reports results separately for the bare API and
  claude.ai, and states that model refusals are "only a secondary protection" behind the
  blocking classifier.
- Gray Swan's CRF benchmark (arXiv 2606.02644): one model refused 100% of tasks against
  localhost and 0% against production sites. Target framing alone moved the result.
- Counter-evidence exists: IssueTrojanBench finds refusals come mostly from the model. The
  honest position is that it must be measured per case.

Design:

- **Engine:** `inspect-swe` 0.3.0 runs `claude_code`, `codex_cli`, `gemini_cli`, `opencode`
  and others as the solver; the sandbox agent bridge proxies model traffic back to Inspect,
  so API keys never enter the sandbox. Pin the harness version; it is logged per sample.
- **Sweep:** model × harness × safeguards on/off, same scenarios.
- **Scenarios:** a malicious set and a matched dual-use/benign set of equal size (the shape
  of Anthropic's 61+61 Claude Code evaluation), with target framing as an explicit factor.
  Report refusal rate **and** benign completion rate together.
- **Your existing internal Inspect suite is this skill's scenario pack**, if it can be
  released; otherwise the skill ships the harness and a small public pack.
- **Safety:** three 2026 incidents (OpenAI/Hugging Face, Anthropic, UK AISI) involved eval
  agents reaching the live internet. Controls they converge on: no egress enforced at two
  layers, pre-baked images instead of package proxies, an automated pre-run egress check,
  explicit scope in the prompt, provider classifiers left on unless deliberately tested off.

### 4.2 `decision-bench` — decision / classification endpoints

Covered in `docs/research/decision-models-security-eval.md`. A thin adapter across the three
wire formats, then: fail-open and fail-closed rates on labelled cases, flip rate under attack
against the re-run noise floor, option-order and paraphrase consistency, and the existing
DecisionRobust / JevBench suites.

### 4.3 `voice-bench` — realtime and speech models

- **The audio channel is measurably weaker than text.** JALMBench: plain harmful queries
  succeed more often as audio (21.5%) than as text (17.0%). "Beyond Text" (arXiv 2510.20223):
  models near 0% in text exceeded 75% under echo, pitch and speed changes.
- **Inspect cannot drive realtime models** (issue #2698 open). promptfoo has an
  `openai:realtime` provider; PyRIT has a `RealtimeTarget` and audio converters.
  promptfoo's `audio` strategy sends prompts to its remote service, so synthesise locally.
- **Standard runs:** text-to-speech parity (the existing text corpus spoken, compared with
  the same prompts as text), then a perturbation delta, then a sample of
  Jailbreak-AudioBench-Plus (CC-BY-4.0) or JALMBench.
- **No benchmark exists for:** background-speech injection in your own call flow, tool and
  MCP abuse by voice, the gap between transcript-based guardrails and audio already spoken,
  barge-in, SIP header spoofing, cost caps. These are custom probes plus design review.

### 4.4 `vision-bench` and `imagegen-review`

- **Vision input:** `cyse3_visual_prompt_injection` (inspect_evals) and promptfoo's
  `vlguard` / `vlsu` plugins run today. Computer-use injection suites (OS-Harm, RedTeamCUA)
  need VMs and belong to T2.
- **Image generation:** no standardized benchmark for the security concerns (phishing and
  brand assets, identity documents, QR payloads, watermark robustness). This is a review, not
  a benchmark: harvest the vendor card, verify provenance metadata survives
  crop/re-encode, and run a small hand-built probe set.

## 5. The non-benchmark review (worked example: decision models)

What `ai-review` would walk a reviewer through, in order:

1. **Scope.** What decision, what happens on each outcome, which error is expensive
   (fail-open vs fail-closed), and whether the model is the sole gate.
2. **Harvest.** Vendor-documented limits (first-option bias, wording sensitivity, injection
   susceptibility are all admitted in vendor docs), data retention, hosting, version
   pinning. Record that no system card exists.
3. **Threat model.** Draw the four channels: the judged content, the option text, the
   returned probabilities, and the downstream executor. Then ask the design questions that
   need no testing: Can untrusted data reach option labels or criteria? Is there an abstain
   option? Is a refusal treated as allow? Could a deterministic rule over typed fields make
   this decision instead? Is the full distribution logged? Are aliases pinned?
4. **Measure.** Your own labelled cases first, then perturbation and injection variants,
   then public suites. Always alongside a baseline: a deterministic rule and an LLM judge.
5. **Decide.** The evidence supports approving these as a screening or routing layer and
   not as a sole authorisation gate. Conditions: deterministic final check, pinned version,
   a canary set re-run on a schedule to catch drift.

The same five steps apply to every subject; only the threat template and catalogue entries
change.

## 6. Reference frameworks to anchor on

Use these as vocabularies, not as the process: OWASP Top 10 for LLM Applications (2025) and
for Agentic Applications (Dec 2025) for risk ids; MITRE ATLAS v2026.10 for technique ids;
the AWS Agentic AI Security Scoping Matrix for the autonomy field in `review.yaml`;
Microsoft's agentic failure-mode taxonomy v2.0 as a red-team coverage list; CSA AI-CAIQ for
vendor questions; NIST AI RMF + AI 600-1 for mapping to governance language.

## 7. Phasing

| Phase | Work | Why this order |
|---|---|---|
| 0 | Move skills into `plugins/`, add manifests and marketplace file, standard frontmatter, CI `claude plugin validate`. Fix stale README and CONTRIBUTING. No behaviour change. | Everything else lands in the new layout |
| 1 | `ai-review` plugin, the four contracts, the benchmark catalogue | Makes existing skills part of a review; needed by every later skill |
| 2 | `voice-bench` and `decision-bench` | Both have review requests pending now |
| 3 | `harness-bench` | Largest build; depends on the decision about releasing the internal suite |
| 4 | `vision-bench`, `imagegen-review`, `feature-review` templates | Demand-driven |

The GPT Realtime 2.1 review does not have to wait for Phase 2: the recipe in §4.3 can be
run by hand with promptfoo or PyRIT, and its outputs become the first test of the contracts.

## 8. Decisions needed

1. **Standard:** dual manifests (Agent Plugins 1.0 + Claude marketplace), or Claude-only?
2. **Plugin grouping** in §3.2 — in particular whether decision models sit with
   `model-evals` or with the modality plugin.
3. **Where the verdict lives:** port the policy gate here (recommended) or keep it only in
   `ai-security-governance`.
4. **Internal harness suite:** can it be open-sourced as the `harness-bench` scenario pack?
5. **Boundary with `ai-security-sdlc`,** which already has `ai-evals` / `ai-redteam` and
   asset-scan plugins. That repo was not readable in this session, so overlap is unassessed.

## 9. Evidence caveats

Research was three single-pass web surveys. Not verified: runtime behaviour of dual-manifest
plugins outside Claude Code; whether a GPT-Realtime-2.x system card exists (none found);
dataset licences for JALMBench, AJailBench and SACRED-Bench; the JALMBench audio-vs-text
figures (search snippet only); OpenAI's own account of the July sandbox incident (fetch
blocked). Locally verified: `inspect_ai` 0.3.289 exposes `ContentAudio`/`ContentImage` and
the sandbox agent bridge; `inspect_evals` 0.29.0 contains no audio jailbreak benchmark.
