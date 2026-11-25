---
name: security-tool-benchmark
description: >-
  Compare security tools against targets with KNOWN answers, to decide which tool to rely
  on and what adding one buys over another. Three kinds, one design: `code` compares code
  scanners (CodeQL, Semgrep, Trivy, osv-scanner, zizmor, an LLM code reviewer) on source
  with known vulnerabilities; `extension` compares scanners of AI components (skills,
  plugins, MCP servers, model files) on labelled malicious and benign samples; `pentest`
  compares black-box pentest tools (an AI pentest agent, Nuclei, ZAP) against running
  vulnerable apps, counting only oracle-confirmed exploits. Tool-agnostic: each tool is
  driven by a small adapter the user picks. Reports recall, precision or false-positive
  rate with intervals, what each tool finds that the others miss, and run-to-run
  agreement for nondeterministic tools. It does not scan your own code or components.
license: MIT
compatibility: "Requires python>=3.11 and git, plus the tools you choose to compare. The extension kind uses Docker with no network for model files; the pentest kind uses Docker for targets."
---

# security-tool-benchmark — which security tool should we rely on?

You are running this skill **on behalf of a user** who wants numbers, with intervals, for
how well one or more security tools find known problems: because a review depends on that
tool's output, or because the capability under review is itself an AI security tool.
Drive **Plan → Run → Analyze**.

The arms are the **tools**. The targets, their known answers and the matching rule are
held fixed. This skill measures a tool; it ships none and does not scan the user's own
code, skills or servers. It does not say whether a tool is good enough.

| Kind | Tools compared | Targets with known answers | Headline numbers |
|---|---|---|---|
| `code` | code scanners, incl. LLM code reviewers | source trees with known CVEs / labelled true and false positives | recall at file/function/line, precision, complement |
| `extension` | scanners of skills, plugins, MCP servers, model files | labelled malicious + benign samples, plus mutated positives no signature matches | true- and false-positive rate, run-to-run agreement |
| `pentest` | black-box pentest tools, incl. AI pentest agents | self-hosted vulnerable apps with a per-target oracle | oracle-confirmed recall, unreproducible-finding rate, cost per verified finding |

Execution tier: `code` **T0** (static); `extension` **T1** (model files are only ever
scanned, inside a container with no network); `pentest` **T2** (live targets you own, in
Docker, watched by a person who can stop it at once; see *Supervising a pentest run*).
Detail for each kind is in `references/<kind>.md`: read the one you need before running.

---

## PLAN

### 1. Choose the kind and the tools (`AskUserQuestion`)
Ask which kind, then **which tools to compare** — the independent variable, established
first. Each tool needs one adapter file: `<kind>/adapters/<name>.sh`, which runs the tool
and writes SARIF. Adapters for common tools ship (`<kind>/adapters/README.md` lists them
and what each needs installed); adding another is one file with no harness change. To
score results a tool already produced elsewhere, use `code/adapters/replay.sh`.

Compare like with like. A dependency scanner cannot satisfy a ground truth made of code
locations, and a workflow auditor cannot satisfy either. Within a class, compare recall;
across classes, the useful question is the **complement**: what each tool finds that the
others miss. Confirm the benchmark's ground truth contains the class being scored.

For any tool backed by a language model: record its training cutoff (targets newer than
the cutoff are the uncontaminated ones) and plan repeats, since its verdict can change
between identical runs.

### 2. Choose the targets and the depth
Each kind lists its benchmark sets and how to fetch them in `references/<kind>.md`
(`code/fetch_targets.sh`, `extension/fetch_sets.sh`, Docker targets for `pentest`).
Verify a set is actually available before planning around it: several are new or rolling.

- **Depth:** `smoke` (a handful of targets — proves the wiring only), `standard` (enough
  targets per class for the intervals to mean something; start near 30), or `full` (the
  whole set). Pass it as the fetch script's `--limit`.
- **Repeats** (`--repeats N` on every driver; defaults `code` 1, `extension` 5, `pentest`
  3): 1 for deterministic tools; 3 or more for LLM-backed or agentic tools, so run-to-run
  agreement can be reported. Every run is a row in `runs.jsonl` with `tool_run` (1..N) and
  `repeat` (0..N-1).
- **Cost before compute:** tell the user targets × tools × repeats, and for LLM-backed and
  agentic tools a per-run budget cap, before anything runs. The `pentest` kind is the
  expensive one: each agentic run can take minutes and real spend.

### 3. Contamination controls
Public test sets are in training data, so a model-backed tool may recall the answer
instead of finding it. Where it applies: ask the tool's model cold what it knows about
each target (`lib/canary_probe.py probe`) and report recognised targets as a separate
stratum; build a mutated twin of public targets (`code/mutate.py`,
`extension/mutate_skill.py`, `pentest/xben_mutate.sh`) and report original and twin side
by side.

