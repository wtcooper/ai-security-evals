# Code-scanner adapters — the only scanner-specific code in this skill

This harness is **scanner-agnostic**. Ground truth, matching (`match.py`), and stats
(`lib/evalstats.py`) never know which scanner produced a finding. All a scanner needs is an
adapter here; `run_scanner.sh --arm <name>` drives `adapters/<name>.sh`.

## Contract (one function)
```
bash adapters/<name>.sh <target-tree> <out-dir> [extra args...]
```
- Scan the code under `<target-tree>`.
- Write SARIF 2.1.0 to `<out-dir>/findings.sarif` (any `*.sarif` in `<out-dir>` is picked up).
- Exit non-zero only on a real failure (findings present is success).

That is the whole interface. `run_scanner.sh` normalises the SARIF into the `findings.jsonl`
contract with `--tool <name>`, so the tool label in every report is your adapter's name.

## Shipped reference adapters
| adapter | tool | needs | notes |
|---|---|---|---|
| `semgrep.sh` | Semgrep | `semgrep` | `--config` overridable; deterministic → `--repeats 1` |
| `codeql.sh` | CodeQL CLI (local) | `codeql`, source-language build | deterministic → `--repeats 1` |
| `sdlc-scan-code.sh` | ai-security-sdlc LLM reviewer | the sdlc plugin (`lib/find_sdlc.sh`), gateway env | nondeterministic → `--repeats 3` |

`codeql.sh` runs the CodeQL **CLI locally** — no GitHub. To instead score CodeQL through GitHub
code-scanning (so the agent never sees the scanner config), use `ephemeral_repo.sh` + a
`workflow_dispatch` run and normalise the alerts with `lib/sarif_to_findings.py --format gh-alerts`
(see SKILL.md → RUN). Both paths produce the same `findings.jsonl` rows.

## Add your own
Copy `semgrep.sh`, change the invocation, done. Examples: Snyk Code (`snyk code test --sarif`),
Bandit (`bandit -f sarif`), a commercial SAST, or another LLM reviewer. Nondeterministic tools
(LLMs) should be run with `--repeats 3+` so the flip-rate / κ columns are meaningful.
