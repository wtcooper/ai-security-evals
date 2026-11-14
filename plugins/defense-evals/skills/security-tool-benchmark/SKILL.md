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
Docker, supervised). Detail for each kind is in `references/<kind>.md`: read the one you
need before running.

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
- **Repeats:** 1 for deterministic tools; 3 or more for LLM-backed or agentic tools, so
  run-to-run agreement can be reported.
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

---

## RUN
Per target, for each tool arm, run that kind's driver. It calls the adapter, normalises
the SARIF into `<EXP>/findings.jsonl` and appends a row to `<EXP>/samples.jsonl`:
```
bash code/run_scanner.sh      "$EXP" <target-id> <tree>  --arm <tool> [--repeats N] [-- <tool args>]
bash extension/run_scanner.sh "$EXP" <asset-id>  <asset> --arm <label> [--adapter <tool>] [--repeats N] [-- <tool args>]
bash pentest/run_dast.sh      "$EXP" <target-id> <url>   --arm <tool> [--k N] [-- <tool args>]
```
A tool that finds nothing is a result, not an error. A tool that fails to run is reported
and that target is excluded for that tool, never counted as a clean scan. The exact
commands, per-set options and safety rules are in `references/<kind>.md`.

---

## ANALYZE
Score against the known answers, then compute the statistics:
```
# code
python3 code/match.py "$EXP/findings.jsonl" <ground_truth.jsonl> --out "$EXP/matched.jsonl" \
  --report "$EXP/match.md" --adjudicate "$EXP/adjudicate.csv" --group-by arm
python3 lib/evalstats.py "$EXP/matched.jsonl" --samples "$EXP/samples.jsonl" --pair-on target \
  --baseline <tool1> --out "$EXP/summary.md" --json "$EXP/summary.json"
# extension
python3 extension/score_assets.py "$EXP/verdicts.jsonl" --by config,stratum \
  --out "$EXP/summary.md" --json "$EXP/summary.json"
# pentest
python3 pentest/validate.py "$EXP" <target-id> --arm <tool> --oracle <oracle.sh> --base-url <url>
python3 lib/evalstats.py "$EXP/findings.jsonl" --samples "$EXP/samples.jsonl" --pair-on target \
  --baseline <tool1> --out "$EXP/summary.md" --json "$EXP/summary.json"
```
Present to the user:
1. **What did not run**: tools that failed on targets, targets excluded as recognised by
   the model, sets that could not be fetched.
2. **Recall and precision (or true- and false-positive rate) per tool, with intervals.**
   Never recall alone: a tool that flags everything has perfect recall.
3. **The complement**: found by tool A only, tool B only, both, and the union. This is
   the answer to "what does adding this tool buy", and totals hide it.
4. **Run-to-run agreement** (flip rate, Fleiss κ) for every nondeterministic tool. This is
   a validity signal: it says how repeatable the tool's verdict is.
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
0.67, recall 0.67), `tool-b` finds 1 of 3 (recall 0.33), the union is 3 of 3, and the
last line is `SMOKE OK`.

## Notes
- A finding without a reproducible proof is precision noise in the `pentest` kind: the
  oracle decides, identically for every tool. Never point a pentest tool at a system the
  user does not own, and never mount the target's source for a black-box claim.
- Model files are scanned, never loaded. The container that handles them has no network.
- State the exact tool version and, for LLM-backed tools, the model, with any number.
- The adapters named `sdlc-*` drive skills from the separate `ai-security-sdlc` project and
  are optional; nothing else here depends on that project.
- **Not verified:** the kinds were merged from three earlier skills. The `code` path was run
  end to end with replayed SARIF, and the matching, mutation and scoring scripts have unit
  tests. No real scanner, model-file sandbox or pentest target was run where this was built.
