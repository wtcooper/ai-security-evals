#!/usr/bin/env bash
# Tencent AI-Infra-Guard MCP scanner, the standalone `aig-mcp-scan` CLI
# (https://github.com/Tencent/AI-Infra-Guard, folder mcp-scan; Apache-2.0; PyPI aig-mcp-scan).
# ONE scanner to compare. Scans the SOURCE DIRECTORY of an MCP server; the server is not started.
#
#   adapters/aig-mcp-scan.sh <mcp-server-dir> <out-dir> [--config judge-only] [--in-place]
#                            [any other aig-mcp-scan option, passed through: -m MODEL -u BASE_URL ...]
#
# --config judge-only   (default, and the only mode) an LLM agent audits the source. A regex
#                       pre-scan feeds the agent's prompt but cannot be run on its own, so there
#                       is no static-only mode. static-only and combined are rejected.
# Needs LLM_API_KEY (or OPENAI_API_KEY / OPENROUTER_API_KEY) for an OpenAI-compatible endpoint.
# The tool's defaults are model `deepseek/deepseek-v3.2-exp` at https://openrouter.ai/api/v1; set
# LLM_MODEL / LLM_BASE_URL or pass -m / -u. Source files are sent to that endpoint.
# Nondeterministic: repeat runs. Do not pass --server_url: that connects to a running server and
# writes the tool's own JSON, not SARIF.
#
# This adapter passes `--language en` (the tool's default is zh) and runs the tool from an empty
# directory, because the tool loads a `.env` from its working directory. When the tool marks its
# own result `possibly-incomplete` (the agent ended with no output), the adapter fails instead of
# recording a clean asset.
#
# Install: pip install aig-mcp-scan   (Python >= 3.10)
# Tool location: AIG_MCP_SCAN_BIN, or AIG_MCP_SCAN_SPEC (a uvx requirement such as
# 'aig-mcp-scan==0.2.0'), or `aig-mcp-scan` on PATH, or uvx with the unpinned package.
# Exit codes of the tool: 0 scan done (findings do not change it), 1 error.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/_common.sh"
asset="${1:?asset path}"; out="${2:?out dir}"; shift 2
config="judge-only"; in_place=0; extra=(); has_key_arg=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="${2:?}"; shift 2;;
    --in-place) in_place=1; shift;;
    --server_url) echo "--server_url is not supported by this adapter (no SARIF in that mode)" >&2; exit 2;;
    -k|--api_key) has_key_arg=1; extra+=("$1"); shift;;
    *) extra+=("$1"); shift;;
  esac
done
case "$config" in
  judge-only) ;;
  static-only|combined) echo "aig-mcp-scan is LLM-only: it has no $config mode; use --config judge-only" >&2; exit 2;;
  *) echo "unknown --config $config (judge-only)" >&2; exit 2;;
esac
if [ "$has_key_arg" -eq 0 ] && [ -z "${LLM_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "aig-mcp-scan needs a model key: set LLM_API_KEY (or OPENAI_API_KEY / OPENROUTER_API_KEY)" >&2; exit 1
fi
mkdir -p "$out"; out="$(stb_abs "$out")"
stb_find_tool AIG_MCP_SCAN aig-mcp-scan aig-mcp-scan
stb_stage_asset "$asset" "$in_place"
[ -d "$STB_ASSET" ] || { echo "aig-mcp-scan needs an MCP server source directory, got a file" >&2; exit 1; }
raw="$(stb_fresh_raw "$out")"

rc=0
(cd "$raw" && "${STB_TOOL[@]}" --repo "$STB_ASSET" --language en -o "$raw/aig-mcp-scan.sarif" \
    ${extra[@]+"${extra[@]}"}) || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "aig-mcp-scan failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
[ -s "$raw/aig-mcp-scan.sarif" ] || { echo "aig-mcp-scan wrote no SARIF" >&2; exit 1; }
python3 "$here/scan_report_to_sarif.py" normalize "$raw/aig-mcp-scan.sarif" "$out/findings.sarif" \
  --tool aig-mcp-scan --asset-root "$STB_ASSET" \
  --meta adapter=aig-mcp-scan --meta "config=$config"
