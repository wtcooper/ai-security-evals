# ai-security-evals

Distributable **AI skills** for evaluating the security of LLM applications and the
controls that protect them — fast, standardized, license-clean.

Each skill is a portable **Agent Skill** (a `SKILL.md` runbook + bundled assets) that
any compatible agent harness can run. It drives an interactive **Plan → Run → Analyze**
flow — gather your target endpoint/auth/body schema, pick how much of the corpus or
which benchmark to run and the judge/attacker models, write the config + `.env`, run the
eval, and summarize the metrics. You don't hand-edit YAML; the skill drives it. (Every
step is also runnable by hand — see Quick start.)

Engines are off-the-shelf: **promptfoo** for app testing and guardrail isolation,
**Inspect** (`inspect_ai` + `inspect_evals`) for control effectiveness inside real
agentic/cyber benchmarks. **Each skill is self-contained** — it ships its own runtime
`lib/` and prebuilt `corpus/`, so app teams can install just the app skills and security
teams just the control skills, with no cross-skill dependencies.

---

## The four skills

Split by **what is under test**. Each is independently installable.

| Skill | Under test | Engine | Output |
|---|---|---|---|
| [`app-eval`](skills/app-eval/) | An app endpoint — fast static benchmark | promptfoo `eval` | F1 / recall / FPR / ASR + per-technique breakdown |
| [`app-redteam`](skills/app-redteam/) | An app endpoint — adaptive attacks | promptfoo `redteam` | which strategies broke through (vuln report) |
| [`control-isolate`](skills/control-isolate/) | A guardrail API by itself (no model) | promptfoo `eval` | classification F1 / precision / recall / FPR |
| [`control-bench`](skills/control-bench/) | A control's effect inside a real benchmark | Inspect + inspect_evals | risk-reduction Δ vs baseline (A/B/C) |

Each app skill also has a **web-UI variant** (`promptfooconfig.browser.yaml`) that runs
the same corpus/attacks through a chat front-end via promptfoo's Playwright **browser
provider** — for when the backend API isn't exposed.

