# Evaluating the ai-security-sdlc plugins — experiment plan

_Status: draft v1 · 2026-08-16 · owner: Wade_

This plan turns `ai-security-evals` into the place where we **measure** whether the plugins in
[`ai-security-sdlc`](https://github.com/wtcooper/ai-security-sdlc) actually work: does a rule set make
generated code more secure, does the pentest skill catch what it should, do the scanners find known
vulnerabilities, do the asset scanners separate malicious from benign. Every section below is a
self-contained experiment design; the cross-cutting rules in §2 apply to all of them.

The repo already ships one harness of this kind — [`skills/control-codegen`](../../skills/control-codegen/SKILL.md)
(git-branch A/B/C for rule-file efficacy). This plan **extends** it rather than replacing it, and adds
sibling harnesses for the other plugins.

---

## 1. What we are evaluating

| sdlc plugin | Skills | Question the eval must answer | Eval type | Harness (this repo) |
|---|---|---|---|---|
| **secure-plan** | `security-profile`, `secure-build-plan` (+ Project CodeGuard rules) | Does having rules / a Secure Build Plan present at build time reduce critical/high vulns in the code an agent writes — without breaking functionality? | Controlled A/B/C, generation | `control-codegen` (extend) |
| **code-scan** | `scan-code` (LLM), `codeql-ci` + `codeql-report` | Recall / precision of each scanner (and their union) on code with known vulnerabilities; what does the LLM scanner catch that CodeQL misses and vice versa? | Detection benchmark | **new** `tool-codescan` |
| **pentest** | `pentest-app` (Strix) | Recall of known vulns with oracle-verified PoCs, false-positive rate, cost/time, black-box | Detection benchmark (dynamic) | **new** `tool-pentest` |
| **asset-scan** | `scan-mcp`, `scan-skill`, `scan-model` | TPR / FPR / judge nondeterminism on labeled malicious + benign assets | Classification benchmark | **new** `tool-assetscan` |
| **remediate** | `fix-findings` | Do fixes make the exploit stop working *and* keep tests green; how often does "scanner says fixed" ≠ fixed | Repair benchmark | **new** `tool-remediate` |
| **ai-evals / ai-redteam** | `eval-baseline`, `eval-security`, `redteam-app` | Do the profile-driven configs the skills write actually surface planted weaknesses in a known-vulnerable LLM app? | Meta-eval | existing `app-eval` / `app-redteam` / `control-bench` targets (DVAA/AIGoat) |

Not in scope: evaluating the underlying OSS tools' *features*; we measure the tool **as our skill drives it**
(profile → config → run → SARIF), because that end-to-end path is what a user gets.

---

## 2. Cross-cutting method (applies to every harness)

### 2.1 Clean starting state and no leakage
- **Ephemeral repos via `gh`.** Every experiment gets a fresh, empty GitHub repo
  (`gh repo create <org>/eval-<harness>-<spec>-<date> --private`), so CodeQL/code-scanning, Actions and
  branch history are pristine and there is no chance the agent reads prior arms' code, results or notes.
  Delete or archive at the end (`gh repo archive`), keep the results bundle in `.evals/`.
- **Immutable `starting-state` branch + `starting-state-locked` tag.** Everything held constant is committed
  once; every arm branches from it. Verify `git rev-parse starting-state == starting-state-locked` before each
  arm (already the `control-codegen` convention).
- **What the agent must never see** in its working tree or context: scanner rules, exploit scripts, functional
  test oracles, other arms' branches, the eval manifest, this document. Oracles live in the eval repo, not the
  target repo. Runs are done from a fresh agent session per sample (no memory/`~/.claude` project state
  carried over; use a throwaway `HOME`/config dir or the container image).
- **Contamination controls for public benchmarks** (models memorize old test apps):
  1. Prefer **post-cutoff** material (rolling CVE sets, 2026-dated challenges) — record the model's cutoff.
  2. **Canary recall probe** before a run: ask the same model, cold, "list the vulnerabilities in `<app/CVE>`" and
     "what is the flag route in `<challenge>`". If it recites the answer, mark the target `contaminated` and either
     drop it or report it in a separate stratum.
  3. **Mutate** what we reuse: rename apps/routes/params/branding, change ports/DB names, regenerate flags per
     build, transplant a bug into a different codebase; keep a paired original ↔ mutant so we can quantify the
     memorization delta.
  4. **Trace audit**: grep agent transcripts for the target's canonical name or a canonical payload appearing
     *before* any recon — evidence of recall, not discovery.
- **Scorer independence:** any LLM used to score (LLM code review, PoC validator, judge) is a **different model
  family** from the one under test (self-preference bias), pinned model + temperature 0 + fixed rubric, and
  repeated ≥3× with majority vote.

### 2.2 Replicates and statistics
- Agent runs are nondeterministic; **never conclude from n=1**. Defaults: k ≥ 10 samples per arm for
  generation experiments; k = 3–5 repeats for scanner runs that involve an LLM (report flip rate / κ).
- Design is **paired** wherever possible (same spec/target, arms differ by one variable). Analyze paired
  differences: bootstrap CIs (B=10k) on per-task deltas; McNemar for paired binary outcomes
  (vuln present/absent, found/not-found); Wilcoxon on per-scenario rates; mixed-effects logistic
  (arm fixed; scenario/framework random) when we pool across specs. Report effect sizes + CIs, not just p.
- Power rule of thumb: detecting a 10-point absolute change in a ~40% binary outcome needs on the order of
  200–400 paired task-runs — plan scenario × k accordingly, and power on the scenario cluster, not raw runs.
- Report **cost and time** alongside every quality metric (tokens, $ per run, wall-clock, $ per verified finding).

### 2.3 Common results contract
Every harness writes an experiment folder `.evals/<harness>/<label>_<date>/` with:
- `manifest.json` — tool + version, model(s) + temperature, benchmark + version/commit, cutoff date, arms, k,
  scorer config, contamination flags, cost. (Extend `control-codegen/new_experiment.sh` into a shared
  `tools/new_experiment.sh`.)
- `results/<arm-or-target>/…` — raw tool output (SARIF/JSON) unmodified.
- `findings.jsonl` — normalized rows: `{run, arm, target, cwe, file, line, severity, confidence, oracle_confirmed, tool}`.
- `summary.md` — the numbers, CIs, and the plots.
A shared `tools/evalstats.py` computes the paired stats from `findings.jsonl` so every harness reports the same way.

### 2.4 Matching rules for detection benchmarks
A finding matches ground truth when **CWE family matches** (map to top-level CWE) **and** location matches at
the granularity the benchmark provides (file → function → line ± 5). Report recall at each granularity. Findings
with no ground-truth match are "unlabeled" — a sample (≥30, or all if fewer) is manually adjudicated and
re-labeled TP/FP; report **precision as a lower bound** and **adjudicated precision**. Use a metric that
penalizes FPs (F1 or F0.5) plus a severity-weighted score; never recall alone.

---

## 3. secure-plan — do rules / Secure Build Plans make generated code more secure?

**Harness:** extend `control-codegen`. Its design (read-only `starting-state` = spec + fixed build prompt; one
experiment branch per arm × sample; held-constant scoring ensemble; per-CWE + correct-AND-secure metrics) is
exactly the design this plan wants. Changes below.

### 3.1 Arms (the single independent variable = what is present before the agent starts)
| Arm | Working tree at build start | What it tests |
|---|---|---|
| **A** none | spec + build prompt | baseline |
| **B** CodeGuard, as installed | A + Project CodeGuard plugin/rules at the agent's path (Claude Code: plugin install → `codeguard-security`; Cursor: `.cursor/rules/*.mdc`; Codex: `AGENTS.md`) — the **whole** rule set, exactly as a real user installs it | "install the plugin" effect (generic, just-in-time rules) |
| **C** Secure Build Plan | A + `.ai-security/profile.md` + `.ai-security/plans/<feature>-sbp.md` produced by our `secure-build-plan` skill for this spec (rules cited by id, no rule bodies) — generated **once**, from the spec only, committed on the arm branch | our plugin's actual output |
| **D** SBP + CodeGuard | B + C | the recommended real-world configuration |
| (E) oracle-specific | A + a hand-written per-CWE rule naming the exact sinks (`control-codegen`'s condition C) | **upper bound only** — leaks the answer; report separately, never as "the effect" |

Run A vs D as the headline; B and C decompose it. Literature says generic guidance moves totals little
(Broken by Default 2026: ~4-pt reduction from explicit instructions) while task-specific guidance is the
lever — so an A-vs-B-only design risks a false null; always include C/D.

**Leakage rule for C/D:** the SBP is written by the `secure-build-plan` skill from spec + profile with a model
that has **not** seen the scanner rules or exploit tests; the SBP file is committed as the arm's only pre-build
diff; the SBP author session is discarded. If the SBP happens to enumerate the exact planted CWEs, that is the
intervention working, not leakage — the leakage boundary is oracles/tests, not security requirements.

### 3.2 Specs
1. **Bundled `control-codegen/specs/01–05`** (sink-dense, stack pinned) — interpretable, real rule files, real
   agentic loop. Keep as first-line.
2. **BaxBench scenarios (392 = 28 × 14 frameworks)** — expert functional tests + black-box exploits already
   exist, and `--safety_prompt none|generic|specific` maps onto A/B/E. Use "generate externally, evaluate
   in-harness": our agent + our rules build the app on the branch, we drop the artifact into BaxBench's
   `results/...` layout and run only `--mode test` + `--mode evaluate`. **Correct & Secure** is the metric.
3. **AutoBaxBench / AutoBaxBuilder-generated scenarios (40 × 14 = 560; or generate fresh ones)** — for
   contamination-free replication once the effect is seen on 1–2. Generate a private batch and never publish
   the scenarios we score on.
4. **Modern-stack spec (new, ours):** one spec in Wade's default stack (Next.js 16 App Router + server actions
   + Drizzle/Neon + Clerk) — the stack the plugins are actually used with; RSC/server-action authz, IDOR,
   SSRF-in-fetch, unsafe redirects, secrets in client bundles. Needs a hand-written probe set (see 3.4).

Spec authoring rules stay as-is: rich problem statement, business functionality and **acceptance criteria**;
pinned stack/ports/storage; **no security implementation detail**; nothing that names a CWE.

### 3.3 Scoring ensemble (held constant across arms, run on every sample)
1. **CodeQL via push** — each sample branch is pushed to the ephemeral repo, CodeQL advanced setup (our
   `codeql-ci` skill, `security-extended`) runs on push, `codeql-report` pulls alerts by branch ref
   (`-f ref=refs/heads/exp/<arm>/sample<i>`). Deterministic; count critical/high by rule.
2. **Dynamic exploit oracle** — BaxBench exploits (specs from 3.2.2/3), or hand-written probes for bundled
   specs (each spec already lists its sink families; write ~5–10 curl/pytest probes per spec: path escape,
   SSRF to `169.254.169.254`/loopback, IDOR across two users, zip-slip archive, formula injection, mass
   assignment of `price`, etc.). **Exploitable** = highest-confidence signal.
3. **LLM review** — our `scan-code` skill in standalone mode (`run_scan.py`), model from a *different family*
   than the generator, T=0, 3 runs → majority; gives per-CWE coverage CodeQL misses (LLM-tool-arg sinks etc.).
4. **Functional acceptance** — the spec's acceptance tests (BaxBench functional tests, or a fixed pytest/newman
   suite per bundled spec kept in the eval repo). Required to compute **correct-AND-secure**.
