#!/usr/bin/env bash
# zizmor adapter — static analysis of GitHub Actions workflows (CI/CD supply-chain: injection, excessive
# permissions, unpinned actions, artifact poisoning).
# CLASS: ci-cd, NOT first-party SAST — see adapters/README.md. Deterministic → --repeats 1.
#   adapters/zizmor.sh <tree> <out-dir> [--persona regular|pedantic|auditor] [--online]
# Runs --offline by default (no network, no GH API token needed); pass --online for audits that need it.
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
persona="regular"; offline="--offline"
while [ $# -gt 0 ]; do case "$1" in
  --persona) persona="$2"; shift 2;; --online) offline=""; shift;; *) shift;; esac; done
command -v zizmor >/dev/null || { echo "zizmor not installed (brew install zizmor)" >&2; exit 1; }
# No workflows in the tree is a legitimate empty result, not an error: emit an empty SARIF run.
if [ -z "$(find "$tree" -path '*/.github/workflows/*' \( -name '*.yml' -o -name '*.yaml' \) -print -quit 2>/dev/null)" ]; then
  echo "no .github/workflows/* in $tree — empty result" >&2
  printf '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"zizmor"}},"results":[]}]}\n' > "$out/findings.sarif"
  exit 0
fi
# zizmor writes SARIF to stdout and exits 1 when findings exist — only >1 is a real failure.
set +e
zizmor --format sarif --persona "$persona" $offline "$tree" > "$out/findings.sarif"
code=$?
set -e
[ "$code" -le 1 ] || { echo "zizmor failed (exit $code)" >&2; cat "$out/findings.sarif" >&2; exit "$code"; }
[ -s "$out/findings.sarif" ]
