---
name: tool-codescan
description: >-
  Measure and COMPARE the recall / precision / F1 of any code scanners — CodeQL, Semgrep, Snyk,
  an LLM code reviewer, a commercial SAST, or your own tool — on code with KNOWN vulnerabilities:
  post-cutoff real CVEs (LiveCVEBench), labelled TP + FP-trap sets (RealVuln), CWE-Bench-Java, plus
  contamination controls (canary probe, mutated variants). Scanner-agnostic: you name the tools to
  compare and each is driven by a small adapter. Reports per-CWE-family recall at file/function/line
  granularity, precision lower bound + adjudicated precision, complement analysis (which tool catches
  what the others miss / both / union), run-to-run flip rate and cost per KLOC. Use to answer "which
  scanner should we rely on, and what does adding scanner X buy over Y". For rule-file efficacy on
  generated code use control-codegen.
disable-model-invocation: true
user-invocable: true
argument-hint: "[livecvebench|realvuln|cwe-bench-java]"
dependencies:
  - git
  - python>=3.11
  - "the scanners you choose (e.g. semgrep, codeql CLI, gh for the code-scanning path)"
allowed-tools:
  - bash
  - AskUserQuestion
---

# tool-codescan — compare code scanners against ground truth

Run this **on behalf of a user** who wants recall/precision numbers with CIs to decide which
scanner(s) to rely on. Drive **Plan → Run → Analyze**. The arms are **scanners, not treatments**:
the target set + matching rule are held constant, the scanner is the independent variable.

## PLAN
1. **Ask the user which scanners to compare** (`AskUserQuestion`, multi-select) — this is the
   independent variable and the first thing every run establishes. Offer the shipped reference
   adapters and let them add their own:
   - **CodeQL** (`codeql` — deterministic, `--repeats 1`)
   - **Semgrep** (`semgrep` — deterministic, `--repeats 1`)
   - **LLM code reviewer** (e.g. the ai-security-sdlc `scan-code`, or any other — nondeterministic,
     `--repeats 3` so flip-rate/κ are measurable)
   - **Other / bring-your-own** — any SAST or LLM reviewer; add `adapters/<name>.sh` (one function,
     see `adapters/README.md`). Snyk, Bandit, a commercial tool, a second LLM: all just adapters.
   Record the chosen tool set as the arms. For any LLM-based tool, also record its **training cutoff**
   (manifest `model.cutoff`) — LiveCVEBench is filtered to entries newer than it.
2. Preflight the chosen tools: `command -v semgrep codeql`, `gh auth status` (only if using the
   GitHub code-scanning path), gateway env for any LLM reviewer.
3. Pick benchmark(s) (`AskUserQuestion`);
   `bash new_experiment.sh tool-codescan "<label>" --benchmark <b> --arms <tool1>,<tool2>,...`.