5. Optional deterministic companions kept identical across arms: Semgrep (taint/Pro rules only — free registry
   caught 0 planted spec-01 sinks), Bandit/gosec, ASan/UBSan+fuzz for spec-05.

### 3.4 Metrics (headline first)
- **Per-CWE-class critical/high count** per sample (CodeQL + confirmed LLM findings), A→D delta, mean ± CI.
- **Exploitable count** (dynamic oracle) and **any-exploitable rate** per arm (paired McNemar).
- **Correct-AND-secure rate** — an arm that "gets secure" by failing acceptance criteria is a false win; always
  show security and correctness side by side.
- Secondary: severity-weighted score, total findings, tokens/$/time per build, % builds that failed.
- Sanity check before scaling k: `git diff exp/A/sample1 exp/D/sample1 -- . ':!CLAUDE.md' ':!.ai-security'`
  must be non-trivial, else the agent ignored the rules (wrong path for that agent).

### 3.5 Procedure (per spec)
```
gh repo create <org>/eval-codegen-<spec>-<date> --private --clone
# starting-state: spec (+ optional pre-generated plan/tasks), build-prompt.md; tag starting-state-locked
# arm branches: exp/{A,B,C,D}/sample<i>  ← only pre-build diff = rules/SBP files
# per sample: fresh agent session, build-prompt.md, iterate to acceptance; commit; push branch
# CodeQL runs on push; collect via codeql-report; run probes + acceptance in Docker; run scan-code x3
# tools/evalstats.py .evals/control-codegen/<exp>/findings.jsonl → summary.md
```
Do the two-armed A vs D at k=10 on spec-01 first (cheap "will I even see a signal?"), then all arms, then
BaxBench replication.

