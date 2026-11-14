#!/usr/bin/env bash
# Shared helpers for the third-party scanner adapters in this folder (aig-*, cisco-*, skillspector).
# Sourced, never run: it is not an adapter and run_scanner.sh never calls it.
#
#   . "$here/_common.sh"
#   stb_abs <path>                       -> prints the absolute path
#   stb_stage_asset <asset> [in-place]   -> sets STB_ASSET (what the scanner is pointed at)
#   stb_find_tool <ENV_PREFIX> <binary> [uvx-spec]  -> sets the array STB_TOOL
#   stb_fresh_raw <out-dir>              -> empties and prints <out-dir>/raw
#
# Why the asset is staged: mutate_skill.py writes a `.label.json` into every mutant that states
# the expected label. A scanner that reads it (an LLM judge) or reports it (a hidden-file rule)
# would be scored on the harness's own answer key, and only on the malicious side. The staged copy
# is the asset without that one file. Pass --in-place to an adapter to scan the path as given.

stb_abs() {
  if [ -d "$1" ]; then (cd "$1" && pwd -P)
  else echo "$(cd "$(dirname "$1")" && pwd -P)/$(basename "$1")"; fi
}

stb_stage_asset() {
  local asset="$1" in_place="${2:-0}" name
  [ -e "$asset" ] || { echo "asset not found: $asset" >&2; return 1; }
  asset="$(stb_abs "$asset")"
  if [ "$in_place" = "1" ]; then STB_ASSET="$asset"; return 0; fi
  STB_TMP="$(mktemp -d)"
  trap 'rm -rf "$STB_TMP"' EXIT
  name="$(basename "$asset")"
  if [ -d "$asset" ]; then
    mkdir "$STB_TMP/$name"
    cp -R "$asset/." "$STB_TMP/$name/"
    rm -f "$STB_TMP/$name/.label.json"
  else
    cp "$asset" "$STB_TMP/$name"
  fi
  STB_ASSET="$STB_TMP/$name"
}

# Resolution order: <PREFIX>_BIN (a path) > <PREFIX>_SPEC (a pip requirement run through uvx,
# e.g. 'cisco-ai-skill-scanner==2.3.2', the way to pin a version) > the binary on PATH >
# uvx with the default spec, when one is given.
stb_find_tool() {
  local prefix="$1" bin="$2" default_spec="${3:-}"
  local bin_var="${prefix}_BIN" spec_var="${prefix}_SPEC"
  if [ -n "${!bin_var:-}" ]; then
    [ -x "${!bin_var}" ] || { echo "$bin_var=${!bin_var} is not executable" >&2; return 1; }
    STB_TOOL=("${!bin_var}")
  elif [ -n "${!spec_var:-}" ]; then
    command -v uvx >/dev/null || { echo "$spec_var is set but uvx is not installed (pip install uv)" >&2; return 1; }
    STB_TOOL=(uvx --from "${!spec_var}" "$bin")
  elif command -v "$bin" >/dev/null 2>&1; then
    STB_TOOL=("$bin")
  elif [ -n "$default_spec" ] && command -v uvx >/dev/null 2>&1; then
    STB_TOOL=(uvx --from "$default_spec" "$bin")
  else
    echo "$bin not found: install it, or set $bin_var to its path${default_spec:+, or install uv so uvx can fetch $default_spec}" >&2
    return 1
  fi
}

stb_fresh_raw() {
  local raw="$1/raw"
  rm -rf "$raw"; mkdir -p "$raw"
  rm -f "$1/findings.sarif"
  echo "$raw"
}
