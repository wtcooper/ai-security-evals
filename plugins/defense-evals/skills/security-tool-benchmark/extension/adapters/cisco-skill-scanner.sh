#!/usr/bin/env bash
# Cisco AI Defense skill-scanner (https://github.com/cisco-ai-defense/skill-scanner, Apache-2.0,
# PyPI cisco-ai-skill-scanner), driven directly rather than through a wrapper. ONE scanner to compare.
# Scans an agent skill directory that holds a SKILL.md.
#
#   adapters/cisco-skill-scanner.sh <skill-dir> <out-dir> [--config static-only|judge-only|combined]
#                                   [--in-place] [any other `skill-scanner scan` option, passed through]
#
# --config static-only  (default) the tool's default analyzers: static (YAML + YARA rules), bytecode,
#                       pipeline, correlation. No key, no network. Deterministic for a fixed version.
#                       The dataflow analyzer is off by default in the tool; add --use-behavioral
#                       to include it.
# --config combined     static analyzers plus `--use-llm` (the LLM judge).
# --config judge-only   `--use-llm` with a scan policy that turns the static, bytecode, pipeline
#                       and correlation analyzers off, so only the judge reports. A --policy you
#                       pass through replaces that policy (the last --policy wins).
# LLM configs need SKILL_SCANNER_LLM_API_KEY and SKILL_SCANNER_LLM_MODEL (or cloud credentials).
# With --use-llm and no usable key the tool exits 2 and writes nothing; it does not fall back.
#
# Install: pip install cisco-ai-skill-scanner   (Python >= 3.11)
# Tool location: CISCO_SKILL_SCANNER_BIN, or CISCO_SKILL_SCANNER_SPEC (a uvx requirement such as
# 'cisco-ai-skill-scanner==2.3.2'), or `skill-scanner` on PATH, or uvx with the unpinned package.
#
# Exit codes of the tool: 0 scan done (findings do not change it unless you pass a --fail-on-*
# option), 1 runtime error or a --fail-on-* threshold met, 2 configuration error.
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
case "$config" in static-only|judge-only|combined) ;; *) echo "unknown --config $config (static-only|judge-only|combined)" >&2; exit 2;; esac
mkdir -p "$out"; out="$(stb_abs "$out")"
stb_find_tool CISCO_SKILL_SCANNER skill-scanner cisco-ai-skill-scanner
stb_stage_asset "$asset" "$in_place"
raw="$(stb_fresh_raw "$out")"
version="$("${STB_TOOL[@]}" --version 2>/dev/null | tail -1 || true)"

mode=()
case "$config" in
  combined) mode=(--use-llm);;
  judge-only)
    printf 'analyzers:\n  static: false\n  bytecode: false\n  pipeline: false\n  correlation: false\n' > "$raw/judge-only-policy.yaml"
    mode=(--use-llm --policy "$raw/judge-only-policy.yaml");;
esac

rc=0
(cd "$raw" && NO_COLOR=1 "${STB_TOOL[@]}" scan "$STB_ASSET" --format sarif --output-sarif "$raw/skill-scanner.sarif" \
    ${mode[@]+"${mode[@]}"} ${extra[@]+"${extra[@]}"}) || rc=$?
# Exit 1 with a report is a passed-through --fail-on-* threshold; exit 1 without one is a runtime error.
if [ "$rc" -ne 0 ] && { [ "$rc" -ne 1 ] || [ ! -s "$raw/skill-scanner.sarif" ]; }; then
  echo "skill-scanner failed (exit $rc); no findings recorded for this run" >&2; exit 1
fi
[ -s "$raw/skill-scanner.sarif" ] || { echo "skill-scanner wrote no SARIF" >&2; exit 1; }
python3 "$here/scan_report_to_sarif.py" normalize "$raw/skill-scanner.sarif" "$out/findings.sarif" \
  --tool cisco-skill-scanner --asset-root "$STB_ASSET" \
  --meta adapter=cisco-skill-scanner --meta "config=$config" --meta "tool_version=$version" --meta "tool_exit=$rc"
