# Implementation plan — building out the sdlc plugin evaluation design

_Status: v1 · 2026-08-16 · companion to [sdlc-plugin-evaluation-plan.md](sdlc-plugin-evaluation-plan.md) (the design doc). Section refs (§) point there._

## Context

[sdlc-plugin-evaluation-plan.md](sdlc-plugin-evaluation-plan.md) (the **design doc**) specifies six experiments that measure whether the `ai-security-sdlc` plugins work. It is a research design, not a build plan. This plan is the **build plan**: what to create in this repo, in what order, so each experiment in the design doc can actually be run. Decisions taken with the user (2026-08-16):

- Scope: **everything end to end** (P0–P6), P0/P1 in full detail, P2–P6 as concrete task lists that reuse the P0 spine.
- Ephemeral eval repos are **public** GitHub repos (CodeQL is free only on public repos; the specs are already public here; archive at end).
- P1 coding agent: **Claude Code only** (Codex/Cursor deferred to P6).
- This plan is committed as `docs/plans/sdlc-eval-implementation-plan.md`, companion to the design doc.

### What the repo has today (verified)
- `skills/control-codegen/` = `SKILL.md`, `build-prompt.md`, `new_experiment.sh` (a fork of `tools/new_experiment.sh` with a different CLI + manifest), `specs/spec-01..05`. **No `lib/`, no scripts, no tests, not in `sync_skills.sh`.** Scoring is prose + an inline Semgrep-only SARIF heredoc.
- `tools/` = source of truth vendored into skills by `tools/sync_skills.sh`; CI (`.github/workflows/ci.yml`) runs `pytest tools/tests`, sync-and-`git diff --exit-code`, and `scripts/check_independence.sh` (no skill may reference `../..`, sibling skills, `tools/`, `targets/`, absolute paths).
- **Nothing exists** for: stats (no scipy/statsmodels; numpy+pandas+openai are transitively in `.venv`), SARIF→findings normalization, `gh`/CodeQL, contamination probes, `testbed/`, `tool-*` skills. `.evals/` is gitignored.
- Sibling repo `~/Code/GitWCoop/ai-security-sdlc` (system under test): `plugins/secure-plan/skills/{security-profile,secure-build-plan}` (with `scripts/find-codeguard.sh`, pins CodeGuard `v1.4.0`), `plugins/code-scan/skills/{scan-code (scripts/run_scan.py, to_sarif.py; env AISEC_GATEWAY_BASE_URL/AISEC_GATEWAY_API_KEY/AISEC_MODEL), codeql-ci (templates/codeql.yml, codeql-config.yml — triggers on `main` only), codeql-report}`, plus `pentest`, `asset-scan`, `remediate`, `ai-evals`, `ai-redteam`, `testbed/`.

### Deviations from / clarifications to the design doc (flagged for the user)
1. **Public not private repos** (design §2.1 says `--private`) — CodeQL cost. Nothing sensitive is pushed; AutoBaxBench private scenarios (§3.2.3) would need a private repo + local CodeQL CLI; handle in P6.
2. **CodeQL via `workflow_dispatch` from an orphan `eval-ci` branch**, not "on push". Reason: a `.github/workflows/codeql.yml` on the arm branch is a scanner hint in the agent's working tree (violates the §2.1 "agent must never see scanner rules" spirit). `codeql-action/analyze` takes `ref`/`sha` inputs so alerts attach to `refs/heads/exp/<arm>/sample<i>` and `codeql-report`'s `-f ref=` filter still works. Push-trigger kept as a documented `--mode push` fallback.
3. **Stats in pure numpy** (bootstrap, exact McNemar, Wilcoxon, Wilson, Fleiss κ). Mixed-effects logistic (§2.2) deferred — would need statsmodels; summary notes "pool across specs → report per spec".
4. Design §2.3 `findings.jsonl` schema is extended with `sample`, `spec`, `tool_run`, `cwe_family`, `exploitable`, `ground_truth_id`, `matched`, and a companion **`samples.jsonl`** (one row per arm×target×sample incl. zero-finding samples) — needed for denominators, correct-AND-secure and cost.

---

## Layout being built (design §9, made concrete)

