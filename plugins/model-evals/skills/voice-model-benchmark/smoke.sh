#!/usr/bin/env bash
# Keyless smoke test: both lanes, end to end, against the bundled mock realtime server, for two
# mock models, then one scorecard across them. No key, no model, no packages (tone audio).
#
#   bash smoke.sh [output dir]          # default: a new temporary directory
#
# The two mock models are two reply profiles of mock_realtime_server.py ("guarded" and
# "open"). Their numbers describe the mock's rule and nothing else.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
OUT="${1:-$(mktemp -d "${TMPDIR:-/tmp}/voice-model-benchmark-smoke.XXXXXX")}"
mkdir -p "$OUT"
for model in mock-realtime-guarded mock-realtime-open; do
  if [ -e "$OUT/$model/samples.jsonl" ]; then
    echo "smoke.sh: $OUT/$model already holds a run; pass an empty output directory" >&2
    exit 2
  fi
  "$PY" run_benchmark.py --target mock --model "$model" --judge mock --tts tone \
    --depth smoke --out "$OUT/$model" 2>"$OUT/$model.log" >/dev/null
  echo "ran $model -> $OUT/$model (log: $OUT/$model.log)"
done
"$PY" lib/scorecard.py --threats threats.json \
  --samples "$OUT"/mock-realtime-guarded/samples.jsonl "$OUT"/mock-realtime-open/samples.jsonl \
  --out "$OUT" --title "voice-model-benchmark smoke scorecard (two mock models)" >/dev/null
echo "scorecard: $OUT/scorecard.md"
cat "$OUT/scorecard.md"
