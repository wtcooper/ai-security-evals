#!/usr/bin/env bash
# ai-security-sdlc `scan-model` adapter — SCAN ONLY, no-network container. ONE scanner to compare.
#   adapters/sdlc-scan-model.sh <model-file> <out-dir> [--config ...]
set -euo pipefail
asset="${1:?}"; out="${2:?}"; shift 2
config="combined"
while [ $# -gt 0 ]; do case "$1" in --config) config="$2"; shift 2;; *) shift;; esac; done
here="$(cd "$(dirname "$0")/.." && pwd)"
docker build -q -t assetscan-model "$here" >/dev/null
docker run --rm --network none -v "$(cd "$(dirname "$asset")" && pwd):/in:ro" -v "$out:/out" \
  assetscan-model scan-model --path "/in/$(basename "$asset")" --config "$config" --out /out
[ -f "$out/findings.sarif" ]