### 4. Open an experiment folder
`bash new_experiment.sh security-tool-benchmark "<label>" --benchmark <set> --arms <tool1>,<tool2>`
— it prints `EXP=<path>` and records the tools, the benchmark and the deployment context.

### 5. Register the analysis plan, before anything runs
```
python3 plan.py "$EXP" --kind <code|extension|pentest> --arms <tool1>,<tool2> --baseline <tool1> \
  --benchmark <set> --depth standard --targets <N> [--repeats <llm-tool>=3] \
  [--corpus <ground_truth.jsonl|labels.jsonl>] [--private] [--ceiling 0.95] [--max-minutes 30]
```
It writes `<EXP>/plan.json` (arms, baseline, set, depth, targets, seed, repeats per tool,
the corpus fingerprint and whether it is public, the organisation's `criteria.json` if
present; for `pentest` the time limit and the scope file's fingerprint) and prints targets ×
tools × repeats with the smallest paired difference this many targets can separate. Show it
to the user as the cost. A changed plan is kept as an amendment (`--reason`), and every report
ends with the plan and any departure from it. The drivers warn when no plan is registered.

---

## RUN
Per target, for each tool arm, run that kind's driver. It calls the adapter, normalises
the SARIF into `<EXP>/findings.jsonl` and appends a row to `<EXP>/samples.jsonl`:
```
bash code/run_scanner.sh      "$EXP" <target-id> <tree>  --arm <tool> [--repeats N] [-- <tool args>]
bash extension/run_scanner.sh "$EXP" <asset-id>  <asset> --arm <label> [--adapter <tool>] [--repeats N] [-- <tool args>]
bash pentest/run_dast.sh      "$EXP" <target-id> <url>   --arm <tool> [--repeats N] [--max-minutes 30] [-- <tool args>]
```
Every run is logged in `<EXP>/runs.jsonl` as `ok` or `failed` (and, for `pentest`, `timeout`
or `stopped`). A tool that finds nothing is a result. A tool that fails to run is not: pass
`--runs` when scoring so that target is excluded for that tool instead of being counted as a
clean scan. The exact commands, per-set options and safety rules are in
`references/<kind>.md`.

### Supervising a pentest run (T2)
The `pentest` kind sends real attacks to live targets, so **a person watches the run and can
halt it**. These protect the evaluation itself; they are not a control this repository ships.
- **Scope file** `<EXP>/scope.txt` (or `--scope`): the authorised targets, one URL or
  `host[:port]` per line. `run_dast.sh` and `validate.py` refuse to start when it is missing
  or the target is not listed; `validate.py` never replays a PoC, or follows a redirect, to a
  URL outside it.
- **Time limit** `--max-minutes` (default **30**) per tool run: a run over it is ended and
  recorded as `timeout`.
- **Run log** `<EXP>/run.log`: append-only; every start, end and stop, and the tool's own
  output. Before starting, tell the user to watch it with `tail -f "$EXP/run.log"`.
- **Stop file** `<EXP>/STOP` (or `--stop-file`): `touch "$EXP/STOP"` ends the current run
  and no further run starts while it exists; the driver exits 3. Drive a sweep as
  `for t in …; do bash pentest/run_dast.sh "$EXP" "$t" … || break; done`, and tell the user
  the stop file is the way to halt it.

---

## ANALYZE
Score against the known answers, then compute the statistics:
```
# code
python3 code/match.py "$EXP/findings.jsonl" <ground_truth.jsonl> --out "$EXP/matched.jsonl" \
  --report "$EXP/match.md" --adjudicate "$EXP/adjudicate.csv" --group-by arm --runs "$EXP/runs.jsonl"
python3 lib/evalstats.py "$EXP/matched.jsonl" --samples "$EXP/samples.jsonl" --pair-on target \
  --baseline <tool1> --out "$EXP/summary.md" --json "$EXP/summary.json"
# extension
python3 extension/score_assets.py "$EXP/verdicts.jsonl" --findings "$EXP/findings.jsonl" \
  --labels <labels.jsonl> --runs "$EXP/runs.jsonl" --by config,stratum \
  --out "$EXP/summary.md" --json "$EXP/summary.json"
# pentest
python3 pentest/validate.py "$EXP" <target-id> --arm <tool> --oracle <oracle.sh> --base-url <url>
python3 pentest/score.py "$EXP" --out "$EXP/pentest.md" --json "$EXP/pentest.json"
python3 lib/evalstats.py "$EXP/findings.jsonl" --samples "$EXP/samples.jsonl" --pair-on target \
  --baseline <tool1> [--majority <agentic-tool>=2/3] --out "$EXP/summary.md" --json "$EXP/summary.json"
```
The kind reports (`match.md`, the extension `summary.md`, `pentest.md`) open with **Read
first**: what did not run, the share of cases whose outcome changed between runs of the same
tool, and a `near_ceiling` validity flag when every tool is at or above `--ceiling` (default
0.95; the set then separates tools poorly). They end with the registered plan. A tool run N
times is scored on the union of its runs in `match.md` and `pentest.md`; compare it with a
tool run once on the per-run figure shown beside it, or majority-vote it in `evalstats`.
Present to the user:
1. **What did not run**: tools that failed, timed out or were stopped on targets (the
   reports list them and the `failed runs` column counts them), targets excluded as
   recognised by the model, sets that could not be fetched. Do not compare a tool that failed on some targets with one that
   scanned all of them until it is fixed and re-run.
2. **Recall and precision (or true- and false-positive rate) per tool, with intervals.**
   Never recall alone: a tool that flags everything has perfect recall.
3. **The complement**: found by tool A only, tool B only, both, and the union. This is
   the answer to "what does adding this tool buy", and totals hide it.
4. **Run-to-run agreement** (flip rate, Fleiss κ) for every nondeterministic tool, from
   the Read first section of the kind report and `evalstats`. This is a validity signal: it
   says how repeatable the tool's verdict is. Read the `near_ceiling` flag the same way.
5. **Strata**: original against mutated twin, clean against recognised targets, and for
   `extension` the mutated positives no signature matches (what a model-backed scanner adds
   beyond signatures, or does not).
6. **Cost**: time and spend per target, and for `pentest` per verified finding.

Unmatched findings are a precision *lower bound* until someone adjudicates a sample of
them (`adjudicate.csv`): some are real issues the benchmark did not label. Say which it is.
Do not tell the user which tool to adopt; give them the table.

---

## Smoke test (no keys, no tools installed)
```
bash tests/smoke.sh
```
Two replayed SARIF files stand in for two tools over a bundled tree with three known
vulnerabilities. Expected: `tool-a` finds 2 of 3 with one unmatched finding (precision
0.67, recall 0.67), `tool-b` finds 1 of 3 (recall 0.33), the union is 3 of 3, the report
ends with the registered plan and "No departures", and the last line is `SMOKE OK`. The
pentest supervision (scope refusal, time limit, stop file, run log) is exercised keylessly
by `tests/test_pentest_kind.py` with stand-in adapters.

## Notes
- A finding without a reproducible proof is precision noise in the `pentest` kind: the
  oracle decides, identically for every tool. Never point a pentest tool at a system the
  user does not own, and never mount the target's source for a black-box claim.
- Model files are scanned, never loaded. The container that handles them has no network.
- State the exact tool version and, for LLM-backed tools, the model, with any number.
- No kind grades with a language model: ground truth, labels or the oracle decide,
  identically for every tool, so there is no judge to blind or re-grade. A model inside a
  tool under test is part of that tool. The only p-values are `evalstats`'s paired table,
  which shows each one Holm-adjusted across the table.
- A stop or time limit ends the tool's whole process group. Containers a tool starts through
  the Docker daemon (Strix's sandbox, for one) are not in that group: after a stop, check
  `docker ps` and remove what the tool left running.
- The adapters named `sdlc-*` drive skills from the separate `ai-security-sdlc` project and
  are optional; nothing else here depends on that project. `sdlc-scan-skill.sh` passes flags
  that the current Cisco skill-scanner rejects; prefer `cisco-skill-scanner.sh`.
- **Comparing extension scanners fairly** (`extension/adapters/README.md` has the detail):
  adapters ship for Tencent AI-Infra-Guard (`aig-skill-scan`, `aig-mcp-scan`), Cisco
  skill-scanner and mcp-scanner, and NVIDIA SkillSpector. The Tencent tools have no
  rule-based mode, so their result is always a language model's and depends on which model
  is configured; the others have a keyless static mode. Compare static with static and
  model-assisted with model-assisted, with the same model behind every tool where you can.
  The adapters scan a copy of each sample without its answer-key file, and turn the silent
  fallbacks they can detect (a missing key, an unusable model reply) into failed runs.
- **Not verified:** the kinds were merged from three earlier skills. The `code` path was run
  end to end with replayed SARIF, and the matching, mutation and scoring scripts have unit
  tests. For the `extension` kind, the static modes of SkillSpector and both Cisco scanners
  were run for real on a benign and a synthetic malicious skill; every model-assisted mode
  and both Tencent tools were exercised only against a mock model, so no detection result
  exists for Tencent. No code scanner, model-file sandbox or pentest target was run. The
  plan, near-ceiling and flip-rate notes were run on fixtures. The pentest supervision was
  run only with stand-in shell adapters and no live target: no real pentest tool, Docker
  sandbox or Strix container has been timed out or stopped by it.