### 3.6 Known gaps to close in the harness
- `control-codegen` today assumes CLAUDE.md-style rule files; add the "install the real CodeGuard plugin" arm
  and the SBP-generation step (call our `secure-build-plan` skill against the spec, capture its output as the
  arm file). Add a `push + CodeQL + codeql-report` scoring stage and the probe suites for specs 01–05.
- Project CodeGuard has published **no efficacy data** (checked repo + site, Aug 2026) — this experiment is a
  genuine contribution; design it to be publishable (methods, CIs, code).

---

## 4. code-scan — recall/precision of `scan-code` (LLM) and CodeQL

**Question:** on code with known vulnerabilities, what fraction does each scanner find (recall), how much
noise (precision), and what is the union/complement (the repo's thesis is that the LLM scan catches classes
CodeQL cannot, e.g. LLM tool-argument taint). Also: LLM run-to-run variance.

### 4.1 Targets (2026 picks; old goats excluded as saturated)
| Tier | Target | Why | Langs | Notes |
|---|---|---|---|---|
| **1 — held-out real CVEs** | **LiveCVEBench / CVE-Factory** (Feb 2026, rolling, MIT; 190 tasks, 153 repos, 14 langs, incl. AI-tooling CVEs; Docker env, vuln commit + fix, validated exploit) | post-cutoff slice → lowest contamination; multi-language | many | Use only entries newer than the scanned model's cutoff. Scan the **vulnerable** snapshot for recall, the **fixed** snapshot for precision (any alert at the fixed location = FP). |
| **1 — labeled TP + FP traps** | **RealVuln v1.0** (Apr 2026; 26 Python web repos, 796 hand labels: 676 TP + **120 FP traps**, file loc + CWE + rationale) | the only Python set with FP traps; already ranks Semgrep/Snyk/Sonar vs Claude/SecLab | Python | Repos are public goats → **high** memorization risk; run canary probes and a mutated variant (rename modules/routes/identifiers) as a paired stratum. v2 promises post-cutoff repos — adopt when out. |
| **1 — CodeQL-native comparison** | **CWE-Bench-Java** (IRIS; 120 real CVEs, 4 CWEs: path traversal, cmd inj, XSS, code inj; buggy + fixed sources, build scripts) | published CodeQL baseline (27/120) vs LLM-assisted (55/120) — direct comparability | Java | Med-high contamination; still the cleanest CodeQL-vs-LLM apples-to-apples. |
| **2 — memory-safety bulk** | **CyberGym-E2E** (Jun 2026, 920 vulns/139 OSS-Fuzz projects, PoC) or **ARVO** (6,138 pairs) subset of ~100 | vulnerable ↔ fixed pairs with crash PoC | C/C++ | For CodeQL C++ + LLM scan; sample post-2025 entries. |
| **2 — anti-memorization design** | **ZeroDayBench** (Mar 2026, 22 vulns transplanted into other repos) and the **RustMizan** paired-mutant idea | measures recall when the code is OOD by construction | multi / Rust | Small; use the *technique* — transplant 10–20 known bugs from LiveCVEBench into unrelated repos ourselves. |
| **3 — fresh, never-published code (ours)** | The apps generated in §3 (arm A samples), labeled by the **dynamic oracle** (exploit succeeded ⇒ vuln at that sink) | zero contamination; exercises the LLM-tool-sink classes; ties the two harnesses together | Py/Node/Go/C | Labels are sink-level, not line-level; use CWE + file matching. |
| **3 — AI-app specific** | **DVAA** (17 agents, MCP/A2A, 22 challenges), **DVMCP** (10 MCP challenges), our own `testbed/sample-app` planted path traversal via tool arg | the "CodeQL has no LLM taint source" gap | Py | Challenge-level ground truth only; hide `solutions/`. |
| Smoke only | XBOW validation-benchmarks (self-declared saturated), OWASP Benchmark v1.2, Juliet, NodeGoat/WebGoat/Juice Shop | plumbing tests; **never** in headline numbers | | |

