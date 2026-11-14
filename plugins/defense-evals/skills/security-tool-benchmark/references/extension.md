# `extension` kind — scanners of AI components: skills, plugins, MCP servers and model files

Detail for the `extension` kind of `security-tool-benchmark`. Paths are relative to the skill folder.

Run **on behalf of a user** deciding how far to trust a scanner of AI components. Cheap: no
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
   - **Other / bring-your-own** — add `extension/adapters/<name>.sh` (one function, see `extension/adapters/README.md`)
   Record the chosen scanners+configs as the arms (e.g. `scan-skill-combined`, `scan-skill-static`,
   `yara`). One adapter backs several arms via `--adapter` + a `--config` flag.
2. `bash new_experiment.sh security-tool-benchmark "<label>" --benchmark <set> --arms <arm1>,<arm2>,...`.
3. `bash extension/fetch_sets.sh "$EXP" <scanner> <set>` — **verify availability** (unreleased sets warn).
   Build negatives (benign, high-install, no prior scanner hits) and the `ours` benign regression set.
4. Held-out stratum: `extension/mutate_skill.py` / `extension/mutate_pickle.py` for ≥3 paraphrase/carrier forms per class,
   then `extension/yara_filter.sh <cisco rules> <sample>` — keep only 0-hit mutants. Keep parent↔mutant pairs.

Order: **skill first** (known to flip), then MCP, then model. Positives + negatives + **held-out
mutated positives with 0 signature hits** + vendor fixtures **excluded** (total contamination). Report
Fleiss κ beside every rate for a nondeterministic scanner: it is a validity signal that says
how repeatable the scanner's verdict is, and the reader decides what repeatability they need.

## Layout
```
extension/adapters/<name>.sh <asset> <out-dir> [--config ...]   # ONE per scanner: scan -> <out-dir>/findings.sarif (extension/adapters/README.md)
extension/run_scanner.sh <EXP> <asset-id> <asset> --arm <label> [--adapter F] [--repeats 5] [-- <config>]   # drives any adapter
extension/fetch_sets.sh <EXP> <scanner> <set>          # pinned corpora -> sets/<scanner>/<set>/labels.jsonl
extension/mutate_skill.py  <benign> <out> --class ...  # held-out malicious skills (LLM-paraphrased PI/exfil, local sink)
extension/mutate_pickle.py <out> --payload --carrier   # held-out malicious pickles (harmless __reduce__; SCAN ONLY)
extension/yara_filter.sh <cisco-rules> <sample>        # keep only 0-YARA-hit mutants
extension/score_assets.py findings.jsonl+labels -> verdicts.jsonl --by config,stratum   # TPR/FPR/CI, flip, Fleiss κ
extension/Dockerfile                                   # --network none sandbox for model/pickle
lib/ evalstats.py sarif_to_findings.py cwe_map.py manifest.py find_sdlc.sh
```

## RUN
For each config/scanner arm × asset, k repeats (k=5 for judge configs, 1 for signatures):
```bash
bash extension/run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-static   --adapter sdlc-scan-skill --repeats 5 -- --config static-only
bash extension/run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-judge    --adapter sdlc-scan-skill --repeats 5 -- --config judge-only
bash extension/run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-combined --adapter sdlc-scan-skill --repeats 5 -- --config combined
bash extension/run_scanner.sh "$EXP" <asset> <path> --arm yara --repeats 1 -- --rules <cisco-rules>
```
Model/pickle runs go **inside the container** (the adapter does `docker run --network none`).

## ANALYZE
```bash
# glue findings.jsonl + labels.jsonl -> verdicts.jsonl (score_assets.build_verdicts_from_findings)
python3 extension/score_assets.py $EXP/verdicts.jsonl --by config,stratum --out $EXP/summary.md --json $EXP/summary.json
```
Read TPR/FPR (Wilson CIs) per scanner arm; the **shipped vs mutant** split (does the LLM-judge catch
what the signatures can't); flip rate + Fleiss κ per config (how repeatable the verdict is); compare FPR to
published references (MCPZoo avg precision 45.5%; Cisco YARA ~78% FP in the AppSecSanta audit).
For model-file scanners, the scan verdicts Hugging Face publishes are one more arm to score
against PickleBall/SafePickle labels, not ground truth: export them with the `review-evidence`
skill's weights scan and feed them through `extension/adapters` like any other tool.

## Notes
- Pickle work is scan-only; the container has no network; never `pickle.load` a positive.
- Report per stratum; a scanner that only catches shipped (signature-covered) positives has no judge
  value — the held-out mutant column is where an LLM-judge earns its place (or doesn't).
- Adding a scanner to a comparison is one file: `extension/adapters/<name>.sh`. No harness change.
