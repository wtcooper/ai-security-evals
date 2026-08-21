---
name: tool-assetscan
description: >-
  Measure and COMPARE TPR / FPR / severity calibration and (for LLM-judge scanners) run-to-run
  nondeterminism of asset scanners — skill scanners, MCP scanners, and model-file scanners (the
  ai-security-sdlc scan-skill / scan-mcp / scan-model, Cisco's YARA rules, ModelScan, PickleScan, or
  your own) — on labelled malicious+benign corpora (MCPTox, SkillSieve/SkillVetBench,
  PickleBall/SafePickle/ShadowPickle), plus held-out mutated positives that signature rules cannot
  match (so an LLM-judge's value beyond signatures is isolated). Scanner-agnostic: you name the
  scanners/configs to compare and each is driven by a small adapter. Reports TPR/FPR with Wilson CIs,
  per-run flip rate and Fleiss κ across repeats, split by scanner and by static-only / judge-only /
  combined config. Vendor fixtures excluded as contamination; pickle work is scan-only in a
  no-network container.
disable-model-invocation: true
user-invocable: true
argument-hint: "[skill|mcp|model]"
dependencies:
  - git
  - python>=3.11
  - docker (model/pickle sandbox)
  - "the scanners you choose (e.g. uvx skill-scanner, yara, modelscan)"
allowed-tools:
  - bash
  - AskUserQuestion
---

# tool-assetscan — compare asset scanners (skill / MCP / model) on labelled corpora

Run **on behalf of a user** deciding whether to trust (and CI-gate on) an asset scanner. Cheap: no
agents to drive, just scanner runs over labelled files. Drive **Plan → Run → Analyze**.

## PLAN
1. **Ask the user which scanners/configs to compare** (`AskUserQuestion`, multi-select) — the
   independent variable, established first. For each asset kind the arms are scanners AND the
   static/judge/combined config:
   - **LLM-judge scanner** (e.g. sdlc `scan-skill` / `scan-mcp` / `scan-model`) at **static-only**,
     **judge-only**, **combined** — k=5 (κ is the point; we've seen `scan-skill` flip clean→flag→clean
     on an unchanged skill)
   - **Signature baseline** (YARA rules, ModelScan, PickleScan) — deterministic, `--repeats 1`; this
     is the comparator that isolates what the judge catches *beyond* signatures
   - **Other / bring-your-own** — add `adapters/<name>.sh` (one function, see `adapters/README.md`)
   Record the chosen scanners+configs as the arms (e.g. `scan-skill-combined`, `scan-skill-static`,
   `yara`). One adapter backs several arms via `--adapter` + a `--config` flag.
2. `bash new_experiment.sh tool-assetscan "<label>" --benchmark <set> --arms <arm1>,<arm2>,...`.
3. `bash fetch_sets.sh "$EXP" <scanner> <set>` — **verify availability** (unreleased sets warn).
   Build negatives (benign, high-install, no prior scanner hits) and the `ours` benign regression set.
4. Held-out stratum: `mutate_skill.py` / `mutate_pickle.py` for ≥3 paraphrase/carrier forms per class,
   then `yara_filter.sh <cisco rules> <sample>` — keep only 0-hit mutants. Keep parent↔mutant pairs.

Order: **skill first** (known to flip), then MCP, then model. Positives + negatives + **held-out
mutated positives with 0 signature hits** + vendor fixtures **excluded** (total contamination). Treat
κ<0.6 as "unusable for CI gating" and say so in the scanner's docs.

## Layout
```
adapters/<name>.sh <asset> <out-dir> [--config ...]   # ONE per scanner: scan -> <out-dir>/findings.sarif (adapters/README.md)
run_scanner.sh <EXP> <asset-id> <asset> --arm <label> [--adapter F] [--repeats 5] [-- <config>]   # drives any adapter
fetch_sets.sh <EXP> <scanner> <set>          # pinned corpora -> sets/<scanner>/<set>/labels.jsonl
mutate_skill.py  <benign> <out> --class ...  # held-out malicious skills (LLM-paraphrased PI/exfil, local sink)
mutate_pickle.py <out> --payload --carrier   # held-out malicious pickles (harmless __reduce__; SCAN ONLY)
yara_filter.sh <cisco-rules> <sample>        # keep only 0-YARA-hit mutants
score_assets.py findings.jsonl+labels -> verdicts.jsonl --by config,stratum   # TPR/FPR/CI, flip, Fleiss κ
Dockerfile                                   # --network none sandbox for model/pickle
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py find_sdlc.sh
```

## RUN
For each config/scanner arm × asset, k repeats (k=5 for judge configs, 1 for signatures):
```bash
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-static   --adapter sdlc-scan-skill --repeats 5 -- --config static-only
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-judge    --adapter sdlc-scan-skill --repeats 5 -- --config judge-only
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-combined --adapter sdlc-scan-skill --repeats 5 -- --config combined
bash run_scanner.sh "$EXP" <asset> <path> --arm yara --repeats 1 -- --rules <cisco-rules>
```
Model/pickle runs go **inside the container** (the adapter does `docker run --network none`).

## ANALYZE
```bash
# glue findings.jsonl + labels.jsonl -> verdicts.jsonl (score_assets.build_verdicts_from_findings)
python3 score_assets.py $EXP/verdicts.jsonl --by config,stratum --out $EXP/summary.md --json $EXP/summary.json
```
Read TPR/FPR (Wilson CIs) per scanner arm; the **shipped vs mutant** split (does the LLM-judge catch
what the signatures can't); flip rate + Fleiss κ per config (the gating verdict); compare FPR to
published references (MCPZoo avg precision 45.5%; Cisco YARA ~78% FP in the AppSecSanta audit). For
model scanners, also score `hf_harvest.py`'s summarization against PickleBall/SafePickle labels (HF
flags are NOT ground truth — JFrog: ~96% FP).

## Notes
- Pickle work is scan-only; the container has no network; never `pickle.load` a positive.
- Report per stratum; a scanner that only catches shipped (signature-covered) positives has no judge
  value — the held-out mutant column is where an LLM-judge earns its place (or doesn't).
- Adding a scanner to a comparison is one file: `adapters/<name>.sh`. No harness change.
