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
# Install: uv tool install git+https://github.com/NVIDIA/skillspector.git   (Python >= 3.12; the README
# documents the git install only, and pypi.org had no `skillspector` project on 2026-11-14)
# Tool location: SKILLSPECTOR_BIN, or SKILLSPECTOR_SPEC (a uvx requirement such as
# 'git+https://github.com/NVIDIA/skillspector.git@<commit>'), or `skillspector` on PATH.
#
# Exit codes of the tool: 0 risk score <= 50, 1 risk score > 50 (findings, not a failure),
# 2 error. With an LLM requested and no usable provider it exits 2, and on some inputs still
# writes a report whose only result is AE1 "not completely inspected" at HIGH. This adapter
# fails on exit 2 and records nothing, so a missing key never turns into a flag or a clean.
# With a provider configured but its replies unusable, the tool exits 0 or 1 with the static
# findings and marks the analysis `partial`; in `combined` the adapter fails on that mark, so a
# run that was in effect static-only is not recorded as a combined one.
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
# Start from an empty run dir: a stale findings.sarif must not survive a failed run.
mkdir -p "$out"; out="$(stb_abs "$out")"; raw="$(stb_fresh_raw "$out")"
case "$config" in
  static-only) mode=(--no-llm); check=();;
  combined)    mode=(); check=(--require-complete);;
  judge-only)  echo "skillspector has no LLM-only mode; use --config static-only or combined" >&2; exit 2;;
  *) echo "unknown --config $config (static-only|combined)" >&2; exit 2;;
esac
stb_find_tool SKILLSPECTOR skillspector
stb_stage_asset "$asset" "$in_place"
version="$("${STB_TOOL[@]}" --version 2>/dev/null | tail -1 || true)"

rc=0
(cd "$raw" && NO_COLOR=1 "${STB_TOOL[@]}" scan "$STB_ASSET" --format sarif --output "$raw/skillspector.sarif" \
    ${mode[@]+"${mode[@]}"} ${extra[@]+"${extra[@]}"}) || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
  echo "skillspector failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
[ -s "$raw/skillspector.sarif" ] || { echo "skillspector wrote no SARIF (exit $rc)" >&2; exit 1; }
python3 "$here/scan_report_to_sarif.py" normalize "$raw/skillspector.sarif" "$out/findings.sarif" \
  --tool skillspector --asset-root "$STB_ASSET" ${check[@]+"${check[@]}"} \
  --meta adapter=skillspector --meta "config=$config" --meta "tool_version=$version" --meta "tool_exit=$rc"