4. `bash fetch_targets.sh "$EXP" <b> --cutoff <YYYY-MM-DD> [--limit 30]` — inspect
   `targets/<b>/ground_truth.jsonl`; **verify availability** (several sets are new/rolling; the
   parser warns when it finds nothing — fix the parser, don't skip silently).
5. Contamination: write `q.jsonl` (per target: "list the vulnerabilities in <repo@version>") and run
   `python3 lib/canary_probe.py probe --questions q.jsonl --out $EXP/contamination/canary.json --exp $EXP`.
   For public sets also build a mutant: `python3 mutate.py <tree> <tree>.mut --map map.json` +
   `translate_gt.py`; scan both as a paired stratum (`target` = `<id>` and `<id>#mut`).

| Held constant | Varied |
|---|---|
| Target set + version pins (ground_truth.jsonl) | **scanner** (the arms you chose) + optional model sweep for any LLM reviewer |
| Matching rule (CWE family + file→function→line ±5) | — |
| Contamination strata (clean vs canary-positive; original vs mutant) | — |

Tiers: **1** LiveCVEBench post-cutoff slice (vulnerable snapshot → recall, fixed snapshot → FP),
RealVuln (676 TP + 120 FP traps; public → canary + mutant stratum), CWE-Bench-Java (published CodeQL
27/120 vs LLM-assisted 55/120); **2** CyberGym-E2E transplants; **3** control-codegen arm-A apps
labelled by the probe oracle; DVAA/DVMCP for LLM-tool sinks. Smoke only: OWASP Benchmark, Juliet.

## Layout
```
adapters/<name>.sh <tree> <out-dir>         # ONE per scanner: run it -> <out-dir>/findings.sarif (see adapters/README.md)
run_scanner.sh <EXP> <id> <tree> --arm <name> [--repeats N] [-- <adapter args>]  # drives any adapter -> findings.jsonl
fetch_targets.sh <EXP> <bench> [--ref R --cutoff DATE --limit N]   # pinned clone + ground_truth.jsonl
materialize.sh <targets-dir> <target-id>                            # vulnerable/ + fixed/ snapshots
ephemeral_repo.sh                                                    # optional: CodeQL via GitHub code-scanning by ref
mutate.py / translate_gt.py                                         # anti-memorisation paired variant
match.py findings.jsonl ground_truth.jsonl --out matched.jsonl --report match.md --adjudicate adj.csv
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py canary_probe.py find_sdlc.sh
```

## RUN
Per target: `materialize.sh` → then, **for each scanner arm**, run its adapter:
```bash
bash run_scanner.sh "$EXP" <id> "$EXP/targets/<b>/<id>/vulnerable" --arm semgrep --repeats 1
bash run_scanner.sh "$EXP" <id> "$EXP/targets/<b>/<id>/vulnerable" --arm codeql  --repeats 1
bash run_scanner.sh "$EXP" <id> "$EXP/targets/<b>/<id>/vulnerable" --arm sdlc-scan-code --repeats 3
```
Scan `fixed/` too (append with `--target <id>@fixed`): any finding at a fixed location = FP.

CodeQL via **GitHub code-scanning** (keeps the scanner config out of the agent's view) instead of the
local `codeql.sh` adapter: `ephemeral_repo.sh create` once per benchmark (public), push
`snap/<target>/vulnerable` (+ `/fixed`) branches, `codeql-run --ref … --wait`, `codeql-alerts --out
results/codeql/<id>/`, then `sarif_to_findings.py --format gh-alerts --tool codeql --arm codeql
--target <id> --append $EXP/findings.jsonl`. Same `findings.jsonl` rows as the adapter path.

## ANALYZE
```bash
python3 match.py $EXP/findings.jsonl $EXP/targets/<b>/ground_truth.jsonl \
   --out $EXP/matched.jsonl --report $EXP/match.md --adjudicate $EXP/adjudicate.csv --group-by arm
python3 lib/evalstats.py $EXP/matched.jsonl --pair-on target --baseline <tool1> --majority <llm-tool>=2/3 \
   --out $EXP/summary.md --json $EXP/summary.json
```
Read: recall@file/function/line and precision (lower bound; adjudicate ≥30 unmatched → fill the CSV →
adjudicated precision) per scanner and per CWE family; **complement** (found by tool A only / tool B
only / both / union) — this is the headline for "what does adding X buy"; flip rate + κ for any
nondeterministic tool; clean vs contaminated and original vs mutant strata; $ and tokens per KLOC.
Never report recall alone (F1/F0.5 + severity-weighted).

## Notes
- The complement table is the point: an LLM reviewer's value is the classes CodeQL/Semgrep have no
  rule for (tool-argument taint, business-logic authz); a signature scanner's value is cheap
  deterministic coverage. The totals hide this; the complement shows it.
- State which exact tool version / model produced any published number (`--tool` label = adapter name).
- Adding a scanner to a comparison is one file: `adapters/<name>.sh`. No harness change.
