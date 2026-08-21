#!/usr/bin/env bash
# Raw YARA signature baseline — the comparator that isolates an LLM-judge's value (what does the
# judge catch that signatures cannot?). Deterministic → --repeats 1.
#   adapters/yara.sh <asset-path> <out-dir> [--rules <dir-or-file>]
set -euo pipefail
asset="${1:?}"; out="${2:?}"; shift 2
rules="${YARA_RULES:-}"
while [ $# -gt 0 ]; do case "$1" in --rules) rules="$2"; shift 2;; *) shift;; esac; done
command -v yara >/dev/null || { echo "yara not installed" >&2; exit 1; }
[ -n "$rules" ] || { echo "--rules <dir-or-file> (or YARA_RULES) required" >&2; exit 1; }
hits=$(yara -r "$rules" "$asset" 2>/dev/null || true)
python3 - "$out/findings.sarif" <<PY
import json,sys
hits="""$hits""".strip().splitlines()
res=[{"ruleId":h.split()[0],"message":{"text":h},"level":"error"} for h in hits if h.strip()]
json.dump({"version":"2.1.0","runs":[{"tool":{"driver":{"name":"yara"}},"results":res}]}, open(sys.argv[1],"w"))
PY
[ -f "$out/findings.sarif" ]
