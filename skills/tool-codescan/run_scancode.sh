#!/usr/bin/env bash
# Run the sdlc `scan-code` LLM reviewer (standalone run_scan.py) N times on a target tree and
# append normalised rows (tool=scan-code, tool_run=r) to <EXP>/findings.jsonl.
#   bash run_scancode.sh <EXP> <target-id> <tree> [--repeats 3] [--arm scan-code] [--model M]
# Env: AISEC_GATEWAY_BASE_URL, AISEC_GATEWAY_API_KEY, AISEC_MODEL (or --model).
set -euo pipefail
exp="${1:?}"; tid="${2:?}"; tree="${3:?}"; shift 3
repeats=3; arm="scan-code"; model="${AISEC_MODEL:-}"
while [ $# -gt 0 ]; do case "$1" in --repeats) repeats="$2"; shift 2;; --arm) arm="$2"; shift 2;; --model) model="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"
scan_dir=$(bash "$here/lib/find_sdlc.sh" --plugin code-scan --skill scan-code)
run=$(basename "$exp"); out="$exp/results/$arm/$tid"; mkdir -p "$out"
t0=$(date +%s)
for r in $(seq 1 "$repeats"); do
  d="$out/run$r"; mkdir -p "$d"
  AISEC_MODEL="$model" python3 "$scan_dir/scripts/run_scan.py" --path "$tree" --out "$d" > "$d/run.log" 2>&1 || { echo "run$r failed" >&2; continue; }
  sarif=$(ls "$d"/*.sarif | head -1)
  python3 "$here/lib/sarif_to_findings.py" "$sarif" --tool scan-code --tool-run "$r" --strip-prefix "$tree" \
      --run "$run" --arm "$arm" --target "$tid" --sample 1 --append "$exp/findings.jsonl"
done
kloc=$(find "$tree" -type f \( -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.go' -o -name '*.java' -o -name '*.rb' -o -name '*.php' -o -name '*.c' -o -name '*.cpp' \) -not -path '*/node_modules/*' -exec cat {} + 2>/dev/null | wc -l | awk '{printf "%.1f", $1/1000}')
python3 "$here/lib/manifest.py" "$exp" append-sample "{\"run\":\"$run\",\"arm\":\"$arm\",\"target\":\"$tid\",\"sample\":1,\"kloc\":$kloc,\"wall_s\":$(( $(date +%s)-t0 )),\"model\":\"$model\"}" >/dev/null
echo "SCANNED=$tid kloc=$kloc repeats=$repeats"
