#!/usr/bin/env bash
# Locate the ai-security-sdlc repo (the system under test) and print its path + sha:
#   AISEC_SDLC_DIR env  >  a sibling checkout ../ai-security-sdlc of the eval repo  >
#   pinned shallow clone into <cache dir> (default $EXP/.deps or ~/.cache/ai-security-evals).
#
#   eval "$(bash find_sdlc.sh [--cache <dir>] [--ref <git ref>])"   # sets SDLC_DIR, SDLC_SHA
#   bash find_sdlc.sh --plugin code-scan --skill scan-code            # prints the skill dir
#
# Nothing from the sdlc repo is vendored here: it is pinned by ref/sha and recorded in the
# experiment manifest (scorers[].sdlc_sha), so a result is reproducible against that commit.
set -euo pipefail
cache="${AISEC_SDLC_CACHE:-$HOME/.cache/ai-security-evals}"
ref="${AISEC_SDLC_REF:-main}"
plugin=""; skill=""; quiet=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cache) cache="$2"; shift 2;;
    --ref) ref="$2"; shift 2;;
    --plugin) plugin="$2"; shift 2;;
    --skill) skill="$2"; shift 2;;
    --quiet) quiet=1; shift;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done
url="${AISEC_SDLC_URL:-https://github.com/wtcooper/ai-security-sdlc}"

dir=""
if [ -n "${AISEC_SDLC_DIR:-}" ] && [ -d "$AISEC_SDLC_DIR/plugins" ]; then
  dir="$AISEC_SDLC_DIR"
elif top=$(git rev-parse --show-toplevel 2>/dev/null) && [ -d "$top/../ai-security-sdlc/plugins" ]; then
  dir="$(cd "$top/../ai-security-sdlc" && pwd)"
else
  dir="$cache/ai-security-sdlc"
  if [ ! -d "$dir/plugins" ]; then
    mkdir -p "$cache"
    git clone -q --depth 1 --branch "$ref" "$url" "$dir" >&2
  fi
fi
sha=$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo unknown)

if [ -n "$plugin" ]; then
  out="$dir/plugins/$plugin"
  [ -n "$skill" ] && out="$out/skills/$skill"
  [ -d "$out" ] || { echo "not found: $out" >&2; exit 1; }
  echo "$out"
  exit 0
fi
[ $quiet -eq 1 ] || { echo "SDLC_DIR=$dir"; echo "SDLC_SHA=$sha"; }
