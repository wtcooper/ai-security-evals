#!/usr/bin/env bash
# NVIDIA SkillSpector (https://github.com/NVIDIA/SkillSpector, Apache-2.0), driven directly.
# ONE scanner to compare. Scans an agent skill: a directory with SKILL.md, a single SKILL.md, or a zip.
#
#   adapters/skillspector.sh <skill-dir|file> <out-dir> [--config static-only|combined] [--in-place]
#                            [any other `skillspector scan` option, passed through]
#
# --config static-only  (default) `--no-llm`: regex, AST, taint and YARA analyzers. No key.
#                       Deterministic for a fixed version, except rule SC4, which looks dependencies
#                       up on api.osv.dev when the skill declares any and falls back to a short
#                       bundled list when that host is unreachable.
# --config combined     the tool's default: static stage plus the LLM stage. Needs a provider:
#                       SKILLSPECTOR_PROVIDER and that provider's key (see `skillspector scan --help`).
#                       File contents are sent to the provider.
# --config judge-only   not available: SkillSpector has no LLM-only switch. Its LLM stage reviews
#                       and adds to the static findings and never removes one.
#
# Install: uv tool install git+https://github.com/NVIDIA/skillspector.git   (Python >= 3.12; not on PyPI)
# Tool location: SKILLSPECTOR_BIN, or SKILLSPECTOR_SPEC (a uvx requirement such as
# 'git+https://github.com/NVIDIA/skillspector.git@<commit>'), or `skillspector` on PATH.
#
# Exit codes of the tool: 0 risk score <= 50, 1 risk score > 50 (findings, not a failure),
# 2 error. With an LLM requested and no usable provider it exits 2; this adapter then fails
# rather than keep the static-only report the tool still writes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "$here/_common.sh"
asset="${1:?asset path}"; out="${2:?out dir}"; shift 2
config="static-only"; in_place=0; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --config) config="${2:?}"; shift 2;;
    --in-place) in_place=1; shift;;
    *) extra+=("$1"); shift;;
  esac
done
case "$config" in
  static-only) mode=(--no-llm);;
  combined)    mode=();;
  judge-only)  echo "skillspector has no LLM-only mode; use --config static-only or combined" >&2; exit 2;;
  *) echo "unknown --config $config (static-only|combined)" >&2; exit 2;;
esac
mkdir -p "$out"; out="$(stb_abs "$out")"
stb_find_tool SKILLSPECTOR skillspector
stb_stage_asset "$asset" "$in_place"
raw="$(stb_fresh_raw "$out")"
version="$("${STB_TOOL[@]}" --version 2>/dev/null | tail -1 || true)"

rc=0
(cd "$raw" && NO_COLOR=1 "${STB_TOOL[@]}" scan "$STB_ASSET" --format sarif --output "$raw/skillspector.sarif" \
    ${mode[@]+"${mode[@]}"} ${extra[@]+"${extra[@]}"}) || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
  echo "skillspector failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
[ -s "$raw/skillspector.sarif" ] || { echo "skillspector wrote no SARIF (exit $rc)" >&2; exit 1; }
python3 "$here/scan_report_to_sarif.py" normalize "$raw/skillspector.sarif" "$out/findings.sarif" \
  --tool skillspector --asset-root "$STB_ASSET" \
  --meta adapter=skillspector --meta "config=$config" --meta "tool_version=$version" --meta "tool_exit=$rc"
