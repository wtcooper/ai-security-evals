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

`sdlc-scan-skill.sh` reaches the Cisco skill-scanner through the ai-security-sdlc wiring and passes
`--no-llm-judge` / `--no-static`. cisco-ai-skill-scanner 2.3.2 rejects both flags ("unrecognized
arguments", checked 2026-11-14), so its static-only and judge-only arms fail against that version.
To compare the Cisco scanners themselves, use the direct adapters below.

## Third-party scanner adapters (driven directly)

These drive the scanners' own command lines. This repo ships none of them: install each yourself,
or let the adapter fetch it with `uvx`. All five scan only; none starts a server or runs asset code.

| adapter | tool (licence) | what it scans | install | network / key | deterministic? repeats | verified here |
|---|---|---|---|---|---|---|
| `skillspector.sh` | [NVIDIA SkillSpector](https://github.com/NVIDIA/SkillSpector) 2.12.0 (Apache-2.0) | skill dir, single skill file or zip | `uv tool install git+https://github.com/NVIDIA/skillspector.git` (Python ≥ 3.12; pypi.org had no `skillspector` project on 2026-11-14) | `static-only`: no key; rule SC4 calls api.osv.dev when the skill declares dependencies, with an offline fallback list. `combined`: `SKILLSPECTOR_PROVIDER` + that provider's key | `static-only` yes, `--repeats 1`. `combined` no, `--repeats 5` | `static-only` yes, real runs. `combined` no: no completed model run; seen only its failures (no key, and unusable replies from a mock model) |
| `cisco-skill-scanner.sh` | [Cisco AI Defense skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) 2.3.2 (Apache-2.0) | skill dir with a skill file | `pip install cisco-ai-skill-scanner` (Python ≥ 3.11) | `static-only`: none. `judge-only` / `combined`: `SKILL_SCANNER_LLM_API_KEY`, `SKILL_SCANNER_LLM_MODEL` | `static-only` yes, `--repeats 1`. LLM configs no, `--repeats 5` | `static-only` yes, real runs. LLM configs: invocation and report shape only, against a mock model (a canned "no findings" reply) |
| `cisco-mcp-scanner.sh` | [Cisco AI Defense mcp-scanner](https://github.com/cisco-ai-defense/mcp-scanner) 4.8.7 (Apache-2.0) | `static-only` / `judge-only` / `combined`: a saved MCP list-tools response (`tools.json`), not source code. `behavioral`: MCP server source code | `pip install cisco-ai-mcp-scanner` (Python ≥ 3.11.4) | `static-only`: none. Others: `MCP_SCANNER_LLM_API_KEY`, `MCP_SCANNER_LLM_MODEL` | `static-only` yes, `--repeats 1`. Others no, `--repeats 5` | `static-only` yes, real runs. Others: invocation and report shape only, against a mock model |
| `aig-skill-scan.sh` | [Tencent AI-Infra-Guard](https://github.com/Tencent/AI-Infra-Guard) `aig-skill-scan` 0.2.2 (Apache-2.0) | skill dir | `pip install aig-skill-scan` (Python ≥ 3.9) | always: `LLM_API_KEY` for an OpenAI-compatible endpoint. No static mode | no, `--repeats 5` | invocation and report shape only, against a mock model. No real model run |
| `aig-mcp-scan.sh` | Tencent AI-Infra-Guard `aig-mcp-scan` 0.2.0 (Apache-2.0) | MCP server source dir | `pip install aig-mcp-scan` (Python ≥ 3.10) | always: `LLM_API_KEY`. No static mode | no, `--repeats 5` | invocation and report shape only, against a mock model. No real model run |

Versions are the ones run on 2026-11-14. "Mock model" means `tests/mock_openai_server.py` replayed
a canned reply: that proves the adapter calls the tool correctly and reads its report, and says
nothing about what the tool detects with a real model.

Common to all five:
- `--config` selects the mode; a config the tool does not have is rejected with exit 2 and a
  reason. The default is `static-only` where the tool has one (never needs a key), else `judge-only`.
- Any other argument is passed to the tool unchanged.
- The tool is found through `<PREFIX>_BIN` (a path), then `<PREFIX>_SPEC` (a pip requirement run
  with `uvx`; use it to pin a version, e.g. `CISCO_SKILL_SCANNER_SPEC='cisco-ai-skill-scanner==2.3.2'`),
  then `PATH`, then `uvx` with the unpinned PyPI package (SkillSpector has none, so it must be
  installed or given a `SKILLSPECTOR_SPEC`). Prefixes: `SKILLSPECTOR`, `CISCO_SKILL_SCANNER`,
  `CISCO_MCP_SCANNER`, `AIG_SKILL_SCAN`, `AIG_MCP_SCAN`.
- The asset is scanned as a temporary copy without `.label.json` (the answer key `mutate_skill.py`
  writes into each mutant). `--in-place` scans the path as given.
- `scan_report_to_sarif.py` is the last step: it converts mcp-scanner's JSON, or checks a tool's
  own SARIF, and writes `findings.sarif` with `properties.severity` on the harness scale and the
  tool's value in `properties.original_severity`. The tool's untouched report stays in `<out-dir>/raw/`.
- A run that did not really happen fails instead of producing a result: a missing key, an
  analyzer that was asked for and silently skipped, a model call or reply that failed while the
  tool carried on with rules only, a report with no scanned item, a tool-reported incomplete
  scan, an unreachable model. Each adapter's header lists the cases it covers.

### Example: three skill scanners on the same asset
```bash
A=<skill-dir>; ID=<asset-id>          # repeat for every labelled asset in the set
# Rule-based arms: no key, deterministic. Tencent has no such mode.
bash extension/run_scanner.sh "$EXP" $ID $A --arm skillspector-static --adapter skillspector        --repeats 1 -- --config static-only
bash extension/run_scanner.sh "$EXP" $ID $A --arm cisco-skill-static  --adapter cisco-skill-scanner --repeats 1 -- --config static-only

# Model-backed arms: point all three at the SAME model, or the model is what you compare.
export SKILLSPECTOR_PROVIDER=openai_compatible SKILLSPECTOR_COMPAT_BASE_URL=<url> SKILLSPECTOR_COMPAT_API_KEY=<key> SKILLSPECTOR_MODEL=<model>
export SKILL_SCANNER_LLM_BASE_URL=<url> SKILL_SCANNER_LLM_API_KEY=<key> SKILL_SCANNER_LLM_MODEL=<model>
export LLM_BASE_URL=<url> LLM_API_KEY=<key> LLM_MODEL=<model>
bash extension/run_scanner.sh "$EXP" $ID $A --arm skillspector-combined --adapter skillspector        --repeats 5 -- --config combined
bash extension/run_scanner.sh "$EXP" $ID $A --arm cisco-skill-combined  --adapter cisco-skill-scanner --repeats 5 -- --config combined
bash extension/run_scanner.sh "$EXP" $ID $A --arm cisco-skill-judge     --adapter cisco-skill-scanner --repeats 5 -- --config judge-only
bash extension/run_scanner.sh "$EXP" $ID $A --arm aig-skill             --adapter aig-skill-scan      --repeats 5 -- --config judge-only

# Then: findings.jsonl + labels.jsonl -> verdicts.jsonl (score_assets.build_verdicts_from_findings), and
python3 extension/score_assets.py "$EXP/verdicts.jsonl" --by config,stratum --out "$EXP/summary.md" --json "$EXP/summary.json"
```
For MCP servers the arms are `cisco-mcp-scanner` (`--config static-only|judge-only|combined|behavioral`)
and `aig-mcp-scan` (`--config judge-only`); Cisco mcp-scanner reads `MCP_SCANNER_LLM_BASE_URL`,
`MCP_SCANNER_LLM_API_KEY` and `MCP_SCANNER_LLM_MODEL`. The Cisco tools route through LiteLLM, so a
custom endpoint needs a prefixed model name such as `openai/<model>`. The variables above were
exercised here only against the mock model, and for SkillSpector only as far as its failure path;
check each tool's provider docs before a real run.

### Read before comparing these scanners
A table of TPR/FPR hides the following. State them next to any result.

1. **Tencent's scanners are LLM-only.** There is no rule-based Tencent arm, so a "static" comparison
   has two tools and a "best mode" comparison puts one tool that always uses a model against tools
   whose keyless mode you may have run. Compare like with like, and use one model for every
   model-backed arm. Out of the box the models differ: SkillSpector defaults to an NVIDIA-hosted
   model, Cisco skill-scanner to `claude-sonnet-5-5`, Cisco mcp-scanner to `gpt-4o`, Tencent to
   DeepSeek models through openrouter.ai.
2. **The tools' own defaults are not the same mode.** SkillSpector runs its LLM stage unless told
   `--no-llm`; Cisco skill-scanner runs rules only unless told `--use-llm`; Cisco mcp-scanner
   defaults to `api,yara,llm`. These adapters default to the keyless mode; name the config in the
   arm label.
3. **Default rule sets differ.** SkillSpector's static stage includes AST and taint analysis.
   Cisco skill-scanner's default leaves its dataflow analyzer (`--use-behavioral`), optional rule
   packs (`--rule-packs`) and stricter policies (`--policy strict`) off. A comparison at defaults
   compares the vendors' choices of default as much as their detection.
4. **For MCP, the tools read different inputs.** Cisco's offline configs read the tool
   descriptions a server advertises; Tencent's scanner and Cisco's `behavioral` config read source
   code. A server with clean descriptions and malicious code can only be caught by the latter, and
   the reverse. An asset set for both needs both a `tools.json` and the source.
5. **Severity scales differ, and the verdict depends on the gate.** An asset flags when it has a
   finding at or above the gate passed to `build_verdicts_from_findings` (its default, `low`,
   flags on any finding above info). Cisco mcp-scanner has no
   critical level and gives one rolled-up severity per analyzer and item. Tencent severities are
   written by the model. SkillSpector and Cisco skill-scanner emit medium and low findings about
   hygiene (undeclared tool scope, undeclared network use) that are not claims of malice. Use the
   same gate for every arm and report which one; reading the table at two gates shows how much of
   a difference is the gate.
6. **A failed run is logged, not scored as clean.** `run_scanner.sh` records every run in
   `runs.jsonl` as `ok` or `failed`; pass `--runs` to `score_assets.py` so failed runs are
   excluded and counted. Without `--runs` a run with no findings reads as clean, so check first. With the adapters in this section a failed
   run has no `findings.sarif`:
   `for d in "$EXP"/results/*/*/run*; do [ -f "$d/findings.sarif" ] || echo "FAILED $d"; done`
7. **The synthetic mutants leak intent in comments.** `mutate_skill.py --class staged_fetch` writes
   a script whose comments say what it is. A model reads comments; a rule does not. That flatters
   model-backed arms on that class.
8. **Versions move.** Unpinned `uvx` fetches the latest release, and these projects release often.
   Pin with `<PREFIX>_SPEC` and record the version (the adapters store what the tool reports in
   `runs[].properties.adapter` of `findings.sarif` where the tool has a `--version`).
9. **Tool behaviours that look like results.** Seen at the versions above:
   - SkillSpector exits 1 for a risk score above 50, and reports an incomplete analysis as a HIGH
     finding (`AE1`). When model replies are unusable it reports the static findings and marks
     the analysis `partial` (the `combined` config fails on that mark).
   - Cisco skill-scanner exits 0 with rule findings plus an INFO `LLM_ANALYSIS_FAILED` result when
     it cannot use the model's reply (the adapter fails on that result).
   - Cisco mcp-scanner runs YARA alone when the LLM key is missing (the adapter fails), and drops
     a tool from a `behavioral` report when it cannot use the model reply for it (the adapter
     fails when every tool was dropped; a partly dropped list is not detected).
   - aig-mcp-scan carries on with a placeholder reply after failed model calls (the adapter
     stops it). aig-skill-scan returns a clean result when the model gives a risk verdict whose
     findings it cannot parse; it only logs a warning, and the adapter does NOT detect that case.
   These checks are tied to the versions tested. A new release can add another quiet fallback.
10. **Data leaves the machine in model-backed configs**: file contents go to the configured
    provider. SkillSpector also sends declared dependency names to api.osv.dev in `static-only`.

## Add your own
Copy `yara.sh`, change the invocation and the →SARIF step. Any classifier works: PickleScan,
guardrails-based skill scanners, a commercial model-supply-chain tool. For a tool with LLM modes,
copy `cisco-skill-scanner.sh` instead: it shows the `--config` switch, pass-through arguments and
the failure handling above. `_common.sh` holds the shared shell helpers and is not an adapter.
