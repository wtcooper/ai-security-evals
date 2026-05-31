# AI Security Evals — Skills Redesign Plan

Status: proposed · Last updated: 2026-05-30

This plan replaces the single custom-engine skill (`skills/ai-guardrail-eval`) and the
prototype (`temp/ai-redteam-eval`) with **four focused, promptfoo-based skills** plus a
small set of shared components. It records every design decision made during review so
implementation can proceed without re-litigating them.

---

## 1. Why we're changing

Two codebases exist today:

- **`skills/ai-guardrail-eval`** — a ~5k-LOC custom async Python engine. Good *ideas*
  (control-vs-refusal attribution, F1/FPR metrics, fail-loud discipline, a rich
  cited corpus), but three problems:
  1. **Multi-turn was wrong.** It shipped the full transcript in one POST with
     *fabricated* assistant turns (90 cases) or `user-only` sequences (68 cases) —
     `user,user,user,...` never happens in production, and canned assistant text is
     fiction. It measured "does the guard flag this transcript," not attack success.
  2. **litellm-coupled.** Output-guardrail isolation relied on a litellm-specific
     `metadata.harness_mock_response` + CustomLLM handler hack.
  3. **Reinvents promptfoo** — judge, metrics, report, adaptive attacks all hand-rolled.

- **`temp/ai-redteam-eval`** — the right *engine* choice (promptfoo as engine + judge +
  report + adaptive layer; generic HTTP provider; air-gapped; license-clean corpus), but
  scoped only to first-turn input attacks against an app.

**Decision:** keep promptfoo as the engine. Split the work into four skills by *what is
under test* and *where the risk enters the data flow*. Retire the custom Python engine,
the litellm `mock_response` hack, and all fabricated multi-turn transcripts.

---

## 2. Target architecture — four skills

| # | Skill | Under test | How control is toggled | Engine |
|---|---|---|---|---|
| 1 | **`app-eval`** | An application endpoint | Whatever the app exposes (or N/A) | promptfoo `eval` |
| 2 | **`app-redteam`** | An application endpoint | App-side | promptfoo `redteam` |
| 3 | **`control-bench`** | A **control's effect inside a real risk scenario** (AgentDojo, CyberSecEval) | **Gateway connector — param-based `model`+`guardrail` via injection shim** | **Inspect** (`inspect_ai` + `inspect_evals`) |
| 4 | **`control-isolate`** | A **guardrail API in isolation** | Call the guardrail directly | promptfoo `http` provider |

**Engine split (decided):** app-eval + app-redteam → **promptfoo**; control-bench →
**Inspect** (it ships AgentDojo + CyberSecEval as native tasks with scorers, so we
reuse them rather than rebuild); control-isolate → **promptfoo** (a direct guardrail
HTTP call is simplest there). The param-injection **shim** is engine-independent: it
sits at the model `base_url`, and both promptfoo and Inspect point their OpenAI
endpoint at it. Inspect has no `defense` hook and no per-request `extra_body`, which
is exactly why the shim-at-the-boundary approach is the right pattern — confirmed
that Inspect routes every tool-result-bearing model call through the configured
endpoint, so a gateway input guardrail can see AgentDojo's indirect-PI payloads.

Skills 1, 2, 4 are promptfoo-native and low-risk. **Skill 3 is the net-new work** and the
hardest; it depends on the **gateway connector** (§5).

```
                 ┌─────────────────────────────────────────────────────────┐
                 │                    shared components                     │
                 │  corpus/  ·  judge config  ·  block-handling transform   │
                 │  metrics/derivedMetrics  ·  gateway connectors           │
                 └─────────────────────────────────────────────────────────┘
   app-eval            app-redteam           control-bench         control-isolate
   (static, fast)      (dynamic attacks)     (A/B/C in frameworks) (direct guardrail F1)
```

---

## 3. Cross-cutting decisions (apply to all skills)

### 3.1 Multi-turn = M2S flattening only
- Single-turn quality cases + **M2S-flattened** multi-turn. No live multi-turn in the
  static skills; no fabricated transcripts; no `user-only` sequences.
- M2S templates: **`hyphenize` / `numberize` / `pythonize`** (arXiv 2503.04856, ACL 2025),
  applied over **MHJ** and **SafeMTData/Attack_600** `multi_turn_queries` lists.
