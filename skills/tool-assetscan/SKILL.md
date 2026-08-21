---
name: tool-assetscan
description: >-
  Measure TPR / FPR / severity calibration and LLM-judge run-to-run nondeterminism of the
  ai-security-sdlc asset scanners — scan-mcp, scan-skill, scan-model — on labelled malicious
  + benign corpora (MCPTox, SkillSieve/SkillVetBench, PickleBall/SafePickle/ShadowPickle),
  plus held-out mutated positives that Cisco's YARA rules cannot match (so the LLM-judge's
  value beyond signatures is isolated). Reports TPR/FPR with Wilson CIs, per-run flip rate and
  Fleiss κ across repeats, split by config (static-only / judge-only / combined). Vendor
  fixtures excluded as contamination; pickle work is scan-only in a no-network container.
disable-model-invocation: true
user-invocable: true
argument-hint: "[scan-skill|scan-mcp|scan-model]"
dependencies:
  - git
  - python>=3.11
  - docker (model/pickle sandbox)
  - yara (held-out filter)
allowed-tools:
  - bash
---

# tool-assetscan — TPR/FPR/κ of scan-mcp / scan-skill / scan-model

Run **on behalf of a user** deciding whether to trust (and CI-gate on) an asset scanner. Cheap:
no agents to drive, just scanner runs over labelled files. Drive **Plan → Run → Analyze** (design §6).

## Design
Positives + negatives + **held-out mutated positives with 0 YARA hits** + vendor fixtures
**excluded**. Configs per scanner: **static-only / judge-only / combined**. k=5 repeats at default
T and T=0. We already observed `scan-skill` flip clean→flag→clean on an unchanged skill — κ is the
point. Treat κ<0.6 as "unusable for CI gating" and say so in the scanner's docs.

Order (design §10): **skill first** (known to flip), then MCP, then model.

## Layout
```
fetch_sets.sh <EXP> <scanner> <set>          # pinned corpora -> sets/<scanner>/<set>/labels.jsonl
mutate_skill.py  <benign> <out> --class ...  # held-out malicious skills (LLM-paraphrased PI/exfil, local sink)
mutate_pickle.py <out> --payload --carrier   # held-out malicious pickles (harmless __reduce__; SCAN ONLY)
yara_filter.sh <cisco-rules> <sample>        # keep only 0-YARA-hit mutants
score_assets.py verdicts.jsonl --by config,stratum   # TPR/FPR/CI, flip, Fleiss κ
Dockerfile                                   # --network none sandbox for model/pickle
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py find_sdlc.sh
```

## PLAN
1. `bash new_experiment.sh tool-assetscan "<label>" --benchmark <set> --arms static-only,judge-only,combined`.
2. `bash fetch_sets.sh "$EXP" <scanner> <set>` — **verify availability** (unreleased sets warn).
   Build negatives (benign, high-install, no prior scanner hits) and the `ours` benign regression set.
3. Held-out stratum: `mutate_skill.py` / `mutate_pickle.py` for ≥3 paraphrase/carrier forms per class,
   then `yara_filter.sh <cisco rules> <sample>` — keep only 0-hit mutants. Keep parent↔mutant pairs.

## RUN
For each config × asset × run r (k=5): invoke the sdlc scanner (located via `lib/find_sdlc.sh`;
scan-skill = `uvx --from cisco-ai-skill-scanner skill-scanner scan … --format sarif`, judge-only
vs `--no-*` static-only per its flags), SARIF → `sarif_to_findings.py --tool <scanner> --target
<asset> --tool-run r`. Model/pickle runs go **inside the container** (`docker run --network none`).

## ANALYZE
```bash
# glue findings.jsonl + labels.jsonl -> verdicts.jsonl (score_assets.build_verdicts_from_findings)
python3 score_assets.py $EXP/verdicts.jsonl --by config,stratum --out $EXP/summary.md --json $EXP/summary.json
```
Read TPR/FPR (Wilson CIs) per config; the **shipped vs mutant** split (does the LLM-judge catch
what YARA can't); flip rate + Fleiss κ per config (gating verdict); compare FPR to the published
references (MCPZoo avg precision 45.5%; Cisco YARA ~78% FP in the AppSecSanta audit). For scan-model,
also score `hf_harvest.py`'s summarization against PickleBall/SafePickle labels (HF flags are NOT
ground truth — JFrog: ~96% FP).

## Notes
- Pickle work is scan-only; the container has no network; never `pickle.load` a positive.
- Report per stratum; a scanner that only catches shipped (YARA-covered) positives has no judge value.