```
docs/plans/sdlc-eval-implementation-plan.md      ← this plan (P0 first commit)
tools/
  new_experiment.sh          unified (promptfoo | inspect | git-branch-ab | detection-bench engines)
  ephemeral_repo.sh          gh create/bootstrap-codeql/push-start/codeql-run/codeql-alerts/archive
  lib/manifest.py            dotted-path set/add/append on manifest.json; append-sample for samples.jsonl
  lib/cwe_map.py             CWE→top-level family map + category-keyword→CWE for scan-code output
  lib/sarif_to_findings.py   SARIF / gh code-scanning alerts JSON → findings.jsonl rows
  lib/evalstats.py           findings+samples → summary.md/json (paired stats, κ, flip rate, cost)
  lib/canary_probe.py        contamination probe (gateway) + transcript trace audit
  lib/find_sdlc.sh           locate/clone pinned ai-security-sdlc (AISEC_SDLC_DIR > plugin cache > clone)
  lib/probelib.py            pytest helpers for dynamic probes (--base-url, --findings-out, mark(cwe,…))
  tests/…                    unit tests + fixtures for all of the above
skills/
  control-codegen/           + lib/ (vendored spine), build_sample.sh, score_branch.sh, setup_codeguard.sh,
                               make_sbp.sh, probes/spec-0N/, acceptance/spec-0N/, arms/E/, SKILL.md rewrite
  tool-codescan/  tool-pentest/  tool-assetscan/  tool-remediate/   (P2–P5; same shape, see below)
targets/                     + compose wrappers/oracles for pentest (P4)
```

---

## P0 — shared spine (do first; every harness depends on it)

Order below is the dependency order. Each item = files + tests + how to verify.

### P0.1 `tools/lib/cwe_map.py` + `tools/lib/sarif_to_findings.py`
- `cwe_map.py`: `CWE_FAMILY` (~60 entries: 23/35/36/73→22; 77/88→78; 564→89; 80/83/87→79; 285/639/862/863→284; 95/96→94; 120/121/122/787/788→119; 259/321→798; 200/532/209→200; …), `family_of(cwe)`, `CATEGORY_TO_CWE` keyword table (path traversal→22, ssrf→918, idor/authorization→284, sql→89, command→78, xss→79, deserialization→502, upload→434, mass assignment→915, secret→798, csv/formula→1236, redirect→601 …), `cwe_from_text(s)`.
- `sarif_to_findings.py <in> --format sarif|gh-alerts --tool codeql|scan-code|semgrep --run R --arm A --target T --sample N [--tool-run r] [--strip-prefix P] [--append findings.jsonl]`. CWE resolution: CodeQL `rule.properties.tags` `external/cwe/cwe-NNN` → Semgrep `properties.cwe` → scan-code `properties.category`/message via `cwe_from_text` → `"uncwe"`. Severity from `security-severity` (≥9 crit, ≥7 high, ≥4 med) else SARIF `level`. `gh-alerts` reader handles the `codeql-report` JSON shape (`rule.tags`, `rule.security_severity_level`, `most_recent_instance.location`), skipping dismissed/fixed.
- **findings.jsonl row**: `{run, arm, target, sample, spec, tool, tool_run, rule_id, cwe, cwe_family, file, line, severity, confidence, oracle_confirmed, exploitable, ground_truth_id, matched, message}`.
- Tests: `tools/tests/test_sarif_to_findings.py` with fixtures `tools/tests/fixtures/{codeql.sarif, semgrep.sarif, scancode.sarif, gh_alerts.json}`. Replaces the inline heredoc in control-codegen SKILL.md.