### 4.2 Design
- Fixed target set + version pins; one ephemeral repo per benchmark (import the snapshot, push, CodeQL on
  push; `scan-code` locally with `run_scan.py` and in agent mode).
- Arms are **scanners**, not treatments: `codeql` (security-extended), `scan-code` (model M, T=0) × 3 repeats,
  `union`. Optional model sweep (local `gemma4`/`qwen3.5` via the gateway vs a frontier model) — the skill is
  model-agnostic and users will ask "which model is good enough".
- Matching per §2.4; adjudicate unmatched findings; report recall / precision / F1 / severity-weighted, per
  CWE family, per language, per benchmark tier, plus **complement analysis** (found by LLM only / CodeQL only /
  both) and **run-to-run flip rate** for `scan-code`.
- Contamination stratum: report each metric on `clean` vs `contaminated` (canary probe positive) targets and
  on original vs mutated pairs.
- Cost: tokens and $ per KLOC scanned; wall-clock.

### 4.3 Deliverables
- `skills/tool-codescan/`: SKILL.md (Plan→Run→Analyze), `fetch_targets.sh` (LiveCVEBench / RealVuln /
  CWE-Bench-Java at pinned commits), `mutate.py` (identifier/route renaming with a rename map for label
  translation), `match.py` (SARIF ↔ ground truth), `canary_probe.py`.

---

## 5. pentest — does `pentest-app` (Strix) find what it should?

**Question:** black-box, from a profile + RoE written by our skill, what fraction of known vulnerabilities does
Strix report **with an oracle-confirmed PoC**, how many findings are unreproducible (FP), at what cost/time.

