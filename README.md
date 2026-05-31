# ai-security-evals

Distributable **Claude Code skills** for evaluating the security of LLM applications
and the controls that protect them.

Each skill is an interactive **Plan → Run → Analyze** runbook that Claude Code executes
on your behalf — it gathers your target endpoint/auth/body schema, picks the corpus or
benchmark and the judge/attacker models, writes the config + `.env`, runs the eval, and
summarizes the metrics. You don't hand-edit YAML; the skill drives it.

Engines are off-the-shelf: **promptfoo** for app testing and guardrail isolation,
**Inspect** (`inspect_ai` + `inspect_evals`) for control effectiveness inside real
agentic/cyber benchmarks. The repo's own code is a thin shared layer (corpus builder,
status-policy transform, metrics, gateway shim).

---

## The four skills

Split by **what is under test**. They share a corpus, transform, and metrics layer in
[`skills/_shared/`](skills/_shared/). See
[`docs/skills-redesign-plan.md`](docs/skills-redesign-plan.md) for the design rationale.

| Skill | Under test | Engine | Output |
|---|---|---|---|
| [`app-eval`](skills/app-eval/) | An app endpoint — fast static benchmark | promptfoo `eval` | F1 / recall / FPR / ASR + per-technique breakdown |
| [`app-redteam`](skills/app-redteam/) | An app endpoint — adaptive attacks | promptfoo `redteam` | which strategies broke through (vuln report) |
| [`control-isolate`](skills/control-isolate/) | A guardrail API by itself (no model) | promptfoo `eval` | classification F1 / precision / recall / FPR |
| [`control-bench`](skills/control-bench/) | A control's effect inside a real benchmark | Inspect + inspect_evals | risk-reduction Δ vs baseline (A/B/C) |
| [`ai-guardrail-eval`](skills/ai-guardrail-eval/) | _(legacy)_ original custom-engine A/B/C harness | custom Python | superseded by the four above |

### When to use which

| You want to… | Skill |
|---|---|
| Get a fast, reproducible safety score for your chatbot/app | `app-eval` |
| Compare two app versions or models on the same corpus | `app-eval` |
| Actively hunt vulnerabilities with adaptive multi-turn attacks | `app-redteam` |
| Measure a guardrail vendor's catch rate and false-positive rate | `control-isolate` |
| Compare guardrail vendors head-to-head | `control-isolate` |
| Prove "enabling guardrail X reduces risk on AgentDojo/CyberSecEval" | `control-bench` |
| Measure indirect-prompt-injection defense during agent tool calls | `control-bench` |

---

## What each skill measures

### `app-eval` — static security benchmark (promptfoo)
| Aspect | Detail |
|---|---|
| Corpus | Bundled, license-clean: prompt injection, harmful content, data leakage, over-refusal (benign negative class) + **M2S-flattened** multi-turn jailbreaks |
| Tiers | `smoke` (~30) · `mid` (~150) · `full` (~2000), stratified + seeded |
| Grading | LLM-as-judge (`llm-rubric`), one criterion per case; judge pinned, gated against judge==target |
| Metrics | F1, Recall (block rate), FPR (over-refusal), ASR, `by_technique_family` |
| A/B/C | Optional: duplicate the provider with a guardrail body param to compare control on/off |

### `app-redteam` — adaptive red team (promptfoo)
| Aspect | Detail |
|---|---|
| Attacks | Multi-turn `crescendo` / `goat` / `mischievous-user` (attacker adapts to real replies, backtracks) + single-turn `jailbreak` / `prompt-injection` |
| Models | Attacker + grader are OpenAI-compatible — point at your production LiteLLM (`ATTACKER_*`, `GRADER_*`) |
| Sessions | `stateful: false` (promptfoo owns history) or `true` (app persists; `sessionParser`) |
| Output | `promptfoo redteam report` vuln UI; flags which strategies succeeded |
| Caveat | ASR is noisy — run repeated trials and report variance |

### `control-isolate` — direct guardrail classification (promptfoo)
| Aspect | Detail |
|---|---|
| Method | Sends the labeled corpus straight to the guardrail (no model); grades the guardrail's own verdict |
| Vendor mapping | `adapters/generic_guardrail.js` recognizes `action:block` / `blocked` / `flagged` / `is_malicious` / a block status; override via `GUARDRAIL_BLOCK_STATUSES` / `GUARDRAIL_BLOCK_FIELD`+`VALUE` |
| Channels | Test input-side and output-side separately (two experiments) |
| Metrics | F1 / precision / recall / FPR + `by_technique_family`; no LLM judge |

### `control-bench` — control effectiveness inside Inspect benchmarks
| Aspect | Detail |
|---|---|
| Benchmarks | **Any** `inspect_evals` task — AgentDojo (indirect-PI during tool calling), `cyse4_mitre` / `cyse4_mitre_frr`, `cyse2_prompt_injection`, … |
| Mechanism | A param-injection **shim** adds `model`+`guardrail` per arm at the model boundary; Inspect runs the A/B/C sweep natively across `openai-api/<arm>/<model>` providers |
| Connectors | `litellm` (top-level `guardrails:[name]`), `openai` passthrough (Netskope/others) |
| Output | Inspect's native scores per arm — diff attack-success (risk ↓) and utility/FRR (over-block cost) |
| Note | Inspect conflicts with `litellm[proxy]` deps → runs in its own `.venv-inspect` |