### P0.2 `tools/lib/evalstats.py`
- Inputs: `findings.jsonl` + `samples.jsonl` (`{run, arm, target, sample, branch, sha, build_ok, acceptance_pass, acceptance_passed, acceptance_total, exploitable_count, cost_usd, tokens_in, tokens_out, wall_s, contaminated}`; derived-with-warning if absent).
- CLI: `evalstats.py <findings.jsonl> [--samples …] --pair-on target,sample [--baseline A] [--arms A,D] [--metric per_cwe,any_exploitable,correct_and_secure,sev_weighted,total] [--severity-min high] [--tools …] [--majority scan-code=2/3] [--boot 10000 --seed 0] [--out summary.md] [--json summary.json]`.
- Functions (numpy only): `majority_vote`, `per_sample_matrix`, `paired_bootstrap_ci`, `mcnemar_exact` (binomial via `math.comb`), `wilcoxon_signed_rank` (exact n≤20 else normal approx), `wilson_ci`, `fleiss_kappa`, `flip_rate`, `severity_weighted`, `summarize` → markdown: arm means±CI, paired deltas vs baseline, per-CWE-family table, correct-AND-secure side by side, cost table, LLM-scanner κ/flip, contaminated stratum split.
- Tests: `test_evalstats.py` — synthetic 2 arms × 12 samples with known deltas; McNemar hand value (b=1,c=6 → p=0.125); Wilson known values; Fleiss κ textbook matrix; zero-finding samples counted; `--seed` determinism.

### P0.3 `tools/lib/manifest.py` + unified `tools/new_experiment.sh`
- Keep positional `<skill> "<label>" [engine]` (existing tests unchanged); add `--start-branch --arms --k --spec --tool --model --temperature --benchmark --pair-on --repo`. Engine default per skill (`git-branch-ab` for control-codegen, `detection-bench` for tool-*). `git-branch-ab` adds `arms/ probes/ branches/` and records `starting_state.{branch,sha,tag_sha}` (warn if branch ≠ `starting-state-locked`). All engines keep `inputs/ results/ transcripts/` + add `contamination/`.
- `manifest.json` **v2** superset (design §2.3): legacy keys + `tool{name,version}`, `model{id,temperature,family,cutoff}`, `benchmark{name,version,spec}`, `arms[]`, `k`, `paired`, `pair_on`, `scorers[]`, `starting_state`, `repo{remote,visibility,archived}`, `contamination{canary_probe,contaminated_targets,trace_audit}`, `cost{usd,tokens_in,tokens_out,wall_s}`, `_todo[]`.
- `manifest.py set|add|append|append-sample|todo-clear` (stdlib json + dotted paths).
- Delete bespoke `skills/control-codegen/new_experiment.sh`; add control-codegen (+ future tool-*) to the vendoring loops in `sync_skills.sh`. Change CI/`run_tests.sh` drift check to `git diff --exit-code -- skills/`. Extend `check_independence.sh` sibling regex to include `control-codegen|tool-[a-z]+`.
- Tests: extend `test_new_experiment.py` (engine dirs, `--k/--arms` in manifest, `$3` starting with `--`), new `test_manifest.py`.

### P0.4 `tools/lib/find_sdlc.sh` + `tools/ephemeral_repo.sh`
- `find_sdlc.sh`: `AISEC_SDLC_DIR` > `~/.claude/plugins/cache/*/ai-security-*/*` > `git clone --depth 1 --branch ${AISEC_SDLC_REF:-main} https://github.com/wtcooper/ai-security-sdlc <EXP>/.deps/ai-security-sdlc`; prints dir + sha (recorded in `manifest.scorers[].sdlc_sha`). Nothing from the sibling repo is vendored → no self-containment violation, no drift.
- `ephemeral_repo.sh` subcommands: `create --name eval-<harness>-<spec>-<date> --dir D [--public]` (`gh repo create --public --clone`); `bootstrap-codeql --dir D --languages … --template-dir $(find_sdlc)/plugins/code-scan/skills/codeql-ci/templates` → orphan branch `eval-ci` with `codeql-eval.yml` (template patched to `workflow_dispatch: inputs {ref, sha}`, `security-extended`, `analyze` `ref/sha` inputs) + `codeql-config.yml`; `push-start --branch starting-state` (pushes branch + tag, verifies tripwire); `codeql-run --repo --ref exp/A/sample1 [--wait]` (`gh workflow run … -f ref -f sha`, `gh run watch`); `codeql-alerts --repo --ref … --out results/<arm>/sample<i>/codeql/` (alerts.json via `gh api … -f ref=refs/heads/… --paginate` + raw analysis SARIF); `archive` (`gh repo archive -y`; manifest `repo.archived=true`). `--dry-run` prints commands.
- Tests: `test_ephemeral_repo.sh` arg parsing with `GH=echo`/`--dry-run`. One manual smoke against a real public repo (dispatch → alerts filtered by ref; check no cross-branch bleed).

