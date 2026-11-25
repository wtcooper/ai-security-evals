#!/usr/bin/env bash
# Keyless smoke test of the whole code-kind path: two "tools" (replayed SARIF) against a tiny
# tree with three known vulnerabilities -> register the plan -> normalise -> match to ground
# truth -> statistics.
#   bash tests/smoke.sh            (prints the per-tool match report)
set -euo pipefail
skill="$(cd "$(dirname "$0")" && cd .. && pwd)"
fx="$skill/tests/fixtures/smoke"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
exp="$(cd "$work" && EVALS_DIR="$work/evals" bash "$skill/new_experiment.sh" security-tool-benchmark smoke \
        --benchmark smoke-fixture --arms tool-a,tool-b | tail -1 | cut -d= -f2)"
python3 "$skill/plan.py" "$exp" --kind code --arms tool-a,tool-b --baseline tool-a \
  --benchmark smoke-fixture --depth smoke --targets 1 --corpus "$fx/ground_truth.jsonl" 2>/dev/null
for arm in tool-a tool-b; do
  bash "$skill/code/run_scanner.sh" "$exp" smoke "$fx/tree" --arm "$arm" --adapter replay -- --sarif "$fx/$arm.sarif"
done
python3 "$skill/code/match.py" "$exp/findings.jsonl" "$fx/ground_truth.jsonl" \
  --out "$exp/matched.jsonl" --report "$exp/match.md" --group-by tool --runs "$exp/runs.jsonl"
python3 "$skill/lib/evalstats.py" "$exp/matched.jsonl" --samples "$exp/samples.jsonl" \
  --pair-on target --baseline tool-a --out "$exp/summary.md" --json "$exp/summary.json" >/dev/null
cat "$exp/match.md"
test -s "$exp/summary.md" && grep -q "No departures" "$exp/match.md" && \
  echo "SMOKE OK: plan.json, findings.jsonl, samples.jsonl, matched.jsonl, summary.md written"
