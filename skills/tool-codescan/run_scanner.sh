#!/usr/bin/env bash
# Run ONE code scanner (an adapter) N times over a target tree and append normalised rows
# (tool=<arm>, tool_run=r) to <EXP>/findings.jsonl. The harness is scanner-agnostic: the only
# scanner-specific code lives in adapters/<arm>.sh, which the user picks in PLAN. Ship your own
# adapter for any tool you want to compare (see adapters/README.md for the 1-function contract).
#
#   bash run_scanner.sh <EXP> <target-id> <tree> --arm <adapter> [--repeats N] [-- <adapter args>]
#
# Deterministic scanners (CodeQL, Semgrep) want --repeats 1; nondeterministic LLM reviewers
# want --repeats 3 so we can report run-to-run flip rate and cost.
set -euo pipefail
exp="${1:?}"; tid="${2:?}"; tree="${3:?}"; shift 3
arm=""; adapter=""; repeats=1; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --arm) arm="$2"; shift 2;;
    --adapter) adapter="$2"; shift 2;;
    --repeats) repeats="$2"; shift 2;;
    --) shift; extra=("$@"); break;;
    *) echo "unknown $1" >&2; exit 2;;
  esac
done
[ -n "$arm" ] || { echo "--arm <name> required (see adapters/)" >&2; exit 2; }
[ -n "$adapter" ] || adapter="$arm"
here="$(cd "$(dirname "$0")" && pwd)"
ad="$here/adapters/$adapter.sh"
[ -f "$ad" ] || { echo "no adapter '$adapter' — write adapters/$adapter.sh from adapters/README.md" >&2; exit 1; }
run=$(basename "$exp"); out="$exp/results/$arm/$tid"; mkdir -p "$out"
t0=$(date +%s)
for r in $(seq 1 "$repeats"); do
  d="$out/run$r"; mkdir -p "$d"
  if ! bash "$ad" "$tree" "$d" "${extra[@]}" > "$d/adapter.log" 2>&1; then
    echo "  run$r: adapter '$arm' failed (see $d/adapter.log)" >&2; continue
  fi
  sarif=$(ls "$d"/*.sarif 2>/dev/null | head -1)
  [ -n "$sarif" ] || { echo "  run$r: adapter produced no *.sarif in $d" >&2; continue; }
  python3 "$here/lib/sarif_to_findings.py" "$sarif" --tool "$arm" --tool-run "$r" --strip-prefix "$tree" \
      --run "$run" --arm "$arm" --target "$tid" --sample 1 --append "$exp/findings.jsonl"
done
kloc=$(find "$tree" -type f \( -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.go' -o -name '*.java' -o -name '*.rb' -o -name '*.php' -o -name '*.c' -o -name '*.cpp' \) -not -path '*/node_modules/*' -exec cat {} + 2>/dev/null | wc -l | awk '{printf "%.1f", $1/1000}')
python3 "$here/lib/manifest.py" "$exp" append-sample "{\"run\":\"$run\",\"arm\":\"$arm\",\"target\":\"$tid\",\"sample\":1,\"kloc\":$kloc,\"wall_s\":$(( $(date +%s)-t0 )),\"repeats\":$repeats}" >/dev/null
echo "SCANNED=$tid arm=$arm kloc=$kloc repeats=$repeats"