### P0.5 `tools/lib/canary_probe.py`
- `probe --questions questions.jsonl --out <EXP>/contamination/canary.json [--n 3]` (rows `{target, prompt, markers[], threshold}`; endpoint `AISEC_GATEWAY_*` > `LITELLM_BASE_URL` (repo `targets/proxy` :4000); `openai` client, T=0; contaminated = hits ≥ threshold in ≥ ceil(n/2) runs; writes to manifest `contamination.*`).
- `audit --transcripts <EXP>/transcripts --markers markers.txt --out contamination/trace_audit.json` (Claude `stream-json` or text; hit index + before-first-tool-call flag). Test with in-process mock OpenAI endpoint.

### P0.6 `tools/lib/probelib.py`
- pytest plugin: `--base-url`, `--findings-out`; fixtures `api`, `two_users`; `mark(cwe, exploitable, evidence)`; hook writes one JSONL row per probe test (`tool=probe`, `exploitable`, `oracle_confirmed=exploitable`). Convention: a probe **fails when exploitable**. Test: pytest-in-pytest against a local `http.server`.

### P0 done when
`bash scripts/run_tests.sh` green; `bash tools/sync_skills.sh && git diff --exit-code -- skills/` clean; `check_independence.sh` clean; `ephemeral_repo.sh` smoke created/archived a public repo with a CodeQL alert attached to a non-default ref.

---

## P1 — secure-plan (extend `control-codegen`; design §3)

Files under `skills/control-codegen/`:
- `lib/` (vendored spine) + vendored `new_experiment.sh`, `ephemeral_repo.sh`.
- `setup_codeguard.sh <EXP> [--ref v1.4.0]` — clone `cosai-oasis/project-codeguard` at tag into `<EXP>/.deps/`; build a **template `CLAUDE_CONFIG_DIR`** once: `claude plugin marketplace add <path>` + `claude plugin install codeguard-security@project-codeguard --scope user`; verify rules under the plugin cache; record version+sha in `manifest.arms[B]`. Fallback: `claude -p --plugin-dir <path>` (record which). Inertness check: `grep -c codeguard transcripts/B-*.jsonl` must be >0.
- `make_sbp.sh <EXP> <spec>` — throwaway checkout of `starting-state`, fresh `CLAUDE_CONFIG_DIR` with the sdlc `secure-plan` plugin (`find_sdlc.sh`), `claude -p` runs `/security-profile` then `/secure-build-plan` from `SPEC.md`; copies `.ai-security/{profile.md,plans/<slug>-sbp.md}` into `<EXP>/arms/C/`; verifies rule ids cited / no rule bodies; session discarded. Reused verbatim for D.
- `build_sample.sh <EXP> <arm> <i> [--model M --max-budget-usd X]` — tripwire check; `git switch -c exp/<arm>/sample<i>`; pre-build diff by arm (A/B: empty commit; C/D: `.ai-security/`; E: `arms/E/<spec>/CLAUDE.md`); `CFG=$(mktemp -d)` (+ codeguard template for B/D); `CLAUDE_CONFIG_DIR=$CFG claude -p "$(cat build-prompt.md)" --model $M --permission-mode bypassPermissions --no-session-persistence --strict-mcp-config --setting-sources project --output-format stream-json --verbose --max-budget-usd $X > transcripts/<arm>-sample<i>.jsonl` (run inside a container/VM, never on the host with real creds; **not** `--bare` — it disables plugins and would silently kill arm B); parse `result` event → cost/usage; commit; `git push -u origin exp/<arm>/sample<i>`; `manifest.py append-sample`.
- `score_branch.sh <EXP> <arm> <i> [--scan-code-repeats 3] [--no-docker] [--semgrep]` — `git worktree add`; `codeql-run --wait` + `codeql-alerts` → `sarif_to_findings --format gh-alerts`; `docker build/run` on `:18080` (fail ⇒ `build_ok=false`, a result not an error); `pytest probes/<spec>` + `pytest acceptance/<spec>` (junit); `run_scan.py` ×3 with `SCORER_MODEL` (refuse same family as generator unless `--allow-same-family`); fold into `findings.jsonl`/`samples.jsonl`; cleanup.
- `probes/conftest.py` + `probes/spec-01/test_probes.py`: path traversal on download/`stored_path`, SSRF (`169.254.169.254`, `127.0.0.1:8080`, `[::1]`, `file://`, redirect-to-loopback via a probe-controlled sink container on the same docker network), IDOR read/modify/delete/folder across two users, zip-slip (`../` + absolute entries), upload size/content-type, share `allow_download=false` bypass. `acceptance/spec-01/test_acceptance.py` = the spec's 9 acceptance criteria. Skeleton dirs for spec-02..05; fill 02–04 in P1, spec-05 = ASan harness script.
- `arms/E/<spec>/CLAUDE.md` — the old "condition C specific rules" text moved out of SKILL.md.
- **SKILL.md rewrite**: arms A/B/C/D/(E) per design §3.1 (E = upper bound only); "A vs D first, k=10, spec-01" (§3.5); B/C mechanics + isolation section; scoring section → `score_branch.sh` + `evalstats`; Semgrep demoted to optional flag; results contract §2.3.
- Design §3.6 gap "add the modern-stack spec": **P6**, not P1 (needs a hand-written probe set; do after the effect is seen).

