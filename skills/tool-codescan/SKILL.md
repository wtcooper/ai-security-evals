---
name: tool-codescan
description: >-
  Measure the recall / precision / F1 of code scanners — the ai-security-sdlc `scan-code`
  LLM reviewer and GitHub CodeQL (and their union) — on code with KNOWN vulnerabilities:
  post-cutoff real CVEs (LiveCVEBench), labelled TP + FP-trap sets (RealVuln), the
  CodeQL-native CWE-Bench-Java, plus contamination controls (canary probe, mutated
  variants). Reports per-CWE-family recall at file/function/line granularity, precision
  lower bound + adjudicated precision, complement analysis (LLM-only / CodeQL-only / both),
  run-to-run flip rate and cost per KLOC. Use to answer "which scanner catches what, and is
  the LLM scan worth it". For rule-file efficacy on generated code use control-codegen.
disable-model-invocation: true
user-invocable: true
argument-hint: "[livecvebench|realvuln|cwe-bench-java]"
dependencies:
  - git
  - gh (for CodeQL via a public ephemeral repo)
  - python>=3.11
allowed-tools:
  - bash
---

# tool-codescan — how good are `scan-code` and CodeQL against ground truth?

Run this **on behalf of a user** who wants recall/precision numbers with CIs for the scanners
their SDLC relies on. Drive **Plan → Run → Analyze**; the arms here are **scanners, not
treatments** (design doc §4).

## Design
| Held constant | Varied |
|---|---|
| Target set + version pins (ground_truth.jsonl) | scanner: `codeql` (security-extended), `scan-code` (model M, T=0) ×3, `union` |
| Matching rule (§2.4: CWE family + file→function→line ±5) | optional model sweep for `scan-code` |
| Contamination strata (clean vs canary-positive; original vs mutant) | — |

Tiers (design §4.1): **1** LiveCVEBench post-cutoff slice (vulnerable snapshot → recall, fixed
snapshot → FP), RealVuln (676 TP + 120 FP traps; public → canary + mutant stratum), CWE-Bench-Java
(published CodeQL 27/120 vs LLM-assisted 55/120); **2** CyberGym-E2E / ZeroDayBench-style
transplants; **3** control-codegen arm-A apps labelled by the probe oracle; DVAA/DVMCP for
LLM-tool sinks. Smoke only: OWASP Benchmark, Juliet, goats.

## Layout
```
fetch_targets.sh <EXP> <bench> [--ref R --cutoff DATE --limit N]   # pinned clone + ground_truth.jsonl
materialize.sh <targets-dir> <target-id>                            # vulnerable/ + fixed/ snapshots
run_scancode.sh <EXP> <target-id> <tree> [--repeats 3 --model M]    # scan-code xN -> findings.jsonl
ephemeral_repo.sh                                                    # push snapshot branches + CodeQL by ref
mutate.py <src> <dst> --map rename_map.json   translate_gt.py gt.jsonl map.json   # anti-memorisation pair
match.py findings.jsonl ground_truth.jsonl --out matched.jsonl --report match.md --adjudicate adj.csv
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py canary_probe.py find_sdlc.sh
```

## PLAN
1. Preflight: `gh auth status`; gateway env for `scan-code` (`AISEC_GATEWAY_BASE_URL`,
   `AISEC_GATEWAY_API_KEY`, `AISEC_MODEL`); record the model's **training cutoff** (manifest
   `model.cutoff`) — LiveCVEBench is filtered to entries newer than it.
2. Pick benchmark(s) (`AskUserQuestion`); `bash new_experiment.sh tool-codescan "<label>" --benchmark <b> --arms codeql,scan-code`.
3. `bash fetch_targets.sh "$EXP" <b> --cutoff <YYYY-MM-DD> [--limit 30]` — inspect
   `targets/<b>/ground_truth.jsonl`; **verify availability** (several sets are new/rolling; the
   parser warns when it finds nothing — fix the parser, don't skip silently).
4. Contamination: write `q.jsonl` (per target: "list the vulnerabilities in <repo@version>") and run
   `python3 lib/canary_probe.py probe --questions q.jsonl --out $EXP/contamination/canary.json --exp $EXP`.
   For public sets also build a mutant: `python3 mutate.py <tree> <tree>.mut --map map.json` +
   `translate_gt.py`; scan both as a paired stratum (`target` = `<id>` and `<id>#mut`).

## RUN
Per target: `materialize.sh` → CodeQL: `ephemeral_repo.sh create` once per benchmark
(public), push `snap/<target>/vulnerable` (+ `/fixed`) branches, `codeql-run --ref … --wait`,
`codeql-alerts --out results/codeql/<target>/` → `sarif_to_findings.py --format gh-alerts
--tool codeql --arm codeql --target <id>`; LLM: `run_scancode.sh "$EXP" <id> <tree> --repeats 3`.
Scan `fixed/` too: any finding at a fixed location = FP (append with `--target <id>@fixed`).

## ANALYZE
```bash
python3 match.py $EXP/findings.jsonl $EXP/targets/<b>/ground_truth.jsonl \
   --out $EXP/matched.jsonl --report $EXP/match.md --adjudicate $EXP/adjudicate.csv --group-by arm
python3 lib/evalstats.py $EXP/matched.jsonl --pair-on target --baseline codeql --majority scan-code=2/3 \
   --out $EXP/summary.md --json $EXP/summary.json
```
Read: recall@file/function/line and precision (lower bound; adjudicate ≥30 unmatched → fill the
CSV → adjudicated precision) per scanner and per CWE family; **complement** (found by LLM only /
CodeQL only / both / union); `scan-code` flip rate + κ; clean vs contaminated and original vs
mutant strata; $ and tokens per KLOC. Never report recall alone (F1/F0.5 + severity-weighted).

## Notes
- The LLM scanner's value proposition is classes CodeQL has no source for (LLM tool-argument
  taint, business-logic authz) — the complement table is the headline, not the totals.
- Local models via the gateway are fine for plumbing; state which model produced any published number.
