#!/usr/bin/env bash
# Semgrep adapter. Deterministic → run with --repeats 1.
#   adapters/semgrep.sh <tree> <out-dir> [--config <ruleset>]
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
config="p/security-audit"
while [ $# -gt 0 ]; do case "$1" in --config) config="$2"; shift 2;; *) shift;; esac; done
command -v semgrep >/dev/null || { echo "semgrep not installed (pipx install semgrep)" >&2; exit 1; }
semgrep scan --sarif --output "$out/findings.sarif" --config "$config" --error --quiet "$tree" || true
[ -f "$out/findings.sarif" ]