**P1 run order**: smoke A vs D, spec-01, k=1, cheap gateway model (checks arm-B inertness, CodeQL alert filtering, docker probes) → k=10 A vs D → add B/C → probes for specs 02–04.

**P1 done when**: `.evals/control-codegen/spec-01-claude-A-vs-D_<date>/summary.md` exists with per-CWE deltas, any-exploitable McNemar, correct-AND-secure side by side, cost; manifest fully populated (`_todo` empty).

---

## P2 — `skills/tool-codescan/` (design §4)
- Vendors spine + `ephemeral_repo.sh`. New: `fetch_targets.sh` (LiveCVEBench/CVE-Factory post-cutoff slice, RealVuln, CWE-Bench-Java at pinned commits), `mutate.py` (identifier/route renaming + rename map for label translation), `match.py` (§2.4: CWE family + file→function→line±5; emits `ground_truth_id/matched`; adjudication CSV for unmatched sample ≥30), `run_scancode.sh` (`run_scan.py` ×3 in standalone mode; also agent mode).
- SKILL.md: arms = scanners (`codeql`, `scan-code`×3, `union`); optional model sweep via gateway; complement analysis + flip rate + clean/contaminated + original/mutant strata (all computed by `evalstats.py`; add `--group-by tool` and complement table).
- Tier-3 tie-in: score P1 arm-A samples labeled by probe oracle.
- Done when: one summary per tier-1 benchmark with recall/precision(lower-bound + adjudicated)/F1 per CWE family and complement table.

## P3 — `skills/tool-assetscan/` (design §6) — cheap, no agents
- New: `fetch_sets.sh` (MCPTox, SkillSieve/SkillVetBench, MalSkillBench-if-released, PickleBall/SafePickle/ShadowPickle; pinned), `mutate_{mcp,skill,pickle}.py`, `yara_filter.sh` (`yara -r <cisco rules> <sample>` → 0 hits gate), `score.py` → thin wrapper on `evalstats` (TPR/FPR Wilson CIs, per-run flip, Fleiss κ, severity Krippendorff α — add α to evalstats), `Dockerfile` (no-network sandbox for pickle work; scan-only, never `pickle.load`).
- Order per design §10: skill scanner first (known to flip), then MCP, then model. Configs: static-only / judge-only / combined; k=5 at default T and T=0. Doc guidance: κ<0.6 ⇒ "unusable for CI gating".

## P4 — `skills/tool-pentest/` (design §5) — most infra-heavy
- New: `targets/` compose wrappers (CVE-Bench subset zero-day mode, Vulhub post-cutoff list + `oracle.sh` per env (canary file/callback/DB row/marker header), XBEN mutator fork, Duck Store checks if source is available), profile templates per target, `validate.py` (rerun PoCs from Strix `vulnerabilities.json` against the oracle; different-family LLM validator only when no scripted oracle), `run_strix.sh` (fixed version, `--scan-mode quick→standard`, `--max-budget`, gateway model, **black-box URL only**, k=3).
- Metrics via evalstats: recall@vuln (oracle-confirmed), precision, $/verified finding, time-to-first-finding; zero-day vs one-day strata; canary probe + trace audit per target.

