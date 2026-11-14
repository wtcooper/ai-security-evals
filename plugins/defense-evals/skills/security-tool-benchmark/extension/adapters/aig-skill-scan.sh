#!/usr/bin/env bash
# Tencent AI-Infra-Guard skill scanner, the standalone `aig-skill-scan` CLI
# (https://github.com/Tencent/AI-Infra-Guard, folder skill-scan; Apache-2.0; PyPI aig-skill-scan).
# ONE scanner to compare. Scans an agent skill directory.
#
#   adapters/aig-skill-scan.sh <skill-dir> <out-dir> [--config judge-only] [--in-place]
#                              [any other aig-skill-scan option, passed through: -m MODEL -u BASE_URL ...]
#
# --config judge-only   (default, and the only mode) the tool is an LLM agent that audits the skill
#                       with file-reading tools; there is no static-only mode and nothing runs
#                       without a model. static-only and combined are rejected.
# Needs LLM_API_KEY (or OPENAI_API_KEY) for an OpenAI-compatible endpoint. The tool's defaults are
# model `deepseek-v4-flash` at https://openrouter.ai/api/v1; set LLM_MODEL / LLM_BASE_URL or pass
# -m / -u. File contents are sent to that endpoint. Nondeterministic: repeat runs.
#
# This adapter passes `--language en` (the tool's default is zh) and runs the tool from an empty
# directory, because the tool loads a `.env` from its working directory.
#
# Install: pip install aig-skill-scan   (Python >= 3.9)
# Tool location: AIG_SKILL_SCAN_BIN, or AIG_SKILL_SCAN_SPEC (a uvx requirement such as
# 'aig-skill-scan==0.2.2'), or `aig-skill-scan` on PATH, or uvx with the unpinned package.
# Exit codes of the tool: 0 scan done (findings do not change it), 1 error (no key, bad path,
# model call failed).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/_common.sh"
asset="${1:?asset path}"; out="${2:?out dir}"; shift 2
config="judge-only"; in_place=0; extra=(); has_key_arg=0
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="${2:?}"; shift 2;;
    --in-place) in_place=1; shift;;
    -k|--api_key) has_key_arg=1; extra+=("$1"); shift;;
    *) extra+=("$1"); shift;;
  esac
done
case "$config" in
  judge-only) ;;
  static-only|combined) echo "aig-skill-scan is LLM-only: it has no $config mode; use --config judge-only" >&2; exit 2;;
  *) echo "unknown --config $config (judge-only)" >&2; exit 2;;
esac
if [ "$has_key_arg" -eq 0 ] && [ -z "${LLM_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "aig-skill-scan needs a model key: set LLM_API_KEY (or OPENAI_API_KEY)" >&2; exit 1
fi
mkdir -p "$out"; out="$(stb_abs "$out")"
stb_find_tool AIG_SKILL_SCAN aig-skill-scan aig-skill-scan
stb_stage_asset "$asset" "$in_place"
[ -d "$STB_ASSET" ] || { echo "aig-skill-scan needs a skill directory, got a file" >&2; exit 1; }
raw="$(stb_fresh_raw "$out")"

rc=0
(cd "$raw" && "${STB_TOOL[@]}" --repo "$STB_ASSET" --language en -o "$raw/aig-skill-scan.sarif" \
    ${extra[@]+"${extra[@]}"}) || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "aig-skill-scan failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
[ -s "$raw/aig-skill-scan.sarif" ] || { echo "aig-skill-scan wrote no SARIF" >&2; exit 1; }
python3 "$here/scan_report_to_sarif.py" normalize "$raw/aig-skill-scan.sarif" "$out/findings.sarif" \
  --tool aig-skill-scan --asset-root "$STB_ASSET" \
  --meta adapter=aig-skill-scan --meta "config=$config"
