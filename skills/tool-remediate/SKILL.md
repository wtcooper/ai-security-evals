---
name: tool-remediate
description: >-
  Measure whether the ai-security-sdlc fix-findings skill actually fixes things (design §7):
  given SARIF from the scanners, do the fixes make the exploit STOP, keep the functional suite
  green, and add a regression test that fails on the pre-fix commit — and how often does a
  scanner report "fixed" while the exploit still works. Paired oracles (exploit + functional)
  on Vul4Py / PatchEval / AutoPatchBench, plus a closed loop on control-codegen arm-A samples.
  Baselines: no-fix and plain "ask the model to fix", so we isolate what triage/regression add.
disable-model-invocation: true
user-invocable: true
argument-hint: "[vul4py|patcheval|closed-loop]"
dependencies:
  - git
  - docker
  - python>=3.11
allowed-tools:
  - bash
---

# tool-remediate — does fix-findings actually fix things?

Run **on behalf of a user** who wants to know their remediation skill produces real fixes, not
scanner-gaming. Drive **Plan → Run → Analyze** (design §7).

## Design
| Held constant | Varied (arms) |
|---|---|
| Target + paired oracle (exploit PoC + functional suite) | `fix-findings` vs `naive` (plain "fix it") vs `no-fix` |
| SARIF input | — |
A fix counts only when **the exploit fails AND functional tests pass AND a regression test was
added that fails on the pre-fix commit**. Metrics: fix rate (both oracles), exploit-only-fix rate
(failure), functional regressions introduced, regression-test-added (and does it catch pre-fix),
scanner-says-fixed-but-exploit-works, diff size, cost.

Targets (design §7): **1** Vul4Py (100 Py vulns, paired exploit+pytest oracles), PatchEval
dockerized subset; **2** AutoPatchBench / SEC-bench; **3** closed loop — control-codegen arm-A
samples → `fix-findings` → re-run its probe+acceptance ensemble.

## Layout
```
fetch_targets.sh <EXP> <bench>          # Vul4Py / PatchEval subset at pinned refs (+ oracles)
run_fix.sh <EXP> <id> <repo> --arm fix-findings|naive|no-fix   # produce the fix from SARIF
verify_fix.sh <EXP> <id> <repo> --exploit <cmd> --tests <cmd> --pre-sha S --post-sha S --regression-test path
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py find_sdlc.sh
```

## PLAN
1. `bash new_experiment.sh tool-remediate "<label>" --benchmark <b> --arms no-fix,naive,fix-findings`.
2. `bash fetch_targets.sh "$EXP" <b>` — each item ships an exploit PoC + functional suite (the two
   oracles) and pre/post commits; verify availability.

## RUN
Per item × arm: `run_fix.sh` drives the arm (fix-findings via the sdlc plugin from the scanner
SARIF; naive = one-shot model prompt; no-fix = identity) on a clone, records the post-fix sha.
Closed loop: reuse control-codegen's `score_branch.sh` as the oracle instead of a bundled suite.

## ANALYZE
```bash
bash verify_fix.sh "$EXP" <id> <repo> --exploit "<poc cmd>" --tests "<pytest cmd>" \
    --pre-sha <vuln> --post-sha <fixed> --regression-test tests/test_regression_<id>.py
python3 lib/evalstats.py "$EXP/findings.jsonl" --samples "$EXP/samples.jsonl" --pair-on target \
    --baseline no-fix --out "$EXP/summary.md" --json "$EXP/summary.json"
```
`samples.jsonl` carries `fixed / exploit_only_fix / regression_added / regression_catches_prefix`
per (arm,target); read fix rate, exploit-only rate (a failure), scanner-gaming rate, and the
fix-findings − naive delta (what triage/regression steps add). The paired oracle rejected 15/119
exploit-only "fixes" in Vul4Py — expect the same failure mode.

## Notes
- Never weaken a test to make a fix pass; a fix without a regression is incomplete (mirror the plugin).
- Report cost/diff-size beside fix rate — a huge rewrite that "fixes" one CWE is not a good fix.
