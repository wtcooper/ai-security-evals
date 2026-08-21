#!/usr/bin/env bash
# Run ONE asset scanner (an adapter) k times over ONE asset (file or dir) and append normalised rows
# (tool=<arm>, tool_run=r) to <EXP>/findings.jsonl. Scanner-agnostic: the only scanner-specific code
# lives in adapters/<adapter>.sh. Model/pickle assets MUST run inside the no-network container
# (that is the adapter's job) — this harness only scans, never executes, a positive.
#
#   bash run_scanner.sh <EXP> <asset-id> <asset-path> --arm <label> [--adapter <file>] [--repeats 5] [-- <adapter args>]
#
# --arm is the label in every report (e.g. scan-skill-combined). --adapter is the script under
# adapters/ (defaults to --arm), so one scanner adapter can back several arms that differ only by a
# config flag passed after `--` (e.g. --config static-only | judge-only | combined).
set -euo pipefail
exp="${1:?}"; aid="${2:?}"; asset="${3:?}"; shift 3
arm=""; adapter=""; repeats=5; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --arm) arm="$2"; shift 2;;
    --adapter) adapter="$2"; shift 2;;
    --repeats) repeats="$2"; shift 2;;
    --) shift; extra=("$@"); break;;
    *) echo "unknown $1" >&2; exit 2;;
  esac
done
[ -n "$arm" ] || { echo "--arm <label> required" >&2; exit 2; }
[ -n "$adapter" ] || adapter="$arm"
here="$(cd "$(dirname "$0")" && pwd)"
ad="$here/adapters/$adapter.sh"
[ -f "$ad" ] || { echo "no adapter '$adapter' — write adapters/$adapter.sh from adapters/README.md" >&2; exit 1; }
run=$(basename "$exp"); out="$exp/results/$arm/$aid"; mkdir -p "$out"
for r in $(seq 1 "$repeats"); do
  d="$out/run$r"; mkdir -p "$d"
  if ! bash "$ad" "$asset" "$d" "${extra[@]}" > "$d/adapter.log" 2>&1; then
    echo "  run$r: adapter '$adapter' failed (see $d/adapter.log)" >&2; continue
  fi
  sarif=$(ls "$d"/*.sarif 2>/dev/null | head -1)
  [ -n "$sarif" ] || { echo "  run$r: no *.sarif in $d" >&2; continue; }
  python3 "$here/lib/sarif_to_findings.py" "$sarif" --tool "$arm" --tool-run "$r" \
      --run "$run" --arm "$arm" --target "$aid" --sample 1 --append "$exp/findings.jsonl"
done
echo "SCANNED=$aid arm=$arm repeats=$repeats"