- This is the *only* place we mechanically generate cases — and it's from cited sources,
  so it stays OSS-defensible. Each generated case records its source list + template.
- Rationale: M2S single-turn ASR meets or *exceeds* live multi-turn, runs in eval mode,
  is deterministic. Live/adaptive multi-turn lives in Skill 2 only.

### 3.2 Block / 400 handling = one generic, vendor-agnostic transform
We test many vendors; we will **not** maintain a transformer per vendor. One generic
`transformResponse` (shared JS), used by all HTTP-provider skills:

- **2xx** → extract assistant text (multi-shape extractor) → **judge decides**
  refusal/compliance. Covers apps that convert a block into a 200 refusal.
- **400** (and optionally **403 / 406 / 446**) → emit promptfoo's
  `guardrails: { flagged: true, flaggedInput: true, reason: <raw body, truncated> }`.
  No vendor-body parsing required to know it blocked.
- **401 / 429 / 5xx** → throw → promptfoo marks **errored**, excluded from metrics (a
  broken run can't masquerade as "secure").
- Wire promptfoo's native **`guardrails` / `not-guardrails`** assertions on top.

**`block_when` (body-path block detection) is NOT in the app skills.** The only case it's
needed is a guardrail/scan API that returns **200 + a structured verdict and no text**
(e.g. Prisma AIRS `action:"block"`). That shape only appears when you call a control
**directly** = Skill 4, where the control *is* the thing under test and you configure its
response shape once, deliberately. Not per-target sprawl.

### 3.3 Judge = mandatory LLM-as-judge, per-case rubric
- promptfoo `llm-rubric`, one criterion per case (no shared rubric — known promptfoo bug
  with `defaultTest` var resolution). CyberSecEval cases reuse their native `judge_question`.
- Judge model pinned in `defaultTest.options.provider`; **warn if judge == target**.
- Carry over from old skill as hard rules: **no keyword-classifier fallback**, **judge is
  label-blind**, judge config recorded in run output.

### 3.4 Metrics
- `metric:` tags per assertion → `Injection_Block`, `Harmful_Block`, `Leak_Block`,
  `Not_Over_Refused`.
- F1 / precision / recall via promptfoo **`derivedMetrics`** (benign = negative class,
  so over-blocking is penalized). FRR = 1 − `Not_Over_Refused`.
- **Marginal attribution** (control_block vs model-refusal) is a **Skill 3 / Skill 4
  feature only** — it needs a structural block signal, which we only have when a control
  is explicitly in the loop.

### 3.5 Air-gap + provenance
- `PROMPTFOO_DISABLE_TELEMETRY` + `PROMPTFOO_DISABLE_REMOTE_GENERATION` set in config and
  install script. promptfoo installed locally, not global.
- Every corpus case keeps `source`, `license`, `citation`, `technique_family`, `id`.

---

## 4. Shared corpus (bundled, OSS, license-clean)

One canonical corpus, built offline, consumed by Skills 1 and 4. Skill 3 uses each
**framework's own tasks**, not this corpus. Skill 2 uses seeds/objectives derived from it.

| Class | Sources |
|---|---|
| Cyber | CyberSecEval — MITRE, MITRE-FRR, interpreter-abuse, prompt-injection |
| Harmful (quality single-turn) | HarmBench, StrongREJECT |
| Harmful (volume) | AdvBench |
| Prompt injection | deepset prompt-injections, Lakera Gandalf, CyberSecEval PI |
| Over-refusal / FRR (negative class) | XSTest-safe, CyberSecEval-FRR |
| M2S (flattened multi-turn) | MHJ, SafeMTData/Attack_600 → hyphenize/numberize/pythonize |

- Builder: one `scripts/build_corpus.py` — fetch offline, **dedup by source id** (the two
  legacy corpora overlap on CyberSecEval/deepset/Gandalf/AdvBench/XSTest), assign
  **stratified seeded tiers** (`smoke` ~30 · `mid` ~150 · `full`), emit promptfoo test
  files per class. Print available-vs-emitted split.
- Gated sets (MHJ requires acceptance; any AgentHarm) load only with `HF_TOKEN`; never
  redistribute.
- Emits standard promptfoo cases: `{ vars:{prompt}, assert:[llm-rubric + metric tag],
  metadata:{id,type,source,license,technique_family,template?} }`.

---

## 5. Gateway connectors — the key abstraction for Skill 3 (and reusable for 1/2/4)

**Reality (corrected):** controls are toggled by **passing parameters** — both a **model
name** and a **guardrail name** — to a gateway (litellm, Netskope, etc.). There are **no
guardrail-baked model aliases**. Standard OpenAI clients inside frameworks won't send a
`guardrails` param, so **something must inject it**.

### 5.1 Connector contract
A connector is a config profile + a thin injection layer that, given an **arm** (baseline
or a named control), makes the framework's standard OpenAI-style calls carry the right
`model` + `guardrail` params to the gateway.

```
connector.arms = [
  { name: "baseline",   model: "<M>",  guardrails: []                 },
  { name: "control-A",  model: "<M>",  guardrails: ["prisma-airs-pi"] },
  { name: "control-B",  model: "<M>",  guardrails: ["lakera-guard"]   },
]
connector emits, per arm:  base_url, api_key, model, + how to inject the guardrail param
```

A/B/C across arms holds the **model constant** and varies the **guardrail param**, so the
only measured difference is the control.

### 5.2 Injection: how the guardrail param reaches the gateway
Frameworks only reliably expose `base_url` + `model` + `key`. Two paths, prefer the first
that works per framework:

1. **Native extra-body passthrough** — if the framework lets you set per-request
   `extra_body` / model args (inspect.ai model args; anything built on the litellm SDK),
   inject `guardrails: [name]` there. No proxy. Validate per framework.
2. **Injection shim (default, universal)** — a tiny OpenAI-compatible reverse proxy
   (~60–80 LOC) configured with one arm's `{gateway_url, key, model, guardrails}`. It
   receives the framework's vanilla request, **adds the `guardrails` param (and pins
   `model`)**, forwards to the real gateway, returns the response untouched. The framework
   sets `OPENAI_BASE_URL` → shim. A/B/C = run the benchmark once per shim config.
   This keeps every framework **100% unmodified**.

