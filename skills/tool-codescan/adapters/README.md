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
- Exit non-zero only on a real failure. Tools that exit 1 *because they found something* (osv-scanner,
  zizmor) must swallow that — findings are a result, not an error.

That is the whole interface. `run_scanner.sh` normalises the SARIF into the `findings.jsonl`
contract with `--tool <name>`, so the tool label in every report is your adapter's name.

## Shipped reference adapters
| adapter | tool | class | needs | repeats |
|---|---|---|---|---|
| `semgrep.sh` | Semgrep | sast | `semgrep` | 1 (deterministic) |
| `codeql.sh` | CodeQL CLI or `gh codeql` | sast | `codeql` **or** `gh extension install github/gh-codeql` | 1 |
| `sdlc-scan-code.sh` | an LLM code reviewer (ai-security-sdlc `scan-code`) | sast (llm) | the sdlc plugin, gateway env | **3+** (nondeterministic) |
| `trivy.sh` | Trivy | sca + misconfig + secret | `trivy` | 1 |
| `osv-scanner.sh` | osv-scanner | sca | `osv-scanner` | 1 |
| `zizmor.sh` | zizmor | ci-cd (GitHub Actions) | `zizmor` | 1 |

`codeql.sh` runs CodeQL **locally** and auto-detects the language from the dominant supported source
extension (`--language` to override; `CODEQL_BUILD` for compiled languages). To instead score CodeQL
through GitHub code-scanning (so the agent never sees the scanner config), use `ephemeral_repo.sh` +
a `workflow_dispatch` run and normalise with `lib/sarif_to_findings.py --format gh-alerts` (SKILL.md →
RUN). Both paths produce identical `findings.jsonl` rows.

## ⚠️ Compare within a class, complement across classes
The `class` column is not decoration. These tools answer **different questions**, and a single
recall/precision table across all of them is misleading:

- **sast** (semgrep, codeql, an LLM reviewer) finds vulnerabilities in *first-party code*, reported at
  a file/function/line. Ground truth for these is CWE + location.
- **sca** (trivy, osv-scanner) finds *known-vulnerable dependencies*, identified by a **CVE/GHSA
  advisory** and reported at a manifest/lockfile — never at the vulnerable line. `match.py` therefore
  matches these by advisory ID (level `advisory`); matching them on CWE+location would score them 0
  for a harness reason rather than a tool reason.
- **ci-cd** (zizmor) audits GitHub Actions workflows (injection, excessive permissions, unpinned
  actions). Its ground truth is workflow findings — not application CWEs at all.

So: **head-to-head recall is only meaningful within a class.** Across classes, read the *complement*
table — "what does adding trivy to semgrep buy" is a real question; "does trivy beat semgrep" is not.
Make sure the benchmark's `ground_truth.jsonl` actually contains the class of vuln you're scoring, or
the tool will look bad for the wrong reason.

## Add your own
Copy `semgrep.sh`, change the invocation, done. Examples: Snyk Code (`snyk code test --sarif`), Bandit
(`bandit -f sarif`), Grype, a commercial SAST, or another LLM reviewer. Nondeterministic tools (LLMs)
should be run with `--repeats 3+` so the flip-rate / κ columns are meaningful. If your tool has no
SARIF output, convert its native JSON inside the adapter (see `zap.sh` in tool-pentest for a worked
example).