**Multi-turn approach:** the static skills capture multi-turn *difficulty* via **M2S**
(multi-turn→single-turn, arXiv:2503.04856) — MHJ human jailbreaks collapsed into one
prompt (hyphenize/numberize/pythonize), no fabricated assistant turns. Live escalation
dynamics live in `app-redteam`.

**Vendor-agnostic block handling:** the shared `_shared/status_policy.js` is the single
source of truth — 2xx → judged text; a block status (default `400`, set
`GUARDRAIL_BLOCK_STATUSES` per vendor) → promptfoo `guardrails` block; any other non-2xx
(incl. 3xx) → errored and excluded from metrics. No per-vendor transformer needed.

---

## Repository layout

```
ai-security-evals/
├── pyproject.toml                  # uv-managed Python deps (Python 3.11+)
├── scripts/run_tests.sh            # all Node + Python tests, offline
├── docs/skills-redesign-plan.md    # design rationale for the four skills
├── local/                          # local LiteLLM proxy: mock models + mock guardrail
└── skills/
    ├── _shared/                    # shared layer used by the skills
    │   ├── status_policy.js        #   single HTTP-status block policy (JS)
    │   ├── transform_response.js   #   promptfoo transformResponse (uses status_policy)
    │   ├── build_corpus.py         #   builds promptfoo test files; M2S; dedup; tiers
    │   ├── m2s.py                  #   multi-turn→single-turn flattening templates
    │   ├── summarize.py            #   F1/recall/FPR/ASR + by_technique_family
    │   ├── corpus/sources/         #   vendored offline datasets (license-clean)
    │   └── tests/                  #   unit tests + mock_server.py
    ├── app-eval/                   # SKILL.md · promptfooconfig.yaml · env.example
    ├── app-redteam/                # SKILL.md · promptfooconfig.yaml · env.example
    ├── control-isolate/            # SKILL.md · promptfooconfig.yaml · adapters/ · env.example
    ├── control-bench/              # SKILL.md · injection_shim.py · connectors/ · arms.example.json
    └── ai-guardrail-eval/          # legacy custom-engine harness (superseded)
```

The shared corpus (`skills/_shared/corpus/promptfoo/`) and the control-isolate corpus are
**generated** by `build_corpus.py` and gitignored. The research-only MHJ source
(`mhj_multiturn.csv`) is also gitignored — provide it locally to include M2S cases;
without it the builder warns and omits the multi-turn dimension.

---

## Quick start

### Prerequisites
- Python 3.11+ with [`uv`](https://docs.astral.sh/uv/) · Node 18+ (for promptfoo)
- For `control-bench`: a separate venv with `inspect_ai` + `inspect_evals`

```bash
uv sync                       # Python deps for the shared layer + tests
bash scripts/run_tests.sh     # verify everything offline (no keys): Node + Python tests
```

### Run a skill (via Claude Code)
Open the repo in Claude Code and invoke the skill — it runs the Plan → Run → Analyze
runbook and asks you for the details it needs:
```
/app-eval        # benchmark an app
/app-redteam     # adaptive red team
/control-isolate # test a guardrail API
/control-bench   # A/B/C a control inside a benchmark
```

### Run a skill manually (app-eval example)
```bash
cd skills/app-eval
cp env.example .env && $EDITOR .env          # TARGET_URL/KEY, JUDGE_URL/KEY/MODEL
bash install_dependencies.sh                 # promptfoo, air-gapped

python ../_shared/build_corpus.py --tier smoke   # build the corpus (~30 cases)
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output results.json
python ../_shared/summarize.py results.json      # F1 / recall / FPR / ASR + breakdown
```

### Try it with zero API keys (local mock gateway)
The `local/` LiteLLM proxy ships mock target models and a mock guardrail, so you can
exercise the full pipeline offline:
```bash
bash local/start_proxy.sh &                  # mock gateway on :4000
# point a skill's TARGET_URL/GUARDRAIL_URL at the mock and run as above
```

### control-bench (separate venv)
```bash
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai 'inspect_evals[agentdojo]'
# define arms.json (baseline + each control), launch shims, run any inspect task:
SHIM_GATEWAY_URL=http://localhost:4000 SHIM_GATEWAY_KEY=$KEY \
  python skills/control-bench/injection_shim.py --arms arms.json --base-port 8901
# it prints the env + `inspect eval inspect_evals/<task> --model "openai-api/...,..."` line
```

---

## Tests

```bash
bash scripts/run_tests.sh     # Node (transform / guardrail adapter) + Python (corpus / metrics / shim / connectors)
```
All tests run offline with no API keys. CI (`.github/workflows/ci.yml`) additionally
validates every promptfoo config.

## License

MIT. See [`LICENSE`](LICENSE). Bundled benchmark datasets retain their original licenses
(per-case `license` metadata); gated/research-only sources (MHJ, AgentHarm) are not
redistributed.
</content>