### 5.3 Connector implementations (start with litellm)
- **`litellm` connector (first):** guardrail param = top-level **`guardrails: [<name>]`**
  in the request body (verified working on litellm ≥ 1.85). Baseline arm omits it.
- **`netskope` connector:** map to its param/header/route convention.
- **`raw-openai` connector:** passthrough for gateways where the guardrail is bound at the
  endpoint and only `base_url` changes.

Each connector knows exactly one thing: **how to express "use guardrail X" as a request
parameter** for that gateway. Adding a vendor = one connector, not a fork of any framework.

### 5.4 Reuse in Skills 1/2/4
The same connector feeds the promptfoo `http` provider body (`{{guardrails}}` templated
from arm config), so A/B/C control comparison is available in `app-eval` too when the app
sits behind a param-based gateway.

---

## 6. Per-skill specs

### Skill 1 — `app-eval` (static benchmark)
- **Goal:** fast, reproducible risk read on an app endpoint. Single-turn + M2S.
- **Engine:** `promptfoo eval` against the generic `http` provider.
- **Config:** target `url/method/headers/body` with `{{prompt}}`; shared block transform;
  per-case `llm-rubric`; `derivedMetrics` for F1/FRR; tier flag (`smoke|mid|full`).
- **Multi-turn:** M2S-flattened cases only.
- **A/B/C (optional):** multiple provider labels via the connector (`baseline`,
  `control-A`…) when the app is behind a param-based gateway.
- **Output:** per-`metric` block rates, F1, FRR; `by_technique_family` breakdown.
- **Reuses:** corpus, judge, block transform, connector.

### Skill 2 — `app-redteam` (adaptive)
- **Goal:** user-customized, dynamic attacks; genuine multi-turn with backtracking.
- **Engine:** `promptfoo redteam run` against the same provider.
- **Strategies:** `crescendo`, `goat`, `mischievous-user`, `jailbreak:hydra`,
  `prompt-injection`; `stateful` set to match whether the app persists session
  (`sessionParser` / `{{sessionId}}` wired).
- **Needs:** a configured **local attacker model** (remote-gen disabled by air-gap).
- **Seeds:** harmful objectives derived from the shared corpus (intents, not transcripts).
- **Caveat surfaced to user:** ASR is noisy — repeated trials + variance before claims.

