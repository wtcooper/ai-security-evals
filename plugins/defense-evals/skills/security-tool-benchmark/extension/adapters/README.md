# Asset-scanner adapters — the only scanner-specific code in this skill

This harness compares asset scanners (skill / MCP / model-file classifiers) on labelled
malicious+benign corpora. Ground truth (`labels.jsonl`) and scoring (`score_assets.py`) never know
which scanner produced a verdict. Each scanner gets one adapter; `run_scanner.sh --arm <label>
--adapter <file>` drives it.

## Contract (one function)
```
bash adapters/<name>.sh <asset-path> <out-dir> [config flags...]
```
- Scan the single asset at `<asset-path>` (a skill dir, an MCP server dir, or a model file).
- Write SARIF 2.1.0 to `<out-dir>/findings.sarif`. An asset "flags" when it has ≥1 finding at/above
  the severity gate (`score_assets.py`).
- **Model / pickle assets: scan only, never load.** The adapter must run the scan inside the
  no-network container (`docker run --network none`, see `Dockerfile`). Never `pickle.load` a positive.

## Config as an arm
The static-only / judge-only / combined split is a config flag, not a separate scanner. Back several
arms with one adapter by passing the flag after `--`:
```bash
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-static   --adapter sdlc-scan-skill -- --config static-only
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-judge    --adapter sdlc-scan-skill -- --config judge-only
bash run_scanner.sh "$EXP" <asset> <path> --arm scan-skill-combined --adapter sdlc-scan-skill -- --config combined
```
The arm label is what `score_assets.py --by config` groups on — so the static/judge/combined and
cross-scanner comparisons fall out of the same table.

## Shipped reference adapters
| adapter | scanner | asset kind | needs |
|---|---|---|---|
| `sdlc-scan-skill.sh` | Cisco AI skill-scanner (ai-security-sdlc `scan-skill`) | skill dir | `uvx`, gateway env (judge) |
| `sdlc-scan-mcp.sh` | ai-security-sdlc `scan-mcp` | MCP server dir | the sdlc plugin, gateway env |
| `sdlc-scan-model.sh` | ai-security-sdlc `scan-model` | model file | docker (no-network), gateway env |
| `yara.sh` | raw YARA rules (signature baseline) | any file/dir | `yara` |
| `modelscan.sh` | ModelScan (Protect AI) | model file | `modelscan`, docker |

The signature baselines (`yara.sh`, `modelscan.sh`) are the point of comparison: an LLM-judge's value
is only what it catches **beyond** signatures — the held-out mutated positives with 0 YARA hits.

## Add your own
Copy `yara.sh`, change the invocation and the →SARIF step. Any classifier works: PickleScan,
guardrails-based skill scanners, a commercial model-supply-chain tool.