### 5.1 Targets
| Tier | Target | Why | Ground truth / oracle | Contamination |
|---|---|---|---|---|
| **1 — real CVEs with graders** | **CVE-Bench v2.1.0** (UIUC; 40 web-app CVEs CVSS≥9, Docker; grader checks DoS / file access / RCE / DB read/mod / admin login / privesc / outbound; Inspect port exists) | the only web set with a built-in exploit **oracle**; zero-day and one-day modes | grader | Medium (2024 CVEs) — treat as ceiling; run **zero-day mode**, canary-probe each CVE |
| **1 — post-cutoff CVEs (ours)** | **Vulhub** slice: environments added after the model's cutoff (Vulhub is at ~561 compose envs, updated Jun 2026, with CVE-2026-* entries e.g. WordPress REST batch RCE, Spring path traversal, Fastjson jar-protocol RCE) | fresh, real, dockerized | we write a per-env oracle: canary file / callback URL / DB row / marker header; require Strix's PoC to trigger it | Low for 2026 CVEs; READMEs contain PoCs → hide them from the agent, mutate ports/hostnames |
| **1 — modern-stack baseline** | **Duck Store** (Escape, 2026; React + FastAPI + GraphQL, 20 documented vulns: logic, IDOR, XSS, sandboxed SQLi, SSRF) | Strix has a **published number** here (1/20, 0 FP, 2h on DeepSeek v3.2 vs Escape 15/20, PentAGI 9/20, Shannon 6/20) — rerun with our model to separate orchestration from model | vendor list; we script 20 checks | Low-med; source availability unverified — may be hosted-only |
| **2 — new open real-app range** | **AgentCyberRange** (Jun 2026; 110 vulns across 15 real web apps + 8 ranges) | most promising *new open* real-app set | its verification toolchain | verify repo/docker availability |
| **2 — mutated CTF flags** | **XBOW validation-benchmarks (104), forked and re-skinned** (routes, branding, params, ports, schema, flag regex; flags injected per build) | XBOW's own README calls it saturated; Strix's harness already speaks it, so a mutated fork is cheap and gives paired original↔mutant memorization deltas | flag capture | High original / low mutant |
| **2 — AI-app** | **DVMCP**, **AIGoat** (AISecurityConsortium), **DVAA**, testbed sample app | AI-layer overlap with `redteam-app`; canary secrets in system prompt / RAG / tool tokens | canary exfil | Med; hide solutions |
| Paid / reference | HTB AI Range (private, refreshed), UK AISI / OpenAI ranges (not accessible) | reference numbers only | | |
| Excluded from headline | plain Juice Shop, DVWA, WebGoat, bWAPP, Mutillidae, NodeGoat, crAPI/VAmPI/DVGA un-mutated | memorized | | smoke/plumbing only |

### 5.2 Design
- **Black-box only** for DAST claims: target is a URL (Docker network), no source mount (Strix mounts a local
  dir writable — never do that in the eval). White-box runs, if any, are a separate stratum.
- Fixed Strix version, `--scan-mode` (start `quick`, then `standard`), `--max-budget`, model via gateway,
  instructions file produced by **our skill from a profile** we write per target (the profile is part of the
  system under test). k = 3 runs per target (Strix is highly nondeterministic).
- **Zero-day vs one-day**: run without hints; optionally a one-day arm where the profile names the vuln class
  (CVE-Bench 13%→25%, AgentCyberRange 16%→33% show hints double scores) — report separately.
- Scoring: **recall@vuln = oracle-confirmed** (flag/canary/callback/DB/file), never self-report;
  **precision** = findings an independent validator (scripted oracle where possible; else a different-family
  LLM validator that must *reproduce* the PoC) confirms; cost per verified finding, time-to-first-finding,
  wall-clock, tokens; SARIF quality (does the finding carry a working PoC).
- Contamination: canary probe per target; trace audit for known payloads before recon; original vs mutant
  paired delta on the XBEN fork.

### 5.3 Deliverables
- `skills/tool-pentest/`: SKILL.md, `targets/` (compose wrappers: cve-bench subset, vulhub post-cutoff list
  with `oracle.sh` per env, xben-mutator, duck-store checks), `validate.py` (rerun PoCs from
  `vulnerabilities.json` against the oracle), profile templates per target.

---

## 6. asset-scan — `scan-mcp`, `scan-skill`, `scan-model`

**Question:** TPR / FPR / severity calibration on labeled positives and negatives, and how much the LLM-judge
component flips between runs (we already saw `skill-scan` flip clean→flag→clean on an unchanged skill).

Common design: positives + negatives + **held-out mutated positives that Cisco's YARA rules cannot match**
(verify: `yara -r <rules> <sample>` → 0 hits before inclusion) + vendor fixtures **excluded** (they are total
contamination). Configs: static-only, LLM-judge-only, combined; k=5 repeats at default T and T=0; report
TPR/FPR with Wilson CIs, per-run flip rate, Fleiss' κ across runs, severity Krippendorff α. Treat κ<0.6 as
"unusable for CI gating" and say so in the skill docs.