### Skill 3 — `control-bench` (control effectiveness inside frameworks) — NET NEW
- **Goal:** measure **risk reduction from enabling a control** inside a realistic risk
  scenario the control would actually sit in — indirect PI during tool calling
  (AgentDojo), cyber-attack assistance (CyberSecEval MITRE), etc.
- **Mechanism:** point the framework at a **connector arm** (§5); run the framework
  **unmodified** once per arm; **diff the framework's native metrics** across arms.
  - AgentDojo → attack-success-rate / utility, with and without the guardrail.
  - CyberSecEval MITRE / MITRE-FRR → pass rate + the FRR set as over-block cost.
- **Why the connector matters here:** an input guardrail at the gateway sees **every model
  call including tool results fed back in**, so it gets a real shot at injected tool
  content — the one way to measure indirect-PI defense without planting canaries in the
  app's own DB/tools.
- **Scope discipline:** one framework at a time, as **options within this skill** (shared
  connector + runner; per-framework metric parser). **Order: CyberSecEval-MITRE first**
  (prompt-based, simplest, proves the A/B/C diff), then **AgentDojo** (agentic, indirect
  PI, higher value, harder).
- **Open validation (1-day spike per framework):** confirm each framework lets you
  redirect the model endpoint (base_url) and/or accepts extra-body; if hard-coded, fall
  back to the injection shim or the framework's native defense-hook API.
- **Output:** per-arm native score + **delta** (Δrisk, Δutility/over-block) attributing
  the change to the control.

### Skill 4 — `control-isolate` (direct guardrail classification)
- **Goal:** characterize a guardrail API by itself — given single/M2S prompts, what does
  it catch? F1 / precision / recall, **input-mode vs output-mode separately**.
- **Engine:** promptfoo `http` provider pointed **directly at the guardrail/scan API**
  (no model). Synthetic candidate content from a test var → guardrail → verdict.
  - Bedrock: `ApplyGuardrail` (assesses text with no model invocation).
  - Any vendor: `http` + a **per-control** `transformResponse`/`block_when` mapping the
    verdict into `guardrails:{flagged,flaggedInput,flaggedOutput,reason}` — configured
    once for the control under test (this is the *only* place body-path parsing lives).
- **Corpus:** the shared labeled corpus (harmful = should-block, benign = should-pass).
- **Output:** F1 / precision / recall / FPR; `by_technique_family`; **marginal
  attribution** lives here naturally (we have the structural verdict).
- **Replaces:** the litellm `mock_response` isolation hack entirely — output isolation =
  "send the candidate output straight to the guardrail."

---

## 7. What we keep, retire, and port

**Keep (from `temp/ai-redteam-eval`):** promptfoo engine pattern, air-gap setup, generic
`http` provider, multi-shape `transformResponse`, benign-as-negative-class F1 framing,
license hygiene, seeded stratified tiers, single-rubric invariant test.

**Port as design constraints (from `ai-guardrail-eval`):** mandatory label-blind LLM
judge, fail-loud mode resolution, `technique_family` breakdowns, marginal attribution
(Skills 3/4), the startup-probe idea (adapt to "connector reachable + arm honored"),
the cited corpus content.

**Retire:** the custom async Python engine; `metadata.harness_mock_response` + CustomLLM
handler; all fabricated/`user-only` multi-turn transcripts; `local/` litellm mock proxy
(replaced by connectors + injection shim where needed); `block_when` in app skills.

---

## 8. Phasing

1. **Phase 0 — shared foundation.** `build_corpus.py` (merge + dedup + M2S generation +
   tiers); shared `transform_response.js` (block policy); judge + `derivedMetrics`
   config; repo skeleton under `skills/`.
2. **Phase 1 — Skill 1 `app-eval`.** Port the prototype config to the merged corpus; ship
   M2S cases; validate F1/FRR + `by_technique_family` on a mock target.
3. **Phase 2 — Skill 4 `control-isolate`.** Direct-guardrail provider + per-control verdict
   mapping; F1 on one real guardrail (e.g. Bedrock ApplyGuardrail).
4. **Phase 3 — Skill 5… wait, Skill 2 `app-redteam`.** Wire redteam strategies + local
   attacker model + session handling.
