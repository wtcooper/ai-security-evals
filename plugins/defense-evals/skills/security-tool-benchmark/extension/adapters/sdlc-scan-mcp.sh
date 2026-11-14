#!/usr/bin/env bash
# ai-security-sdlc `scan-mcp` adapter — ONE scanner to compare.
#   adapters/sdlc-scan-mcp.sh <mcp-server-dir> <out-dir> [--config static-only|judge-only|combined]
set -euo pipefail
asset="${1:?}"; out="${2:?}"; shift 2
config="combined"
while [ $# -gt 0 ]; do case "$1" in --config) config="$2"; shift 2;; *) shift;; esac; done
here="$(cd "$(dirname "$0")/.." && pwd)"
scan_dir=$(bash "$here/lib/find_sdlc.sh" --plugin asset-scan --skill scan-mcp)
# The sdlc scan-mcp skill ships its own runner; invoke it and normalise its SARIF here.
python3 "$scan_dir/scripts/run_scan_mcp.py" --path "$asset" --config "$config" --out "$out"
sarif=$(ls "$out"/*.sarif | head -1); [ "$sarif" = "$out/findings.sarif" ] || cp "$sarif" "$out/findings.sarif"