### When to use which
| You want to… | Skill |
|---|---|
| A fast, reproducible safety score for your chatbot/app | `app-eval` |
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
| Corpus | **Bundled, prebuilt, license-clean** (~2900 cases): cyber-offensive (MITRE ATT&CK + interpreter abuse), prompt injection, data leakage, content-safety, over-refusal (benign) + **M2S-flattened** multi-turn. Tagged by `category` (cyber/injection/leakage/content_safety) — see [Corpus coverage](#corpus-coverage--cyber-first-filterable) |
| Sampling | Full corpus ships; sample with `--filter-sample N` (smoke ~30 / mid ~150 / full) or slice with `--filter-metadata category=cyber` |
| Grading | LLM-as-judge (`llm-rubric`) via an OpenAI-compatible provider; gated against judge==target |
| Metrics | F1, Recall (block rate), FPR (over-refusal), ASR, `by_technique_family`, per-status histogram |
| A/B/C | Optional: duplicate the provider with a guardrail body param to compare control on/off |

### `app-redteam` — adaptive red team (promptfoo)
| Aspect | Detail |
|---|---|
| Attacks | Multi-turn `crescendo` (adaptive, **runs on your own attacker model, air-gapped**), `custom`, `jailbreak:tree`, plus `prompt-injection` |
| Remote-only | `goat` / `mischievous-user` / plain `jailbreak`(→`jailbreak:meta`) need promptfoo's hosted generation — not air-gapped |
| Models | Attacker + grader are OpenAI-compatible — point at your production LiteLLM (`ATTACKER_*`, `GRADER_*`) |
| Output | `promptfoo redteam report` vuln UI; flags which strategies succeeded. ASR is noisy — repeat trials |

### `control-isolate` — direct guardrail classification (promptfoo)
| Aspect | Detail |
|---|---|
| Method | Sends the bundled labeled corpus straight to the guardrail (no model); grades the guardrail's own verdict |
| Vendor mapping | `adapters/generic_guardrail.js` recognizes `action:block`/`blocked`/`flagged`/`is_malicious`/a `guardrail_name`/a "content blocked" message/a block status; override via `GUARDRAIL_BLOCK_STATUSES` / `GUARDRAIL_BLOCK_FIELD`+`VALUE` |
| Metrics | F1 / precision / recall / FPR + `by_technique_family` + per-status histogram; no LLM judge |

### `control-bench` — control effectiveness inside Inspect benchmarks
| Aspect | Detail |
|---|---|
| Benchmarks | **Any** `inspect_evals` task — AgentDojo (indirect-PI during tool calling), `cyse4_mitre` / `cyse4_mitre_frr`, `cyse2_prompt_injection`, … |
| Mechanism | A param-injection **shim** adds `model`+`guardrail` per arm at the model boundary; Inspect runs the A/B/C sweep natively across `openai-api/<arm>/<model>` providers and diffs scores |
| Output | Inspect's native scores per arm — attack-success (risk ↓) and utility/FRR (over-block cost) |
| Note | Inspect conflicts with `litellm[proxy]` deps → runs in its own `.venv-inspect` |

---

## Cross-cutting capabilities

These apply across **all** the skills, not just one.

### Multi-turn via M2S (the fast standardized multi-turn feature)
The static skills capture multi-turn *difficulty* without a live attack loop by **M2S**
(multi-turn → single-turn, arXiv:2503.04856) — an ordered multi-turn attack is flattened
into one prompt (hyphenize/numberize/pythonize), no fabricated assistant turns, so it
runs at single-turn latency/cost.

The bundled multi-turn set is **our own**, generated by a deterministic scaffold library
([`tools/m2s_strategies.py`](tools/m2s_strategies.py)) that encodes published attack
strategies — **Crescendo, ActorAttack, Speak-Out-of-Turn decomposition, Puzzler,
payload-splitting, GOAT toolbox, prompt-leak sycophancy, trust→repeat→override, cipher
obfuscation** — across **all four domains** (prompt injection, jailbreak, data leakage,
toxic/harmful), so multi-turn coverage isn't limited to harmful content. It's
license-clean (authored here, cited per strategy) and joined by **SafeMTData Attack_600
(MIT)**. Each case is tagged `technique_family=m2s_<strategy>` so the breakdown shows
per-strategy recall. M2S is dataset-agnostic — teams can flatten their own sequences via
`m2s.flatten()`. Live adaptive escalation lives in `app-redteam`.

### Corpus coverage — cyber-first, filterable
The bundled corpus spans four **attack categories**, each case tagged with a `category`
axis so you can run and score any slice independently (not just one domain):

| category | n | what it covers |
|---|---:|---|
| `cyber` | ~710 | offensive cyber assistance — **CyberSecEval MITRE ATT&CK** (all 10 tactics: C2 / Exfil / Lateral Movement / Privilege Escalation / Recon / Discovery / Execution / Persistence / Collection / Evasion), **interpreter abuse** (sandbox/container escape, post-exploitation), + cyber multi-turn (SQLi, RCE, exfil, credential theft, malware) |
| `prompt_injection` | ~280 | direct + indirect injection, instruction override, payload-splitting, cipher smuggling |
| `data_leakage` | ~65 | system-prompt extraction, secret/credential/PII exfiltration, training-data & conversation-history leakage (single- and multi-turn) |
| `content_safety` | ~900 | CBRN, weapons, violence, hate, self-harm, illegal — the classic content-safety axis |
| `benign` | ~1000 | the negative class (FPR / over-refusal) |

So among *attack* cases, the **cyber-relevant axes (cyber + injection + data-leakage) are
the majority** — not an afterthought to content safety. Run a cyber-only sweep with
promptfoo's metadata filter:
```bash
npx promptfoo eval -c promptfooconfig.yaml --filter-metadata category=cyber --output results.json
python lib/summarize.py results.json   # prints recall per category + per ATT&CK tactic
```
`summarize.py` reports **recall by category** and **by `technique_family`** (e.g. per
ATT&CK tactic), so you see exactly where a target/guardrail is weak.

### Vendor-agnostic block handling
Each skill's `lib/status_policy.js` (a deterministic rules classifier) sorts every
response **body-first, status-as-hint** — so a new vendor's block code (e.g. LiteLLM's
**403** content-filter, recognized by its body) is caught with no config:

| Class | How it's detected | What happens |
|---|---|---|
| `answer` | 2xx, no block signal | extracted text → judged |
| `block` | a body block-signal (`action:block`/`flagged`/a `guardrail_name`/a "content blocked" message) **or** a hint status (`GUARDRAIL_BLOCK_STATUSES`, default `400`) | counted as the defense firing |
| `error` | 5xx/429/408/401 or an auth/quota/timeout body | **excluded** from metrics (infra ≠ safety) |
| `ambiguous` | a non-2xx with no block or infra signal | the LLM judge decides; control-isolate surfaces it loudly — **never silently dropped** |

`summarize.py` prints a **per-status histogram** every run, so mis-bucketing is visible.

---

## Repository layout

