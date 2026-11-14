# Fixtures for the third-party scanner adapters

Captured on 2026-11-14 from the real tools, for `tests/test_scanner_adapters.py`. Each file is the
tool's own report, unedited, as the adapter receives it before conversion. Versions: SkillSpector
2.12.0 (commit c816150), cisco-ai-skill-scanner 2.3.2, cisco-ai-mcp-scanner 4.8.7,
aig-skill-scan 0.2.2, aig-mcp-scan 0.2.0.

Samples the tools were run on:

- `samples/benign-skill/` — a small benign skill written for these tests. `skill-md.txt` is its
  skill file; the test copies it to the name the scanners expect, because this repo allows that
  file name only at a skill's own root.
- "staged-fetch" — the benign skill passed through `extension/mutate_skill.py --class staged_fetch
  --seed 0` (synthetic, scan-only, local unroutable sink), scanned as a copy without `.label.json`.
- `samples/benign-mcp/` — a two-tool MCP server source file plus its saved list-tools response.
- `samples/poisoned-mcp/` — the same server with a hand-written poisoned `tools.json`. The
  generator's payload strings, appended to a tool description, produced no YARA hit from
  mcp-scanner, so a flagged report needed stronger synthetic text. It is not generator output.

| file | how it was produced |
|---|---|
| `skillspector/clean.sarif` | `skillspector scan <benign> --no-llm --format sarif` (exit 0) |
| `skillspector/flagged-staged-fetch.sarif` | same on the staged-fetch mutant (exit 1: risk score above 50) |
| `skillspector/llm-unavailable.sarif` | `skillspector scan <benign> --format sarif` with no provider key (exit 2; the file was still written) |
| `cisco-skill-scanner/clean.sarif` | `skill-scanner scan <benign> --format sarif` (default analyzers, exit 0) |
| `cisco-skill-scanner/flagged-staged-fetch.sarif` | same on the staged-fetch mutant (exit 0) |
| `cisco-mcp-scanner/clean.json` | `mcp-scanner --analyzers yara --format raw static --tools benign-mcp/tools.json` |
| `cisco-mcp-scanner/flagged-poisoned-tools.json` | same on `poisoned-mcp/tools.json` |
| `cisco-mcp-scanner/llm-requested-but-not-run.json` | `--analyzers yara,llm` on `poisoned-mcp/tools.json` with no LLM key: warning on stderr, exit 0, no `llm_analyzer` entry |
| `cisco-mcp-scanner/behavioral-nothing-analysed.json` | `mcp-scanner behavioral <benign-mcp> --format raw` when the model reply was unusable: exit 0, empty list |
| `cisco-skill-scanner/llm-analysis-failed-mockllm.sarif` | `skill-scanner scan <staged-fetch> --use-llm` with a key set and the mock model answering text that is not JSON: exit 0, rule findings plus one INFO `LLM_ANALYSIS_FAILED` |
| `skillspector/llm-replies-unusable-mockllm.sarif` | `skillspector scan <staged-fetch>` with `SKILLSPECTOR_PROVIDER=openai_compatible` and the same mock: exit 1, static findings, analysis marked `partial` |
| `*-mockllm.*` | the real tool and its real report writer, with the model replaced by `tests/mock_openai_server.py` replaying a file from `mock-replies/`. They show the report shape. They are not evidence of what a model would find. |

No API key was available when these were captured, so there is no fixture from a real model run.