### 6.1 scan-mcp
| Set | Source | Size / labels | Notes |
|---|---|---|---|
| Positives | **MCPTox** (AAAI'26; 1,312 poisoned tool descriptions over 45 real servers, 10 risk categories) + paired originals as negatives | pos + matched neg | templated phrasing may overlap YARA (`tool_poisoning`, `coercive_injection`) — that's fine for "as shipped" TPR; use mutation set for held-out |
| Positives | **MCPSecBench** playground servers (17 attack types), **MCP-SafetyBench** (245 cases; host-side ones out of scope for static) | hand-built | source-level malicious servers |
| Positives (real) | postmark-mcp v1.0.16 (BCC exfil), fake Oura MCP (Feb 2026), Smithery path traversal | handful | pull from npm/mirrors |
| Negatives | random sample n≥300 of official MCP registry (~37k) / Glama (~72k) servers with high installs and no prior scanner hits; manually adjudicate any positive (2 reviewers, κ) | | FPR |
| Reference | **MCPZoo** (Jul 2026; 113,927 servers, 8 scanners incl. Cisco mcp-scanner; avg scanner precision 45.5%, pairwise Jaccard 15.7%, recall on CVE set 24% avg); AppSecSanta audit (Cisco YARA ~78% FP on 27 hits, e.g. `coercive_injection_generic` on "You MUST call this tool first") | | our FPR should be compared to these |
| Smoke only | Invariant mcp-injection-experiments, DVMCP, Cisco `tests/threat_files` | | canonical → memorized |
| Held-out | 200 benign tool JSONs → inject 5 payload classes (exfil, shadowing, coercion, rug-pull time bomb, hidden HTML/unicode) × ≥3 LLM-paraphrased surface forms; keep parent↔mutant pairs; 0 YARA hits | | measures LLM-judge value beyond YARA |

### 6.2 scan-skill
| Set | Source | Size / labels | Notes |
|---|---|---|---|
| Positives + negatives | **MalSkillBench** (Jun 2026, CC0; 3,944 malicious incl. 703 in-the-wild + 4,000 matched benign, sandbox-verified) — verify release | best labeled corpus | reported detectors collapse on prompt-injection class |
| Positives + negatives | **SkillSieve** 400 labeled (89 mal / 311 benign, 7 attack types, stealth 1–5) from a 49,592 ClawHub snapshot; **SkillVetBench** 100 (78/22) with published baselines (VirusTotal 33–46%, ClawScan 48–56%, SkillSieve 82–85%; judge variance 35–95% across LLMs) | | direct comparability |
| Positives | Snyk **ToxicSkills** goof samples (~9); ClawHavoc IOC-matched skills (341→1,184) if a snapshot is available | small | |
| Negatives | `anthropics/skills`, top-500 by installs on skills.sh with no scanner hits, and **our own 13 skills** (already remediated to clean — a regression set) | | |
| Reference | "Elementary, My Dear Watson" (Mar 2026) reports Cisco skill-scanner F1 0.88 / FPR 0.23 (verify in PDF); "Seeing Is Not Screening" (Jun 2026) multimodal hidden-instruction evasion set | | |
| Held-out | 150 benign skills → LLM-paraphrased PI in prose, benign-looking `scripts/*.py` with staged fetch to a *local* server, unicode-tag / HTML-comment / zero-width smuggling, prerequisites-style social engineering; 0 YARA hits; hash-dedupe vs vendor evals | | |

### 6.3 scan-model
| Set | Source | Size / labels | Notes |
|---|---|---|---|
| Positives + negatives | **PickleBall** artifact (CCS'25, MIT; 252 benign HF + 84 malicious); **SafePickle** (Feb 2026, CC BY-NC-ND; 648 benign + 79 malicious HF pickles + 9 evasive + 6 real incl. nullifAI; baselines: PickleScan TPR 97%/TNR 0%, ModelScan 100%/0%, Fickling 57/86) | labeled | core |
| Evasion | **ShadowPickle** (Jul 2026; 3,000 mal + 3,000 benign; PickleScan/ModelScan recall 0.0, Fickling 1.0); picklescan CVE PoCs (CVE-2025-1716, -10155/6/7, -71360, -71376, CVE-2026-53875); nullifAI 7z carrier | | how much of ModelAudit's value is beyond picklescan |
| Positives (non-pickle) | **MalHug** metadata (91 malicious HF models incl. **15 Keras Lambda**) — files not redistributed, locate by id | | Keras/ONNX/GGUF coverage |
| Negatives | HF top-1k by likes per format (pickle/pt/safetensors/GGUF/ONNX/Keras) after HF Guardian clean | | FPR per format |
| Held-out | `fickling.injection` / `__reduce__` of *harmless* payloads (print, tempfile write, socket to localhost) into benign torch/joblib/sklearn pickles; carriers: raw, torch zip, 7z, ext mismatch, nested, base64+exec, idlelib gadget; plus Keras Lambda / ONNX custom-op / GGUF template samples | | **scan-only, container, no network, never `pickle.load`** |
| `hf_harvest` caveat | JFrog: ~96% of HF "unsafe" flags are FPs — HF flags are **not** ground truth; evaluate `hf_harvest.py`'s summarization against PickleBall/SafePickle labels for the same repo ids | | |

### 6.4 Deliverables
- `skills/tool-assetscan/`: SKILL.md, `fetch_sets.sh` (pinned), `mutate_{mcp,skill,pickle}.py`,
  `yara_filter.sh`, `score.py` (TPR/FPR/CI/κ), sandbox `Dockerfile` (no network) for the pickle work.

---

## 7. remediate — does `fix-findings` actually fix things?

**Question:** given SARIF from the scanners, do the fixes (a) make the exploit stop, (b) keep the functional
suite green, (c) add a regression test, and (d) how often does the scanner report "fixed" while the exploit
still works (scanner-gaming).

| Tier | Target | Oracle |
|---|---|---|
| 1 | **Vul4Py** (Aug 2026; 100 Python vulns / 60 CWEs, paired exploit + pytest oracles — the paired oracle rejected 15/119 exploit-only "fixes") | exploit fails **and** tests pass |
| 1 | **PatchEval** (ByteDance; 1,000 CVEs Go/JS/Py, 230 dockerized) — dockerized subset | security + functional tests in sandbox |
| 2 | **AutoPatchBench** (Meta, 136 C/C++ ARVO vulns) / **SEC-bench** | crash no longer reproduces + differential tests |
| 3 (closed loop, ours) | findings from §3 arm-A samples → `fix-findings` → re-run §3.3 ensemble (CodeQL + probes + acceptance) | exploitable count ↓, acceptance still passes, regression test present |

Metrics: fix rate (both oracles), exploit-only-fix rate (flag as failure), functional regressions introduced,
regression test added (yes/no, and does it fail on the pre-fix commit), scanner-says-fixed-but-exploit-works
rate, diff size, cost. Compare against "no-fix" and against a plain "ask the model to fix" baseline so we
measure what the skill's triage/regression steps add.

Deliverable: `skills/tool-remediate/` (SKILL.md, `fetch_targets.sh`, `verify_fix.sh` running both oracles).

---

## 8. ai-evals / ai-redteam — meta-eval (short)

These plugins wrap Promptfoo, which `app-eval` / `app-redteam` / `control-bench` already evaluate directly.
What is untested is our **profile → config** step. Design: point `security-profile` + `eval-security` +
`redteam-app` at a known-vulnerable LLM app with planted weaknesses (**DVAA**, **AIGoat**, `testbed/sample-app`
with the planted tool-arg path traversal, plus canary secrets in the system prompt/RAG), k=3, and score
whether the generated config surfaces each planted weakness (recall on planted list), the false-positive rate,
and whether a config written from a *thin* profile does worse than from a full one (the profile is the lever).
Reuse `targets/proxy` and the existing DVAA/AIGoat targets in this repo. No new harness needed beyond a
planted-weakness manifest per target.

---

## 9. Harness layout in this repo

```
skills/
  control-codegen/        (existing; add arms B/D, SBP step, CodeQL-on-push scorer, probe suites, modern-stack spec)
  tool-codescan/          (new)  scan-code + CodeQL recall/precision
  tool-pentest/           (new)  Strix recall/FP/cost with oracles
  tool-assetscan/         (new)  mcp / skill / model scanner TPR/FPR/κ
  tool-remediate/         (new)  fix-findings repair validity
tools/
  new_experiment.sh       (generalize from control-codegen; manifest schema shared)
  evalstats.py            (paired bootstrap / McNemar / Wilcoxon / mixed-effects; Wilson CIs; κ)
  canary_probe.py         (contamination probe + trace audit)
  ephemeral_repo.sh       (gh repo create/clone/push/archive; CodeQL workflow bootstrap via codeql-ci)
targets/                  (existing DVAA/AIGoat/proxy; add compose wrappers + oracles for pentest targets)
docs/plans/               (this plan; per-harness experiment writeups as they land)
```
Naming: `control-*` = "does a control change an outcome" (A/B); `tool-*` = "how good is a detection/repair
tool against ground truth". Each skill follows the repo's Plan → Run → Analyze SKILL.md convention and is
self-contained (its own `lib/` vendored via `tools/sync_skills.sh`).

---

## 10. Phasing

| Phase | Work | Output | Why first |
|---|---|---|---|
| **P0 (1–2 wk)** | Shared plumbing: `ephemeral_repo.sh`, generalized manifest, `evalstats.py`, `canary_probe.py`; CodeQL-on-push scoring stage | reusable spine | every harness needs it |
| **P1** | secure-plan: A vs D, spec-01, k=10; then B/C; probes for specs 01–04 | first efficacy numbers for CodeGuard/SBP | highest-value question; CodeGuard has no published efficacy data |
| **P2** | code-scan: LiveCVEBench post-cutoff slice + RealVuln (+ mutated) + CWE-Bench-Java; scan-code vs CodeQL vs union | complement analysis for the repo's core thesis | reuses P0 repos/CodeQL |
| **P3** | asset-scan: skill first (we already know it flips), then MCP, then model | TPR/FPR/κ, gating guidance | cheap, no agents to run |
| **P4** | pentest: CVE-Bench zero-day + Vulhub 2026 slice with oracles + Duck Store rerun | Strix recall/FP/cost | most infra-heavy |
| **P5** | remediate: Vul4Py + closed loop on P1 outputs | fix validity | depends on P1/P2 outputs |
| **P6** | BaxBench/AutoBaxBench replication of P1; modern-stack spec; meta-eval of ai-evals/redteam | robustness | after the effect is seen |

---

## 11. Risks and open questions
- **Cost.** k=10 × 4 arms × full app builds with a frontier model is real money; start with A vs D and one
  spec; use local models via the gateway for plumbing runs only (state which model produced any published number).
- **Contamination is the main validity threat** for every public benchmark here; the post-cutoff + canary +
  mutation trio is mandatory, and results must be reported per stratum.
- **Scorer bias:** CodeQL is deterministic but blind to LLM sinks; the LLM reviewer is broad but noisy — hence
  the ensemble and the dynamic oracle as tie-breaker. Never let a single scanner be the headline.
- **Unverified items to confirm before relying on them:** MalSkillBench public release; Duck Store source
  availability; AgentCyberRange repo/docker; ExploitBench; RealVuln v2 timing; "Watson" paper's Cisco
  skill-scanner numbers; MCPTox repo URL.
- **Ethics/legal:** all pentest targets are self-hosted in Docker; asset-scan positives are handled scan-only
  in a no-network container; nothing is run against third-party systems.
- **Open:** do we want the modern-stack (Next.js/Drizzle/Clerk) spec in P1 or P6? Which agent(s) beyond
  Claude Code (Codex, Cursor) do we commit to in P1?

---

## Appendix A — benchmark catalog (Aug 2026)

**Code scanners:** LiveCVEBench/CVE-Factory (livecvebench.github.io; github.com/livecvebench/CVE-Factory) ·
RealVuln (github.com/kolega-ai/Real-Vuln-Benchmark) · CWE-Bench-Java (github.com/iris-sast/cwe-bench-java) ·
CyberGym-E2E (github.com/sunblaze-ucb/cybergym-e2e) · ARVO (arxiv 2408.02153) · ZeroDayBench (arxiv 2603.02297) ·
RustMizan (arxiv 2607.04729) · SecVulEval (github.com/basimbd/secvuleval) · CASTLE (github.com/CASTLE-Benchmark) ·
SecLLMHolmes · PrimeVul (legacy) · OWASP BenchmarkPython (github.com/OWASP-Benchmark/BenchmarkPython, synthetic).

**Codegen / rules:** BaxBench (baxbench.com; github.com/logic-star-ai/baxbench) · AutoBaxBuilder / AutoBaxBench
(github.com/eth-sri/AutoBaxBuilder) · SecureAgentBench (arxiv 2509.22097) · SecRepoBench (github.com/ai-sec-lab/SecRepoBench) ·
A.S.E (github.com/Tencent/AICGSecEval) · SecCodePLT · CWEval · SecCodeBench (github.com/alibaba/sec-code-bench) · DualGauge ·
Broken by Default (arxiv 2604.05292) · How Secure is Secure Code Generation? (arxiv 2601.07084) · Project CodeGuard
(github.com/cosai-oasis/project-codeguard — no efficacy data) · Wiz secure-rules-files.

**Pentest:** CVE-Bench (github.com/uiuc-kang-lab/cve-bench; Inspect port in inspect_evals / usnistgov/caisi-cyber-evals) ·
Vulhub (github.com/vulhub/vulhub, environments.toml) · Duck Store (escape.tech/blog/duck-store-vulnerable-app) ·
AgentCyberRange (arxiv 2606.14295) · BountyBench (bountybench.github.io) · XBOW validation-benchmarks (saturated) ·
Strix benchmarks (github.com/usestrix/strix/tree/main/benchmarks) · Escape comparison (escape.tech/blog/benchmarking-agentic-ai-pentesting-tools) ·
DVMCP (github.com/harishsg993010/damn-vulnerable-MCP-server) · AIGoat (github.com/AISecurityConsortium/AIGoat) ·
DVAA (github.com/opena2a-org/damn-vulnerable-ai-agent) · rsc-vulnerabilities (github.com/EvtDanya/rsc-vulnerabilities) ·
Revelio post-cutoff method (arxiv 2606.22263) · MindFort NexBench, ARTEMIS (scoring references).

**Asset scanners:** MCPTox (arxiv 2508.14925) · MCP-SafetyBench (github.com/xjzzzzzzzz/MCPSafety) · MCPSecBench
(github.com/AIS2Lab/MCPSecBench) · MCPZoo (arxiv 2607.11086) · AppSecSanta MCP audit · MalSkillBench (arxiv 2606.07131) ·
SkillSieve (github.com/xiaohou521/skillsieve) · SkillVetBench (github.com/supreme-lab/SkillVetBench) · ToxicSkills goof
(github.com/snyk-labs/toxicskills-goof) · awesome-agent-skills-security (github.com/LLMSecurity) · PickleBall
(zenodo 16974645; github.com/columbia/pickleball) · SafePickle (arxiv 2602.19818) · ShadowPickle (arxiv 2607.17503) ·
MalHug (github.com/security-pride/MalHug) · picklescan CVEs 2025–26 · ModelAudit (github.com/promptfoo/modelaudit).

**Remediation:** Vul4Py (arxiv 2608.00692) · PatchEval (github.com/bytedance/PatchEval) · AutoPatchBench (Meta) ·
SEC-bench / SEC-bench Pro · CyberGym-E2E · VulnRepairEval.

**Method:** Adding Error Bars to Evals (Anthropic 2024) · Evaluation of LLMs Should Not Ignore Non-Determinism
(NAACL'25) · self-preference bias (arxiv 2509.26600) · cost-aware eval (arxiv 2607.15263).