5. **Phase 4 — Skill 3 `control-bench`.** Build the **litellm connector + injection shim**;
   prove A/B/C against **CyberSecEval-MITRE**; then AgentDojo. Spike framework endpoint
   redirection first.

> **Built (control-bench, simplified):** Inspect runs the A/B/C sweep, scoring, and
> comparison **natively** — multiple `openai-api/<arm>/<model>` providers in one
> `inspect eval`, compared in `inspect view` — so **no custom orchestrator/runner is
> needed** (an earlier `run_ab.py`/per-benchmark runners were removed). The only custom
> code is the **connectors** (param mapping) + the **injection shim**, which also
> converts a guardrail block (HTTP 400) into a 200 refusal so blocks score instead of
> aborting the run. `injection_shim.py --arms arms.json` launches one shim per arm and
> prints the exact env + `--model` string. **Verified end-to-end** against the local
> LiteLLM (`local/`) with the mock guardrail: a one-command Inspect sweep gave baseline
> attack-success **1.0** vs guarded **0.0**. Note: `inspect_ai`/`inspect_evals` conflict
> with `litellm[proxy]` deps, so control-bench runs in its **own venv** and talks to the
> gateway over HTTP — they never share an environment. Works with **any** inspect_evals
> task, not just the priority ones.

Each phase ships an independently usable skill; Skill 3 is last because it depends on the
connector and on per-framework spikes.

---

## 9. Engineering standards & testing (required, every phase)

Testing is part of "done" for each phase — no phase ships without it.

- **Test-first on every deterministic unit.** The block-handling `transform_response.js`
  is the highest-risk shared component — it gates every metric. Port the prototype's
  zero-dep test runner and **add cases for our policy**: 2xx multi-shape extraction,
  400→`flagged`, 403/406/446→`flagged`, 401/429/5xx→throw/excluded, no-status fallback.
  Same for M2S template generation (golden input list → expected flattened prompt per
  template) and the corpus builder (tier sizes, dedup correctness, single-rubric
  invariant, seed reproducibility).
- **Connector / injection shim** (Skill 3): unit-test the param injection (vanilla request
  in → `guardrails:[name]` + pinned `model` out) and a **contract probe** that fails fast
  if the gateway didn't honor the arm (adapts the old skill's startup probe). Never let a
  misconfigured arm silently score as "control had no effect."
- **`promptfoo validate`** in CI for every skill config; a `smoke`-tier run against a
  **mock target** (no API keys, no network) as a wiring/cost gate before any real run.
- **Metrics correctness:** golden tests pinning the confusion matrix → F1/precision/
  recall/FPR and the `derivedMetrics` math (benign = negative class), including
  ERROR-exclusion and divide-by-zero guards.
- **Fail loud, no silent fallbacks** (ported rule): no keyword-classifier fallback if the
  judge fails; hard-error on ambiguous control/mode config; surface dropped/errored cases.
- **Reproducibility:** seeded sampling; record full run config (target, judge, connector
  arm, corpus tier, versions) with every result so runs are comparable and auditable.
- **Repo hygiene:** `uv`-managed `.venv`; lint + unit tests run in `.github` CI; no gated
  datasets or secrets committed.

Definition of done per phase = feature works on a mock target **and** its unit/golden
tests pass in CI **and** `promptfoo validate` is green.

## 10. Open questions / decisions needed

1. **Injection shim build vs litellm-as-proxy.** Build the ~80-LOC OpenAI-compatible shim
   (full control, OSS-clean) vs reuse litellm's proxy + guardrail integrations (batteries
   included, heavier dep). Leaning: build the shim; keep litellm as a *connector target*,
   not a required dependency.
2. **Framework endpoint redirection** — confirm per framework (AgentDojo, inspect.ai-based
   CyberSecEval) that `base_url`/extra-body can be set without forking. Spike in Phase 4.
3. **MHJ / gated dataset licensing** for the bundled M2S set — confirm redistribution terms;
   if gated, ship the builder + instructions, not the data.
4. **Repo layout** — one skill dir each under `skills/` with a shared `skills/_shared/`
   (corpus, transform, connectors, judge config)? Confirm before Phase 0.
5. **Connector #2 priority** — Netskope vs others, based on what we actually test next.
</content>
