#!/usr/bin/env bash
# Cisco AI Defense mcp-scanner (https://github.com/cisco-ai-defense/mcp-scanner, Apache-2.0,
# PyPI cisco-ai-mcp-scanner), driven directly. ONE scanner to compare. It has no SARIF output:
# this adapter takes its raw JSON and converts it with scan_report_to_sarif.py.
#
#   adapters/cisco-mcp-scanner.sh <mcp-server-dir|tools.json> <out-dir>
#        [--config static-only|judge-only|combined|behavioral] [--tools F] [--prompts F] [--resources F]
#        [--in-place] [any other global mcp-scanner option, passed through before the subcommand]
#
# What is scanned depends on the config, and the two inputs are not the same thing:
#   static-only | judge-only | combined  scan a saved MCP list-tools response (JSON with a "tools"
#       array: names, descriptions, input schemas) with the offline `static` subcommand. The server
#       is never started and its source code is NOT read. Default file: <asset>/tools.json.
#       --prompts / --resources add saved list-prompts / list-resources responses.
#   behavioral  reads the server's SOURCE CODE (`mcp-scanner behavioral <dir>`) and asks an LLM
#       whether each tool does what its docstring says. No offline form.
#
# --config static-only  (default) `--analyzers yara`. No key, no network, deterministic.
# --config judge-only   `--analyzers llm`.
# --config combined     `--analyzers yara,llm`.
# --config behavioral   source-code alignment check, LLM only.
# LLM configs need MCP_SCANNER_LLM_API_KEY and MCP_SCANNER_LLM_MODEL (optionally
# MCP_SCANNER_LLM_BASE_URL), or cloud credentials for Bedrock. The tool's own default analyzer
# list also has `api` (Cisco AI Defense cloud API, MCP_SCANNER_API_KEY); no config here uses it,
# add `--analyzers yara,llm,api` after the config to include it.
#
# Two behaviours of the tool that this adapter turns into failures instead of clean results:
#   - with no LLM key, `--analyzers yara,llm` prints a warning, runs YARA alone and exits 0;
#   - `behavioral` drops a tool whose model reply it cannot use and exits 0 with an empty list.
#
# Install: pip install cisco-ai-mcp-scanner   (Python >= 3.11.4)
# Tool location: CISCO_MCP_SCANNER_BIN, or CISCO_MCP_SCANNER_SPEC (a uvx requirement such as
# 'cisco-ai-mcp-scanner==4.8.7'), or `mcp-scanner` on PATH, or uvx with the unpinned package.
# Exit codes of the tool: 0 scan done (findings do not change it), 1 error.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/_common.sh"
asset="${1:?asset path}"; out="${2:?out dir}"; shift 2
config="static-only"; in_place=0; tools=""; prompts=""; resources=""; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="${2:?}"; shift 2;;
    --tools) tools="${2:?}"; shift 2;;
    --prompts) prompts="${2:?}"; shift 2;;
    --resources) resources="${2:?}"; shift 2;;
    --in-place) in_place=1; shift;;
    *) extra+=("$1"); shift;;
  esac
done
case "$config" in
  static-only) analyzers="yara"; require=(yara);;
  judge-only)  analyzers="llm"; require=(llm);;
  combined)    analyzers="yara,llm"; require=(yara llm);;
  behavioral)  analyzers=""; require=(behavioral);;
  *) echo "unknown --config $config (static-only|judge-only|combined|behavioral)" >&2; exit 2;;
esac
mkdir -p "$out"; out="$(stb_abs "$out")"
stb_find_tool CISCO_MCP_SCANNER mcp-scanner cisco-ai-mcp-scanner
stb_stage_asset "$asset" "$in_place"
raw="$(stb_fresh_raw "$out")"
req=(); for a in "${require[@]}"; do req+=(--require-analyzer "$a"); done

conv=()
rc=0
if [ "$config" = "behavioral" ]; then
  [ -d "$STB_ASSET" ] || [ -f "$STB_ASSET" ] || { echo "behavioral needs a source file or directory" >&2; exit 1; }
  # `--format raw` must follow the subcommand here: the subcommand has its own --format.
  (cd "$raw" && "${STB_TOOL[@]}" ${extra[@]+"${extra[@]}"} behavioral "$STB_ASSET" --format raw \
      > "$raw/mcp-scanner.json" 2> "$raw/mcp-scanner.stderr") || rc=$?
else
  # Explicit files are used as given; the default is tools.json inside the (staged) asset.
  if [ -z "$tools" ]; then
    if [ -f "$STB_ASSET" ]; then tools="$STB_ASSET"; else tools="$STB_ASSET/tools.json"; fi
  else tools="$(stb_abs "$tools")"; fi
  if [ ! -f "$tools" ] && [ -z "$prompts" ] && [ -z "$resources" ]; then
    echo "no tools.json in the asset: save the server's MCP list-tools response as <asset>/tools.json," >&2
    echo "pass --tools <file>, or use --config behavioral to read the source code instead" >&2
    exit 1
  fi
  sub=(); [ -f "$tools" ] && { sub+=(--tools "$tools"); conv+=(--tools-file "$tools"); }
  [ -n "$prompts" ] && { prompts="$(stb_abs "$prompts")"; sub+=(--prompts "$prompts"); conv+=(--prompts-file "$prompts"); }
  [ -n "$resources" ] && { resources="$(stb_abs "$resources")"; sub+=(--resources "$resources"); conv+=(--resources-file "$resources"); }
  (cd "$raw" && "${STB_TOOL[@]}" --analyzers "$analyzers" --format raw ${extra[@]+"${extra[@]}"} static "${sub[@]}" \
      > "$raw/mcp-scanner.json" 2> "$raw/mcp-scanner.stderr") || rc=$?
fi
cat "$raw/mcp-scanner.stderr" >&2 || true
if [ "$rc" -ne 0 ]; then
  echo "mcp-scanner failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
root="$STB_ASSET"; [ -d "$root" ] || root="$(dirname "$root")"
python3 "$here/scan_report_to_sarif.py" cisco-mcp "$raw/mcp-scanner.json" "$out/findings.sarif" \
  --asset-root "$root" ${conv[@]+"${conv[@]}"} "${req[@]}" \
  --meta adapter=cisco-mcp-scanner --meta "config=$config" --meta "analyzers=${analyzers:-behavioral}"