## P5 — `skills/tool-remediate/` (design §7)
- New: `fetch_targets.sh` (Vul4Py, PatchEval dockerized subset, AutoPatchBench sample), `verify_fix.sh` (exploit oracle **and** functional tests; flags exploit-only fixes; checks regression test added and that it fails on pre-fix commit), `run_fix.sh` (`fix-findings` from SARIF; baseline arm = plain "ask the model to fix"; no-fix arm).
- Closed loop: P1 arm-A samples → `fix-findings` → re-run `score_branch.sh` → exploitable↓ / acceptance still passes.

## P6 — robustness (design §3.2.2–4, §8, §11 open items)
- BaxBench "generate externally, evaluate in-harness" adapter (`baxbench_adapter.sh`: drop arm build into `results/<model>/<scenario>/…/code`, run `--mode test/evaluate`); AutoBaxBench private batch (private repo + local CodeQL CLI).
- Modern-stack spec (`specs/spec-06-nextjs-app.md`, Next.js 16 App Router + server actions + Drizzle/Neon + Clerk) + hand-written probes (RSC/server-action authz, IDOR, SSRF-in-fetch, unsafe redirects, secrets in client bundle).
- Codex CLI as second agent (AGENTS.md path, `codeguard-codex.zip` install).
- Meta-eval of ai-evals/ai-redteam: planted-weakness manifest per target (DVAA, AIGoat, sdlc `testbed/`), score generated promptfoo configs' recall on the planted list; reuse `targets/proxy`; thin vs full profile arms.

---

## Verification (end to end)
1. Unit: `bash scripts/run_tests.sh` (adds test_evalstats / test_sarif_to_findings / test_manifest / test_probelib / ephemeral_repo dry-run / canary mock).
2. Repo hygiene: `bash tools/sync_skills.sh && git diff --exit-code -- skills/`; `bash scripts/check_independence.sh`; CI green.
3. P0 smoke: `ephemeral_repo.sh create/bootstrap-codeql/push-start/codeql-run/codeql-alerts/archive` on a throwaway public repo; alert JSON filtered by non-default ref.
4. P1 smoke: A vs D, spec-01, k=1 with a gateway model → transcript for B shows codeguard read; `docker` probes produce `probe` rows; `evalstats.py` renders `summary.md`. Then k=10.
5. Each later phase: its SKILL.md Plan→Run→Analyze produces `.evals/<harness>/<label>_<date>/{manifest.json,results/,findings.jsonl,samples.jsonl,summary.md}` — the §2.3 contract.

## Risks (carry-forward from design §11 + build-specific)
- Autonomous `claude -p` builds with permission bypass → run in container/VM; cap `--max-budget-usd`.
- Arm-B fidelity: `claude plugin` install under a custom `CLAUDE_CONFIG_DIR` and `--setting-sources` interplay must be verified once (fallback `--plugin-dir`).
- CodeQL: 3–10 min per dispatch, GitHub concurrency; language matrix must match the spec's chosen stack (FastAPI vs Express alt); verify alerts-by-ref has no cross-branch bleed.
- Docker: agent Dockerfiles may fail (`build_ok=false` drops the pair; report count); SSRF probes need a probe-controlled sink on the docker network.
- Unverified benchmark availability (design §11) is checked in each phase's `fetch_*.sh` before relying on it.

## Build status (2026-08-16)
P0–P6 built and unit-tested (95 tests pass; ephemeral-repo + CodeQL smoke verified live on a public
repo). P1 spec-01 probes/acceptance complete; specs 02–05 (+06 modern stack) have stubs. Remaining
work is running the experiments (real agent builds + benchmark fetches), not building the harness.

## First commit (immediately after approval)
1. Write `docs/plans/sdlc-eval-implementation-plan.md` (this content, repo-relative links to the design doc sections).
2. Start P0.1.
