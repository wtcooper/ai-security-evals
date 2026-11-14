#!/usr/bin/env bash
# Keyless smoke test of the whole code-kind path: two "tools" (replayed SARIF) against a tiny
# tree with three known vulnerabilities -> normalise -> match to ground truth -> statistics.
#   bash tests/smoke.sh            (prints the per-tool match report)
set -euo pipefail
skill="$(cd "$(dirname "$0")" && cd .. && pwd)"
fx="$skill/tests/fixtures/smoke"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
exp="$(cd "$work" && EVALS_DIR="$work/evals" bash "$skill/new_experiment.sh" security-tool-benchmark smoke \
        --benchmark smoke-fixture --arms tool-a,tool-b | tail -1 | cut -d= -f2)"
for arm in tool-a tool-b; do
  bash "$skill/code/run_scanner.sh" "$exp" smoke "$fx/tree" --arm "$arm" --adapter replay -- --sarif "$fx/$arm.sarif"
done
python3 "$skill/code/match.py" "$exp/findings.jsonl" "$fx/ground_truth.jsonl" \
  --out "$exp/matched.jsonl" --report "$exp/match.md" --group-by tool
python3 "$skill/lib/evalstats.py" "$exp/matched.jsonl" --samples "$exp/samples.jsonl" \
  --pair-on target --baseline tool-a --out "$exp/summary.md" --json "$exp/summary.json" >/dev/null
cat "$exp/match.md"
test -s "$exp/summary.md" && echo "SMOKE OK: findings.jsonl, samples.jsonl, matched.jsonl, summary.md written"
