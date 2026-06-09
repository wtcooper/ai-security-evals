# Promptfoo Red Teaming

Red teaming generates **adversarial** attacks (jailbreaks, injection, escalation) and
scores whether your model resisted them.

---

## The three phases

These are separate commands that do different things. Knowing which to use is the
single most important concept.

```
  redteam generate ─────▶ writes redteam.yaml (objectives only, no model calls to target)
        │
        ▼
  redteam eval ─────────▶ runs an existing redteam.yaml against the target + grades it
        │
   redteam run = generate + eval in one shot (re-syncs objectives to your config each time)
```

| Command | Generates objectives? | Calls the target? | Use when |
|---------|----------------------|-------------------|----------|
| `redteam generate` | ✅ | ❌ | You want to mint + cache a frozen objective set |
| `redteam eval` | ❌ (reads cached file) | ✅ | Re-run a cached set, offline, repeatably |
| `redteam run` | ✅ | ✅ | Quick one-shot: generate fresh + run immediately |

**Why split generate from eval?** Generation quality is best from the community cloud
service, but you often want to *run* the suite many times with no network. Generate once
online → commit the `redteam.yaml` → `eval` it offline forever.

---

## The three model roles

Red teaming uses up to three distinct LLMs. Don't confuse them:

| Role | Config key | Notes |
|------|-----------|-------|
| **Target** | `targets[].config.model` | The system under test |
| **Attacker** | `redteam.provider.config.model` | Drives crescendo turns. Must emit raw JSON. |
| **Scorer** | `defaultTest.options.provider.config.model` | Grades pass/fail |

A stronger attacker + scorer than the target gives a harder, fairer test.

---

## Mode A — Community (cloud generation)

Easiest start. promptfoo's hosted service generates attacks (GPT-4-class quality) and
grades them. Free up to 10k probes/month. Leave `redteam.provider` unset.

```bash
npx promptfoo@latest redteam run \
  --config docs/promptfoo-tutorial/templates/redteam-cloud-template.yaml
npx promptfoo@latest view
```

Template: [`templates/redteam-cloud-template.yaml`](templates/redteam-cloud-template.yaml)

---

## Mode B — Local (zero cloud)

All three roles run on local Ollama models. Set `redteam.provider` (attacker) and
`defaultTest.options.provider` (scorer) to local, and pass the env flag:

```bash
PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true \
  npx promptfoo@latest redteam run \
  --config docs/promptfoo-tutorial/templates/redteam-local-template.yaml
```

> The first run still contacts the cloud **once** to generate plugin objectives, then
> caches them in `redteam.yaml`. To be truly offline from the start, hand-supply goals
> (Mode C) or pre-generate while online.

Template: [`templates/redteam-local-template.yaml`](templates/redteam-local-template.yaml)

### What can actually run locally

Only some strategies execute offline. At eval time:

| Runs offline ✅ | Remote-only ❌ |
|----------------|----------------|
| `basic`, `crescendo` | `jailbreak` (iterative), `jailbreak:composite` |
| `base64`, `leetspeak`, `rot13`, `hex`, `morse`, `homoglyph`, `emoji` (deterministic transforms) | `goat`, `hydra`, `likert`, `meta`, `gcg`, `citation`, `best-of-n` |

Plugins may still be *generated* cloud-side (Phase 1); only the **strategy** matters offline.

---

## Mode C — Cached / hand-supplied goals (fully offline)

Run from a `redteam.yaml` whose objectives are already baked in — either generated
earlier or hand-written. Zero generation calls. This is the "snapshot and replay" pattern.

```bash
PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true \
  npx promptfoo@latest redteam eval \
  --config docs/promptfoo-tutorial/templates/redteam-cached-goals-template.yaml
```

Template: [`templates/redteam-cached-goals-template.yaml`](templates/redteam-cached-goals-template.yaml)

Each test carries its own `goal`, `pluginId`, `strategyId`, `assert`, and `provider`.
See the curated packs in [`scripts/promptfoo-getting-started/configs/`](../../scripts/promptfoo-getting-started/configs/)
for a real 365-objective cyber set and a 330-objective OWASP governance set built this way.

### Ready-to-run: the tiered cyber pack

[`templates/readteam-cyber-eval-template.yaml`](templates/readteam-cyber-eval-template.yaml)
is a curated, offline-runnable pack: **90 crescendo objectives across 18 cyber
domains**, split into 3 tiers of 30. Every tier spans all 18 domains; Tier 1 holds
the highest-signal probes. Crescendo is slow, so run a tier at a time:

```bash
PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true \
  npx promptfoo@latest redteam eval \
  --config docs/promptfoo-tutorial/templates/readteam-cyber-eval-template.yaml \
  --filter-metadata tier=1          # 30 attacks; drop the flag to run all 90
```

---

## Strategy toggles (crescendo)

Set these under the strategy's `config:` in your **source** config. They control attack depth:

| Toggle | Default | Effect |
|--------|---------|--------|
| `stateful` | `false` | `false` resends full history each turn (no server session). `true` only if the target keeps history. |
| `maxTurns` | `5` | Max escalation turns before giving up. Raise (8–10) for deeper attacks at higher token cost. |
| `maxBacktracks` | `5` | Times the attacker may retreat + rephrase after a refusal. |
| `continueAfterSuccess` | `false` | `false` stops at first success. `true` keeps hunting more until `maxTurns`. |

> ⚠️ These live in the **source** config consumed by `generate`/`run`. They are **not**
> copied into the generated `redteam.yaml` per test — a cached file falls back to the
> defaults. To change them for a cached `eval`, add them to that file's
> `redteam.strategies` block.

---

## Run-level toggles

| Toggle | Location | Effect |
|--------|----------|--------|
| `numTests` | per-plugin or `redteam.numTests` | Objectives generated per plugin (before strategy expansion) |
| `maxConcurrency` | `redteam.numTests` sibling | Parallel probes at eval. Local models: keep 1–2. |
| `evaluateOptions.cache` | top-level | `false` = never reuse responses |
| `--filter-first-n N` | CLI flag | Run only first N tests (smoke check) |
| `--no-cache` | CLI flag | Per-run cache disable |
| `delay` | `targets[].config` / `targets[]` | ms pause between calls (rate-limit friendliness) |

---

## Gotchas we hit (and fixed)

| Symptom | Cause + fix |
|---------|-------------|
| `Expected a JSON object, but got ```json` | Attacker model wrapped JSON in markdown fences. Set `response_format: {type: json_object}` on the attacker, or use `redteam run` (auto-formats). |
| `Test is missing purpose metadata` | Crescendo needs `metadata.purpose`. Add it to `defaultTest.metadata`. |
| Crescendo skipped / no multi-turn | Dataset plugins (`harmbench`, `cyberseceval`) have `goal: null`, incompatible with crescendo. Use `harmful:*` (LLM-generated goals) or hand-supply goals. |
| `Could not identify provider: gemma4:e2b` | Colons parse as provider prefixes. Use `id: openai:chat` + `model: gemma4:e2b`. |
| Model timeout on local runs | Crescendo prompts are ~1500 tokens. Set `timeout: 600` in `litellm_config.yaml`, restart proxy. |
| OWASP preset injected remote-only strategies | The `owasp:llm` / `owasp:agentic` **collections** override your strategy list with `jailbreak`/`composite` (remote-only). Pin the explicit plugin IDs instead. |