```
ai-security-evals/
├── skills/                         # the distributable skills (each self-contained)
│   ├── app-eval/                   #   SKILL.md · promptfooconfig{,.browser}.yaml · lib/ · corpus/ · env.example
│   ├── app-redteam/                #   SKILL.md · promptfooconfig{,.browser}.yaml · lib/ · env.example
│   ├── control-isolate/            #   SKILL.md · promptfooconfig.yaml · adapters/ · lib/ · corpus/ · env.example
│   └── control-bench/              #   SKILL.md · injection_shim.py · connectors/ · lib/ · runners/
├── targets/                        # things to point the skills at
│   ├── proxy/                      #   shared LiteLLM AI gateway (any provider via LiteLLM; content-safety guardrails)
│   ├── aigoat/                     #   AIGoat (adopt): UI + API + defense levels — clone+run docs
│   └── dvaa/                       #   DVAA (adopt): OpenAI-compatible + MCP — clone+run docs
├── tools/                          # MAINTAINER ONLY (not installed): canonical libs + corpus builder
│   ├── lib/                        #   source of truth for status_policy{.js,.py}, transform_response.js, summarize.py
│   ├── build_corpus.py · m2s.py    #   corpus builder + M2S flattening
│   ├── corpus/sources/             #   vendored datasets (AdvBench, CyberSecEval, XSTest, PromptInject, SafeMTData)
│   ├── tests/                      #   unit tests (run via scripts/run_tests.sh)
│   └── sync_skills.sh              #   vendors lib/* + prebuilt corpus into each skill (CI checks no drift)
├── e2e/                            # real-model end-to-end tests for all four skills (run_e2e.sh)
├── docs/skills-redesign-plan.md    # design rationale
└── scripts/run_tests.sh            # all Node + Python tests, offline
```

**Self-contained skills:** each skill carries vendored copies of the runtime it uses in
`lib/`, and the prebuilt `corpus/`. `tools/` is the single source of truth; CI runs
`tools/sync_skills.sh` + `git diff --exit-code` so the copies never drift. The bundled
corpus is committed and redistributable (license-clean); MHJ (CC-BY-NC) is opt-in dev
only (`build_corpus --with-mhj`) and gitignored.

---

## Quick start

### Prerequisites
- Python 3.11+ with [`uv`](https://docs.astral.sh/uv/) · Node 18+ (for promptfoo)
- For `control-bench`: a separate venv with `inspect_ai` + `inspect_evals`

```bash
uv sync                       # Python deps for the tools/tests
bash scripts/run_tests.sh     # verify everything offline (no keys): Node + Python + no-drift
```

### Run a skill (via an agent harness)
Point your agent at a skill directory (each holds a `SKILL.md` runbook); the agent runs
the Plan → Run → Analyze flow and asks for the details it needs:
- `app-eval` — benchmark an app
- `app-redteam` — adaptive red team
- `control-isolate` — test a guardrail API
- `control-bench` — A/B/C a control inside a benchmark

Skills follow the standard `SKILL.md` format, so any compatible harness can load them;
no harness, no problem — every step is plain CLI (next).

### Run a skill manually (app-eval example)
```bash
cd skills/app-eval
cp env.example .env && $EDITOR .env          # TARGET_URL/KEY, JUDGE_BASE_URL/KEY/MODEL
bash install_dependencies.sh                 # promptfoo, air-gapped
set -a; . .env; set +a
npx promptfoo eval -c promptfooconfig.yaml --output results.json --filter-sample 30
python lib/summarize.py results.json         # F1 / recall / FPR / ASR + per-status histogram
```
The corpus is **bundled** — no build step. (Web UI instead? use `promptfooconfig.browser.yaml`.)

### Try it with zero API keys (local mock gateway)
[`targets/proxy/`](targets/proxy/) is a local LiteLLM gateway with mock target models, a
mock guardrail, and LiteLLM's bundled content-filter — exercise the full pipeline offline:
```bash
bash targets/proxy/start_proxy.sh &          # gateway on :4000
# point a skill's TARGET_URL / GUARDRAIL_URL at the mock and run as above
```
Add real models by editing `targets/proxy/litellm_config.yaml` — LiteLLM fronts **any
provider** (OpenAI, Anthropic, Google, Bedrock, your own gateway, …), so a skill points
at one OpenAI-compatible endpoint regardless of backend; put your provider key in `.env`
(examples included). The test apps ([AIGoat](targets/aigoat/), [DVAA](targets/dvaa/)) route
their models through this gateway, so a guardrail can be toggled by name and A/B/C tested.

### control-bench (separate venv)
```bash
uv venv .venv-inspect
.venv-inspect/bin/python -m pip install inspect_ai 'inspect_evals[agentdojo]'
SHIM_GATEWAY_URL=http://localhost:4000 SHIM_GATEWAY_KEY=$KEY \
  python skills/control-bench/injection_shim.py --arms arms.json --base-port 8901
# prints the env + `inspect eval inspect_evals/<task> --model "openai-api/...,..."` line
```

---

## Tests

```bash
bash scripts/run_tests.sh     # Node + Python unit tests + no-drift check, all offline
bash e2e/run_e2e.sh all       # real-model end-to-end for all four skills (any provider key in .env, via LiteLLM)
```
CI (`.github/workflows/ci.yml`) runs the unit tests, the no-drift check, and validates
every promptfoo config.

## License

MIT. See [`LICENSE`](LICENSE). Bundled datasets retain their original licenses (per-case
`license` metadata + `tools/corpus/sources/NOTICE`): AdvBench / CyberSecEval / PromptInject /
SafeMTData (MIT), XSTest (CC-BY-4.0). Non-redistributable sources (MHJ — CC-BY-NC) are not
bundled.
