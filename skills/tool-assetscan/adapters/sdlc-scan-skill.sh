#!/usr/bin/env bash
# Cisco AI skill-scanner as wired by the ai-security-sdlc `scan-skill` skill — ONE scanner to
# compare. Config selects the static/judge split.
#   adapters/sdlc-scan-skill.sh <skill-dir> <out-dir> [--config static-only|judge-only|combined]
# Env (judge configs): AISEC_GATEWAY_BASE_URL, AISEC_GATEWAY_API_KEY, AISEC_MODEL.
set -euo pipefail
asset="${1:?}"; out="${2:?}"; shift 2
config="combined"
while [ $# -gt 0 ]; do case "$1" in --config) config="$2"; shift 2;; *) shift;; esac; done
command -v uvx >/dev/null || { echo "uvx not installed (pip install uv)" >&2; exit 1; }
flags=""
case "$config" in
  static-only) flags="--no-llm-judge";;
  judge-only)  flags="--no-static";;
  combined)    flags="";;
  *) echo "unknown --config $config" >&2; exit 2;;
esac
uvx --from cisco-ai-skill-scanner skill-scanner scan "$asset" --format sarif --output "$out/findings.sarif" $flags
[ -f "$out/findings.sarif" ]
