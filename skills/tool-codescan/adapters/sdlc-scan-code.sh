#!/usr/bin/env bash
# ai-security-sdlc `scan-code` LLM reviewer adapter — the sdlc plugin as ONE tool to compare,
# not the identity of this skill. Nondeterministic → run with --repeats 3.
#   adapters/sdlc-scan-code.sh <tree> <out-dir> [--model M]
# Env: AISEC_GATEWAY_BASE_URL, AISEC_GATEWAY_API_KEY, AISEC_MODEL (or --model).
set -euo pipefail
tree="${1:?}"; out="${2:?}"; shift 2
model="${AISEC_MODEL:-}"
while [ $# -gt 0 ]; do case "$1" in --model) model="$2"; shift 2;; *) shift;; esac; done
here="$(cd "$(dirname "$0")/.." && pwd)"
scan_dir=$(bash "$here/lib/find_sdlc.sh" --plugin code-scan --skill scan-code)
AISEC_MODEL="$model" python3 "$scan_dir/scripts/run_scan.py" --path "$tree" --out "$out"
sarif=$(ls "$out"/*.sarif | head -1); [ "$sarif" = "$out/findings.sarif" ] || cp "$sarif" "$out/findings.sarif"
